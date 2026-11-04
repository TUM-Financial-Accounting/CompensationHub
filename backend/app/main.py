"""HTTP API over the harmonised panel: one read route per dashboard view, plus the Add data form
(the only routes that write the panel, disabled when READ_ONLY is set), feedback posts (kept in
Postgres at DATABASE_URL) and the assistant.

Pay statistics use full-year executives (≥ 360 days in office) so that joiners, leavers and
CEO hand-overs do not drag medians down. `scope=dax` restricts to DAX firm-years, the only
universe that exists on both sides of the 2021/22 regime break.
"""

import base64
import json
import os
import threading
from contextlib import asynccontextmanager
from dataclasses import asdict
from typing import Literal

import numpy as np
import pandas as pd
import psycopg
from fastapi import FastAPI, HTTPException
from fastapi.encoders import jsonable_encoder
from fastapi.responses import StreamingResponse
from fastapi.staticfiles import StaticFiles
from psycopg.rows import dict_row

from . import assistant, entry, reference
from . import schemas as s
from .forecast import BAND, HORIZONS, MODEL_IDS, MODELS, TARGETS, get_forecasts, what_if
from .panel import COMPONENTS, ROOT, Panel, get_panel
from .peers import (BASELINE, HIGH, METHOD_IDS, METHODS, MIN_PAY, MIN_PEER_FIRMS, Benchmarks,
                    Method, fragility, get_benchmarks)

Scope = Literal["dax", "all"]
Role = Literal["CEO", "CFO", "Member"]


@asynccontextmanager
async def lifespan(_: FastAPI):
    get_panel()  # build (or load the cached) panel before the first request
    threading.Thread(target=get_forecasts, daemon=True).start()  # peers and forecasts
    yield


app = FastAPI(title="DAX executive compensation panel", lifespan=lifespan)


def records(df: pd.DataFrame) -> list[dict]:
    """JSON-safe rows: NaN becomes None."""
    return df.astype(object).where(df.notna(), None).to_dict("records")


def quantiles(df: pd.DataFrame, by: list[str]) -> pd.DataFrame:
    g = df.groupby(by)["total"]
    out = g.quantile([0.1, 0.25, 0.5, 0.75, 0.9]).unstack()
    out.columns = ["p10", "p25", "median", "p75", "p90"]
    return out.assign(n=g.size()).reset_index()


def in_scope(df: pd.DataFrame, scope: Scope) -> pd.DataFrame:
    return df[df["index"] == "DAX"] if scope == "dax" else df


def full_year(p: Panel) -> pd.DataFrame:
    return p.execs[p.execs["full_year"]]


def ceos(p: Panel, full_year_only: bool = False) -> pd.DataFrame:
    """One CEO per firm-year: prefer full-year CEOs, then the higher-paid (co-CEOs)."""
    e = p.execs[p.execs["role"] == "CEO"]
    if full_year_only:
        e = e[e["full_year"]]
    e = e.sort_values(["full_year", "total"], ascending=False)
    return e.drop_duplicates(["firm_id", "year"])


def with_firm_names(p: Panel, df: pd.DataFrame) -> pd.DataFrame:
    return df.merge(p.firms[["firm_id", "name"]].rename(columns={"name": "firm"}), on="firm_id")


def with_design(p: Panel) -> pd.DataFrame:
    """Executive-years that disclose plan design (named KPIs, caps) — the §162 sources."""
    return p.execs[p.execs["sti_kpis"].map(lambda v: isinstance(v, list))]


def extras(df: pd.DataFrame, columns: list[str]) -> list[dict]:
    """Columns added by attribute tables, as one dict per row."""
    return records(df[columns]) if columns else [{} for _ in range(len(df))]


def dax_ceo_quantiles(p: Panel) -> pd.DataFrame:
    e = in_scope(full_year(p), "dax")
    return quantiles(e[e["role"] == "CEO"], ["year"]).assign(group="CEO")


@app.get("/api/summary", response_model=s.Summary)
def summary():
    p = get_panel()
    fy, e = p.firm_years, p.execs
    ceo_q = dax_ceo_quantiles(p).set_index("year")
    female = in_scope(e, "dax").groupby("year")["female"].mean()
    first, last = int(fy["year"].min()), int(fy["year"].max())
    ratio = ceo_board(p)
    return {
        "first_year": first,
        "last_year": last,
        "n_firms": len(p.firms),
        "n_people": e["person_id"].nunique(),
        "n_exec_years": len(e),
        "n_firm_years": len(fy),
        "ceo_median_first": ceo_q.loc[first, "median"],
        "ceo_median_last": ceo_q.loc[last, "median"],
        "female_share_first": female[first],
        "female_share_last": female[last],
        "pay_ratio_median_last": ratio.loc[ratio["year"] == last, "pay_ratio"].median(),
        "ceo_pay": records(ceo_q.reset_index()),
    }


@app.get("/api/trends", response_model=s.Trends)
def trends(scope: Scope = "dax"):
    p = get_panel()
    e = in_scope(full_year(p), scope)

    levels = quantiles(e.assign(group=e["role"]), ["year", "group"])

    pooled = e[e["reported"]].groupby("year")[COMPONENTS].sum()  # blanks = not reported
    mix = (pooled.div(pooled.sum(axis=1), axis=0).stack()
           .rename("share").rename_axis(["year", "component"]).reset_index())

    ceo = e[e["role"] == "CEO"].groupby(["firm_id", "year"])["total"].max()
    others = e[e["role"] != "CEO"].groupby(["firm_id", "year"])["total"].median()
    premium = (ceo / others).dropna().groupby("year").agg(value="median", n="size")

    fy = in_scope(p.firm_years, scope)
    opt_out = fy.groupby("year")["opt_out"].agg(value="mean", n="size")

    return {
        "levels": records(levels),
        "mix": records(mix),
        "ceo_premium": records(premium.reset_index()),
        "opt_out_rate": records(opt_out.reset_index()),
    }


@app.get("/api/firms", response_model=list[s.FirmListItem])
def firms():
    p = get_panel()
    last = p.firm_years.sort_values("year").drop_duplicates("firm_id", keep="last")
    ceo = ceos(p)[["firm_id", "year", "name", "total"]].rename(
        columns={"name": "ceo_name", "total": "ceo_total"})
    df = (p.firms[["firm_id", "name", "first_year", "last_year"]]
          .merge(last[["firm_id", "year", "index", "board_total"]], on="firm_id")
          .merge(ceo, on=["firm_id", "year"], how="left")
          .rename(columns={"firm_id": "id"})
          .sort_values("name", key=lambda n: n.str.lower()))
    return records(df)


@app.get("/api/firms/{firm_id}", response_model=s.FirmDetail)
def firm(firm_id: str):
    p = get_panel()
    info = p.firms[p.firms["firm_id"] == firm_id]
    if info.empty:
        raise HTTPException(404, f"Unknown firm '{firm_id}'")
    execs = with_firm_names(p, p.execs[p.execs["firm_id"] == firm_id])
    design = ceos(p)
    design = design[(design["firm_id"] == firm_id)
                    & design["sti_kpis"].map(lambda v: isinstance(v, list))].sort_values("year")
    for col in ["sti_kpis", "lt_kpis"]:
        design[col] = design[col].map(
            lambda ks: [{"name": k, "categories": p.kpi_category[k]} for k in ks])
    dax = dax_ceo_quantiles(p).rename(columns={"median": "value"})
    years = p.firm_years[p.firm_years["firm_id"] == firm_id]
    firm = records(info.rename(columns={"firm_id": "id"}))[0]
    firm["attributes"] = extras(info, p.extra_firm_columns)[0]
    return {
        "firm": firm,
        "years": [{**y, "extra": x} for y, x in
                  zip(records(years), extras(years, p.extra_year_columns))],
        "execs": records(execs.sort_values(["year", "total"], ascending=[True, False])),
        "design": records(design[["year", "sti_kpis", "lt_kpis", "sti_cap_pct", "lti_cap"]]),
        "dax_ceo_median": records(dax[["year", "value", "n"]]),
    }


@app.get("/api/executives", response_model=list[s.ExecYear])
def executives(year: int):
    p = get_panel()
    e = p.execs[p.execs["year"] == year]
    if e.empty:
        raise HTTPException(404, f"No executives in {year}")
    return records(with_firm_names(p, e).sort_values("total", ascending=False))


@app.get("/api/people/{person_id}", response_model=s.Person)
def person(person_id: str):
    p = get_panel()
    e = p.execs[p.execs["person_id"] == person_id]
    if e.empty:
        raise HTTPException(404, f"Unknown person '{person_id}'")
    latest = e.sort_values("year").iloc[-1]
    return {
        "id": person_id,
        "name": latest["name"],
        "female": bool(latest["female"]),
        "german": bool(latest["german"]),
        "birth_year": None if pd.isna(latest["birth_year"]) else int(latest["birth_year"]),
        "years": records(with_firm_names(p, e).sort_values(["year", "firm_id"])),
    }


@app.get("/api/design", response_model=s.Design)
def design():
    p = get_panel()
    m = with_firm_names(p, with_design(p))
    n_firms = m.groupby("year")["firm_id"].nunique()

    cells = []
    for plan, col in [("STI", "sti_kpis"), ("Long-term", "lt_kpis")]:
        x = m[["year", "firm_id", "firm", col]].explode(col).dropna(subset=[col])
        x = x.assign(category=x[col].map(p.kpi_category)).explode("category")
        cells.append(x.groupby(["year", "firm_id", "firm", "category"])[col]
                     .agg(lambda names: sorted(set(names))).rename("names")
                     .reset_index().assign(plan=plan))
    cells = pd.concat(cells, ignore_index=True)
    usage = cells.groupby(["year", "plan", "category"]).size().rename("n").reset_index()
    usage["share"] = usage["n"] / usage["year"].map(n_firms)

    ceo = ceos(p)
    ceo = with_firm_names(p, ceo[ceo["year"].isin(n_firms.index)]).merge(
        p.firm_years[["firm_id", "year", "sti_esg_share", "lti_esg_share",
                      "sti_esg_kind", "lti_esg_kind"]],
        on=["firm_id", "year"], how="left")
    caps = ceo.groupby("year").agg(n=("firm_id", "size"), sti_capped=("sti_cap", "sum"),
                                   lti_capped=("lti_cap", "sum"),
                                   sti_cap_median=("sti_cap_pct", "median"))
    return {"kpi_usage": records(usage), "kpi_cells": records(cells), "ceos": records(ceo),
            "caps": records(caps.reset_index())}


def ceo_board(p: Panel) -> pd.DataFrame:
    """Full-year CEOs in years with workforce or TSR data: pay ratio, TSR, change vs. prior year."""
    c = ceos(p, full_year_only=True)
    prev = c[["person_id", "firm_id", "year", "total"]].assign(year=lambda d: d["year"] + 1)
    c = c.merge(prev, on=["person_id", "firm_id", "year"], how="left", suffixes=("", "_prev"))
    c = c.merge(p.firm_years[["firm_id", "year", "avg_staff_cost", "tsr"]], on=["firm_id", "year"])
    has_data = c.groupby("year")[["avg_staff_cost", "tsr"]].transform("count").sum(axis=1) > 0
    c = c[has_data]
    c["pay_ratio"] = c["total"] / c["avg_staff_cost"]
    c["pay_change"] = c["total"] / c["total_prev"] - 1
    return with_firm_names(p, c)


@app.get("/api/board", response_model=s.Board)
def board():
    p = get_panel()
    diversity = []
    for scope in ("dax", "all"):
        e = in_scope(p.execs, scope).assign(age=lambda d: d["year"] - d["birth_year"])
        g = e.groupby("year")
        diversity.append(pd.DataFrame({
            "female_share": g["female"].mean(),
            "non_german_share": 1 - g["german"].mean(),
            "median_age": g["age"].median(),
            "n": g.size(),
        }).reset_index().assign(scope=scope))

    known = p.execs.dropna(subset=["internal"])
    coverage = known.groupby("year").size() / p.execs.groupby("year").size()
    known = known[known["year"].map(coverage) >= 0.8]
    hiring = pd.concat([
        known.assign(role="Board"),
        known[known["role"] == "CEO"].assign(role="CEO"),
    ]).groupby(["year", "role"])["internal"].agg(
        external_share=lambda s: (s == "Extern").mean(), n="size").reset_index()

    c = ceo_board(p)
    ratio = c.dropna(subset=["pay_ratio"]).groupby("year")["pay_ratio"].agg(value="median", n="size")
    pairs = c.dropna(subset=["tsr", "pay_change"]).groupby("year")
    corr = pd.DataFrame({"value": pairs[["tsr", "pay_change"]].apply(
                             lambda g: g["tsr"].corr(g["pay_change"])),
                         "n": pairs.size()}).dropna()
    return {
        "diversity": records(pd.concat(diversity)),
        "ceos": records(c),
        "hiring": records(hiring),
        "pay_ratio_median": records(ratio.reset_index()),
        "tsr_pay_corr": records(corr.reset_index()),
    }


@app.get("/api/quality", response_model=s.Quality)
def quality():
    p = get_panel()
    e, fy = p.execs, p.firm_years
    exec_fields = {"Fixed salary": "fixed", "Short-term bonus": "sti",
                   "Multi-year bonus": "mti", "Share-based pay": "lti", "Other benefits": "other",
                   "Pension cost": "pension", "One-time payments": "one_time",
                   "Birth year": "birth_year", "Days in office": "days"}
    firm_fields = {"Index listing": "index", "Employees": "employees",
                   "Shareholder return": "tsr", "ESG share in STI": "sti_esg_share",
                   **{c: c for c in p.extra_year_columns}}
    coverage = [
        pd.DataFrame({"field": label, "share": df.groupby("year")[col]
                      .apply(lambda v: v.notna().mean())}).reset_index()
        for df, fields in [(e, exec_fields), (fy, firm_fields)]
        for label, col in fields.items()
    ]
    universe = fy.assign(index=fy["index"].fillna("Other")).groupby(["year", "index"]).agg(
        firms=("firm_id", "size"), opt_out=("opt_out", "sum")).reset_index()
    universe = universe.merge(
        e.assign(index=e["index"].fillna("Other")).groupby(["year", "index"]).size()
        .rename("execs").reset_index(), on=["year", "index"], how="left").fillna({"execs": 0})
    return {
        "coverage": records(pd.concat(coverage)),
        "universe": records(universe),
        "sources": p.sources,
        "issues": p.issues,
    }


# --------------------------------------------------------------------------- peer benchmark
# Computed in peers.py; these routes only select and shape. Methodology: docs/peers.md.

BASELINE_METHOD = Method(BASELINE, "baseline", "All other firms",
                         "Every other firm in the same year and role.",
                         "Reference point: no peer selection at all.")
RESULT = ["method", "n_peers", "n_firms", "p10", "p25", "peer_median", "p75", "p90", "ratio",
          "percentile", "verdict", "label"]


def method_info(b: Benchmarks, method: str) -> dict:
    meta = next((m for m in METHODS if m.id == method), BASELINE_METHOD)
    score = b.scorecard.set_index("method").loc[method]
    return {**asdict(meta), "coverage": score["coverage"],
            "n_firms_median": score["n_firms_median"], "fit": score["fit"],
            "pull": score["pull"], "pull_se": score["pull_se"], "stability": score["stability"],
            "above_share": score["above_share"]}


def results_by_row(results: pd.DataFrame) -> dict[int, list[dict]]:
    return {row: records(g[RESULT]) for row, g in results.groupby(level="row")}


def ceo_verdicts(b: Benchmarks) -> pd.DataFrame:
    """Per CEO-year: definitions with verdict 'above', definitions with a result, ratio range."""
    res = b.results[b.results["method"].isin(METHOD_IDS)
                    & b.results.index.isin(b.rows.index[b.rows["role"] == "CEO"])]
    g = res.groupby(level="row")
    per = pd.DataFrame({"above": (res["verdict"] == "above").groupby(level="row").sum(),
                        "n_methods": g.size(), "ratio_min": g["ratio"].min(),
                        "ratio_max": g["ratio"].max()})
    per["robust"] = (per["above"] > 0) & (per["above"] == per["n_methods"])
    per["fragile"] = (per["above"] > 0) & ~per["robust"]
    return per.join(b.rows[["year", "firm_id", "firm", "person_id", "name", "total"]])


@app.get("/api/peers", response_model=s.PeerOverview)
def peer_overview():
    b = get_benchmarks()
    per = ceo_verdicts(b)
    by_year = per.groupby("year").agg(robust=("robust", "sum"), fragile=("fragile", "sum"),
                                      n=("robust", "size"))
    robust = per[per["robust"]].sort_values(["year", "ratio_min"], ascending=[False, False])
    return {
        "methods": [method_info(b, m) for m in METHOD_IDS],
        "baseline": method_info(b, BASELINE),
        "agreement": records(b.agreement),
        "convergence": records(b.convergence),
        "years": sorted(b.rows["year"].unique().tolist()),
        "high": HIGH,
        "min_peer_firms": MIN_PEER_FIRMS,
        "min_pay": MIN_PAY,
        "n_rows": len(b.rows),
        "n_common": b.n_common,
        "ceo_flagged_any": int((per["robust"] | per["fragile"]).sum()),
        "ceo_flagged_all": int(per["robust"].sum()),
        "ceo_by_year": records(by_year.reset_index()),
        "robust_ceos": records(robust),
        "fragility": records(fragility(b.rows, b.results)),
    }


@app.get("/api/peers/verdicts", response_model=s.PeerVerdicts)
def peer_verdicts(year: int, role: Role = "CEO"):
    """Every executive of a year and role with the benchmark under each definition."""
    b = get_benchmarks()
    rows = b.rows[(b.rows["year"] == year) & (b.rows["role"] == role)]
    if rows.empty:
        raise HTTPException(404, f"No benchmarked {role}s in {year}")
    res = b.results[b.results["method"].isin(METHOD_IDS) & b.results.index.isin(rows.index)]
    by_row = results_by_row(res)
    out = [{**r, "results": by_row.get(row, []),
            "n_above": sum(x["verdict"] == "above" for x in by_row.get(row, []))}
           for row, r in zip(rows.index, records(rows))]
    return {"year": year, "role": role, "rows": out}


@app.get("/api/peers/{method}", response_model=s.PeerMethodView)
def peer_method(method: str, year: int | None = None, role: Role = "CEO"):
    """One definition in one year and role: every executive with their result (or none), the
    chosen peer firms, the peer groups, and what is specific to the definition."""
    if method not in METHOD_IDS:
        raise HTTPException(404, f"Unknown peer definition '{method}'")
    b = get_benchmarks()
    years = sorted(b.rows["year"].unique().tolist())
    year = year or years[-1]
    rows = b.rows[(b.rows["year"] == year) & (b.rows["role"] == role)]
    if rows.empty:
        raise HTTPException(404, f"No benchmarked {role}s in {year}")
    res = b.results[(b.results["method"] == method) & b.results.index.isin(rows.index)]
    by_row = results_by_row(res)
    titles = reference.naics_titles()
    executives = [{**r, "naics_title": titles[r["naics"]], "result": (by_row.get(row) or [None])[0]}
                  for row, r in zip(rows.index, records(rows))]
    links = b.links[(b.links["method"] == method) & (b.links["year"] == year)
                    & (b.links["role"] == role)]
    if method in ("size", "industry", "cluster"):  # group membership: no score to show
        links = links.assign(score=None)
    groups = res.join(rows[["firm_id", "total"]]).groupby("label").agg(
        n_firms=("firm_id", "nunique"), n_execs=("total", "size"), median=("total", "median"))
    extras = {}
    if method == "cluster":
        extras = {"clusters": records(b.clusters), "cluster_choice": records(b.cluster_choice)}
    if method == "forest":
        extras = {"importance": records(b.importance), "forest_fit": b.forest_fit}
    summary = {"n": len(rows), "n_benchmarked": len(res),
               "n_firms_median": res["n_firms"].median() if len(res) else None,
               "above": int((res["verdict"] == "above").sum()),
               "below": int((res["verdict"] == "below").sum())}
    return {"method": method_info(b, method), "year": year, "role": role, "years": years,
            "summary": summary, "executives": executives, "links": records(links[["firm_id", "peer_firm", "score"]]),
            "groups": records(groups.reset_index()), **extras}


@app.get("/api/firms/{firm_id}/peers", response_model=list[s.FirmPeerRow])
def firm_peers(firm_id: str):
    """The firm's full-year CEOs against their peers, every year and definition."""
    b = get_benchmarks()
    rows = b.rows[(b.rows["firm_id"] == firm_id) & (b.rows["role"] == "CEO")]
    res = b.results[b.results["method"].isin(METHOD_IDS) & b.results.index.isin(rows.index)]
    out = rows[["year", "person_id", "name", "total"]].join(res, how="inner")
    return [{**r, "result": {k: r[k] for k in RESULT}} for r in records(out)]


# --------------------------------------------------------------------------- pay prediction


def target_list() -> list[dict]:
    return [{"id": t, "label": label} for t, label in TARGETS.items()]


def model_info(model_id: str) -> dict:
    return asdict(next(m for m in MODELS if m.id == model_id))


@app.get("/api/prediction", response_model=s.PredictionOverview)
def prediction():
    f = get_forecasts()
    demo = {c["feature"]: c["coef"] for c in f.extras["linear_demo"]["coefficients"]}
    h1 = f.live[f.live["h"] == 1]
    best = h1[h1["model"] == h1["target"].map(f.best)].pivot_table(
        index="person_id", columns="target", values="value")
    parts = best[[c for c in COMPONENTS if c in best]].sum(axis=1, min_count=1)
    return {
        "models": [model_info(m) for m in MODEL_IDS],
        "targets": target_list(),
        "scorecard": records(f.scorecard),
        "by_horizon": records(f.by_horizon),
        "paid": records(f.paid),
        "best": f.best, "best_rule": f.best_rule, "band": BAND,
        "peer_method": f.peer_method, "origins": f.origins, "last_year": f.last_year,
        "latest_regime": f.now["regime"].mode()[0],
        "gap_woman": np.expm1(demo["Woman"]), "gap_german": np.expm1(demo["German nationality"]),
        "mlp_seeds": f.extras["mlp"]["seeds"],
        "coherence": (parts / best["total"]).median() if "total" in best else None,
    }


@app.get("/api/prediction/{model}", response_model=s.PredictionModelView)
def prediction_model(model: str, target: str = "total"):
    if model not in MODEL_IDS:
        raise HTTPException(404, f"Unknown model '{model}'")
    if target not in TARGETS:
        raise HTTPException(404, f"Unknown target '{target}'")
    f = get_forecasts()
    bt = f.backtest[(f.backtest["target"] == target)]
    mine = bt[bt["model"] == model].assign(err=lambda d: d["y"] - d["pred"])
    ref = bt[bt["model"] == "drift"].set_index(["person_id", "firm", "year", "h"])["pred"]
    key = pd.MultiIndex.from_frame(mine[["person_id", "firm", "year", "h"]].astype(object))
    mine = mine.assign(ref=(mine["y"].to_numpy() - ref.reindex(key).to_numpy()))
    roles = mine.groupby(["regime", "role"], observed=True).agg(
        n=("err", "size"), mae=("err", lambda e: e.abs().mean()),
        mae_ref=("ref", lambda e: e.abs().mean())).reset_index()
    h1 = mine[mine["h"] == 1]
    sample = h1.sample(min(len(h1), 1500), random_state=0)
    misses = mine.reindex(mine["err"].abs().sort_values(ascending=False).index).head(15)
    calib = f.calibration[(f.calibration["model"] == model) & (f.calibration["target"] == target)]
    hz = f.by_horizon[f.by_horizon["model"].isin([model, "drift"]) & (f.by_horizon["target"] == target)]
    extras = dict(f.extras.get(model, {}))
    if "firms" in extras:
        extras["firms"] = extras["firms"][:25]
    return {
        "model": model_info(model), "target": target, "targets": target_list(),
        "scores": records(f.scorecard[f.scorecard["model"] == model]),
        "by_horizon": records(hz), "calibration": records(calib[["regime", "level", "achieved"]]),
        "by_role": records(roles), "best": f.best,
        "points": [{"regime": r, "h": int(h), "actual": float(np.exp(y)), "predicted": float(np.exp(p))}
                   for r, h, y, p in sample[["regime", "h", "y", "pred"]].itertuples(index=False)],
        "misses": [{"person_id": r.person_id, "name": r.name, "firm": r.firm, "year": int(r.year),
                    "h": int(r.h), "actual": float(np.exp(r.y)), "predicted": float(np.exp(r.pred)),
                    "error": float(r.err)} for r in misses.itertuples()],
        **extras,
    }


def peer_quantiles(f, b, person: pd.Series, method: str) -> tuple[list[dict], list[dict]]:
    """The executive's value of every target among the peers of `method` in the latest year."""
    links = b.links[(b.links["method"] == method) & (b.links["firm_id"] == person["firm_id"])
                    & (b.links["year"] == person["year"]) & (b.links["role"] == person["role"])]
    pool = f.now[f.now["firm_id"].isin(links["peer_firm"]) & (f.now["role"] == person["role"])]
    out = []
    for t in TARGETS:
        v = pool[t][pool[t] > 0]
        if len(v) < MIN_PEER_FIRMS:
            continue
        own = person[t] if person[t] > 0 else None
        out.append({"target": t, "value": own, "n": len(v),
                    **dict(zip(["p10", "p25", "median", "p75", "p90"],
                               v.quantile([0.1, 0.25, 0.5, 0.75, 0.9]))),
                    "percentile": None if own is None else float(((v < own) + 0.5 * (v == own)).mean())})
    firms = pool.drop_duplicates("firm_id")[["firm_id", "firm"]].sort_values("firm")
    return out, records(firms)


@app.get("/api/people/{person_id}/prediction", response_model=s.PersonPrediction)
def person_prediction(person_id: str, peer_method: str | None = None):
    """Forecasts of every pay item from the latest year (every model; `best` names the one to
    show), with three reference points: the executive's own history, the board, and the peers
    of one peer definition (`peer_method`, default the best on the peer scorecard)."""
    f, b, p = get_forecasts(), get_benchmarks(), get_panel()
    now = f.now[f.now["person_id"] == person_id]
    if now.empty:
        raise HTTPException(404, f"No forecast for '{person_id}': not a full-year executive in "
                                 f"{f.last_year}")
    x = now.iloc[0]
    method = peer_method or f.peer_method
    if method not in METHOD_IDS:
        raise HTTPException(404, f"Unknown peer definition '{method}'")
    e = p.execs[(p.execs["person_id"] == person_id) & (p.execs["firm_id"] == x["firm_id"])
                & p.execs["full_year"]].sort_values("year")
    history = [{"target": t, "years": [{"year": int(y), "value": None if pd.isna(v) else float(v)}
                                       for y, v in zip(e["year"], e[t])]} for t in TARGETS]
    live = f.live[(f.live["person_id"] == person_id) & (f.live["firm_id"] == x["firm_id"])]
    lo, hi = f"lo{BAND:g}", f"hi{BAND:g}"
    forecasts = live[["target", "model", "year", "h", "value", lo, hi, "source"]].rename(
        columns={lo: "lo", hi: "hi"})
    board = f.now[(f.now["firm_id"] == x["firm_id"])]
    ceo = board.loc[board["role"] == "CEO", "total"].max()
    colleagues = [{"person_id": r.person_id, "name": r.name, "role": r.role, "total": r.total,
                   "ratio_to_ceo": r.total / ceo if ceo > 0 else None,
                   "is_self": r.person_id == person_id}
                  for r in board.sort_values("total", ascending=False).itertuples()]
    staff = p.firm_years.loc[(p.firm_years["firm_id"] == x["firm_id"])
                             & (p.firm_years["year"] == x["year"]), "avg_staff_cost"]
    staff = staff.iloc[0] if len(staff) and pd.notna(staff.iloc[0]) else None
    peers, peer_firms = peer_quantiles(f, b, x, method)
    paid = f.live_paid[(f.live_paid["person_id"] == person_id)
                       & (f.live_paid["firm_id"] == x["firm_id"])]
    return {
        "person_id": person_id, "name": x["name"], "firm_id": x["firm_id"], "firm": x["firm"],
        "role": x["role"], "year": int(x["year"]), "regime": x["regime"], "best": f.best,
        "band": BAND, "history": history, "forecasts": records(forecasts),
        "paid": records(paid[["target", "year", "p"]]), "board": colleagues,
        "avg_staff_cost": staff, "staff_ratio": x["total"] / staff if staff else None,
        "method": method, "methods": [{"id": m.id, "name": m.name} for m in METHODS],
        "peer_firms": peer_firms, "peers": peers,
    }


@app.get("/api/firms/{firm_id}/prediction", response_model=list[s.FirmForecast])
def firm_prediction(firm_id: str):
    """Next year's total pay for each executive of the firm's latest year (best model)."""
    f = get_forecasts()
    model = f.best["total"]
    live = f.live[(f.live["firm_id"] == firm_id) & (f.live["target"] == "total")
                  & (f.live["model"] == model) & (f.live["h"] == 1)]
    now = f.now[f.now["firm_id"] == firm_id][["person_id", "name", "role", "total"]]
    lo, hi = f"lo{BAND:g}", f"hi{BAND:g}"
    out = now.merge(live[["person_id", "year", "value", lo, hi]], on="person_id")
    return records(out.rename(columns={lo: "lo", hi: "hi"}).assign(model=model))


@app.get("/api/whatif", response_model=s.WhatIf)
def whatif(person_id: str, years: int = 1, role: Role | None = None,
           index: Literal["DAX", "MDAX", "none"] | None = None, board: int | None = None,
           employees: float | None = None, growth: float | None = None):
    """What an executive of the latest year would earn with other characteristics (role, index,
    board size, employees) or another yearly growth. Associations, not causal effects."""
    if not 1 <= years <= max(HORIZONS):
        raise HTTPException(422, f"years must be 1–{max(HORIZONS)}")
    out = what_if(get_forecasts(), person_id, years, role, index, board, employees, growth)
    if out is None:
        raise HTTPException(404, f"'{person_id}' is not a full-year executive of the latest year")
    return out


# --------------------------------------------------------------------------- data entry


def writable() -> None:
    if os.getenv("READ_ONLY", "").strip().lower() not in ("", "0", "false", "no"):
        raise HTTPException(403, "This dashboard is read-only (READ_ONLY is set).")


def data_table(table_id: str) -> entry.Table:
    t = entry.table(table_id)
    if t is None:
        raise HTTPException(404, f"Unknown table '{table_id}'")
    return t


@app.get("/api/tables", response_model=list[s.DataTable])
def data_tables():
    """Tables the Add data form can append to, with their columns and current rows."""
    return [entry.describe(t) for t in entry.tables()]


def changes_of(body: s.Changes) -> list[tuple[entry.Table, list[dict]]]:
    return [(data_table(c.table), c.rows) for c in body.changes]


@app.post("/api/rows", response_model=s.Saved)
def add_rows(body: s.Changes):
    """Append rows to one or more tables (the Add data form, or a draft the assistant proposed
    and the user confirmed). One panel build checks them all; on failure nothing is kept."""
    writable()
    changes = changes_of(body)
    try:
        return {"added": entry.add(changes)}
    except Exception as e:  # validation or the panel build: the files are already restored
        raise HTTPException(422, str(e)) from e


@app.post("/api/rows/check", response_model=list[s.RowFindings])
def check_rows(body: s.Changes):
    """Per row: what would stop saving, and for pay rows the plausibility check (typos, own
    forecast, board, peers, pay mix)."""
    return entry.validate(changes_of(body))


@app.post("/api/extract", response_model=s.Extracted)
def extract(body: s.Document):
    """Text of an uploaded PDF or text file, for the assistant to read."""
    try:
        return entry.extract_text(body.name, base64.b64decode(body.data))
    except Exception as e:
        raise HTTPException(422, f"Could not read {body.name}: {e}") from e


@app.delete("/api/tables/{table_id}/rows/{index}", response_model=s.DataTable)
def delete_row(table_id: str, index: int):
    writable()
    t = data_table(table_id)
    try:
        entry.delete(t, index)
    except Exception as e:
        raise HTTPException(422, str(e)) from e
    return entry.describe(t)


# --------------------------------------------------------------------------- feedback

FEEDBACK_TABLE = """CREATE TABLE IF NOT EXISTS feedback (
    id serial PRIMARY KEY,
    author text NOT NULL DEFAULT '',
    body text NOT NULL,
    created timestamptz NOT NULL DEFAULT now())"""


def feedback_db() -> psycopg.Connection:
    url = os.getenv("DATABASE_URL")
    if not url:
        raise HTTPException(503, "Feedback is off: DATABASE_URL is not set.")
    try:
        db = psycopg.connect(url, row_factory=dict_row, connect_timeout=5)
    except psycopg.OperationalError as e:
        raise HTTPException(503, f"Feedback database unreachable: {e}") from e
    db.execute(FEEDBACK_TABLE)
    return db


@app.get("/api/feedback", response_model=list[s.FeedbackPost])
def feedback():
    """Feedback posts users left on the dashboard (bugs, wishes, questions), newest first."""
    with feedback_db() as db:  # ponytail: newest 500 only, paginate when there are more
        return db.execute("SELECT * FROM feedback ORDER BY id DESC LIMIT 500").fetchall()


@app.post("/api/feedback", response_model=s.FeedbackPost)
def post_feedback(body: s.NewFeedback):
    """Save a feedback post. Open to every visitor, also with READ_ONLY set."""
    # ponytail: no login or rate limit; delete spam in the database, add both if it gets abused
    with feedback_db() as db:
        return db.execute("INSERT INTO feedback (author, body) VALUES (%s, %s) RETURNING *",
                          (body.author, body.body)).fetchone()


# --------------------------------------------------------------------------- assistant


@app.get("/api/chat/models", response_model=s.ChatSetup)
def chat_models():
    return {"models": assistant.models(), "examples": assistant.examples()}


@app.post("/api/chat")
def chat(body: s.ChatRequest):
    """Streams the assistant's work as JSON lines: tool calls, their results, the answer."""
    draft = [c.model_dump() for c in body.draft] if body.draft else None
    events = assistant.chat([m.model_dump() for m in body.messages], body.model, body.thinking,
                            body.page, draft)
    return StreamingResponse((json.dumps(jsonable_encoder(e)) + "\n" for e in events),
                             media_type="application/x-ndjson")


# Built dashboard (production image only); mounted last so it never shadows /api.
if (ROOT / "frontend" / "dist").is_dir():
    app.mount("/", StaticFiles(directory=ROOT / "frontend" / "dist", html=True), name="web")
