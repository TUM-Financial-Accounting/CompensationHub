"""Red flags: rules from the law and the governance code next to five statistical detectors.

Every check answers one question for one executive-year (or, for the firm-level rules, one
firm-year): *is there something here a supervisory board or an investor should look at?*

    rules        a jump in pay, pay up while shareholders lost, a one-time payment above two
                 years' pay; per firm-year: no individual disclosure (opt-out)
    context      is pay high for its context? against the peers (peers.py), against last
                 year's forecast (forecast.py), against expected pay (a regression)
    structure    is the pay package as a whole unusual (level, fixed, bonus and long-term
                 shares)? robust distance (MCD), isolation forest

Every flag carries its evidence as a sentence. The model-based detectors are cross-fitted by
firm and fitted within one disclosure regime: the model that scores a firm never saw it, and
2022+ pay is never judged by 2006–2021 norms. They flag the FLAG_SHARE most unusual
executive-years of a regime, so their flags are comparable. The evaluation plants known
anomalies in real executive-years and counts which detector finds them; robustness is in how
many detectors a flag is raised. Method and results: docs/redflags.md.

    uv run python -m app.redflags    print the scorecard
"""

from __future__ import annotations

from collections.abc import Callable, Iterator
from dataclasses import dataclass
from functools import lru_cache
from threading import Lock

import numpy as np
import pandas as pd
from sklearn.covariance import MinCovDet
from sklearn.ensemble import IsolationForest
from sklearn.linear_model import LinearRegression
from sklearn.model_selection import GroupKFold

from . import forecast
from .entry import keur
from .panel import CACHE, Panel, cached, get_panel
from .peers import METHOD_IDS, Benchmarks, get_benchmarks

JUMP = 0.5           # rule: total pay up by more than half on the previous year
PAY_UP = 0.2         # rule: pay up by more than this while the year's TSR was negative
SEVERANCE_CAP = 2.0  # rule: one-time payment above two years' pay (DCGK G.13)
FLAG_SHARE = 0.05    # model-based detectors flag the 5 % most unusual executive-years of a regime
FOLDS = 5            # cross-fitting: folds of firms
TREES = 200          # isolation forest
TAIL = 0.025         # evidence names a share as extreme beyond its 2.5 % or 97.5 % percentile
SEED = 0

# Planted anomalies: what is changed in a real executive-year, and how much. Size 1 (0 for the
# structure) leaves the row as it is, so the first point of each curve is the false-alarm rate.
PLANTS = {"level": (1, 1.25, 1.5, 2, 3), "jump": (1, 1.25, 1.5, 2, 3),
          "structure": (0, 0.25, 0.5, 0.75, 1)}
MAIN_SIZE = {"level": 2, "jump": 2, "structure": 1}  # size at which the AUC is reported


@dataclass(frozen=True)
class Kind:
    id: str
    name: str
    short: str
    idea: str
    size_label: str
    unit: str  # 'multiple' (pay × size) or 'share' (share of the bonus)


KINDS = [
    Kind("level", "Paid more, every year", "Paid more",
         "Pay multiplied by the size in every year of the executive at the firm: always above "
         "the peers, but no jump against the own past.", "Pay multiplied by", "multiple"),
    Kind("jump", "Pay jumps in one year", "Jump",
         "Pay multiplied by the size in one year only.", "Pay multiplied by", "multiple"),
    Kind("structure", "Same pay, bonus made fixed", "Bonus made fixed",
         "Total pay unchanged, but this share of the annual bonus is paid as fixed salary: "
         "pay that no longer depends on performance.", "Share of the bonus made fixed", "share"),
]


@dataclass(frozen=True)
class Detector:
    id: str
    family: str  # 'rule' (law or code), 'context' (pay against a reference), 'structure' (the
                 # pay package as a whole)
    level: str   # 'executive' or 'firm' (a firm-year: the whole board)
    name: str
    rule: str    # what is flagged, from which threshold
    origin: str  # legal basis or literature


TOP = f"flagged among the {FLAG_SHARE:.0%} highest scores of its disclosure regime, each firm scored by a model fitted without it"
STRUCTURE = ("on four numbers per executive-year, each measured against the same year and role: pay "
             "against the median of the year, role and index, and the shares of fixed salary, "
             "annual bonus and long-term pay")

DETECTORS = [
    Detector("jump", "rule", "executive", "Pay up by more than half",
             f"Total pay more than {1 + JUMP:g}× the executive's previous year at the same firm, in "
             "the same role and disclosure regime (both full years).",
             "DCGK G.3 warns against an upward ratchet; a few large raises a year spread to other "
             "firms through peer groups (DiPrete, Eirich & Pittinsky 2010)."),
    Detector("tsr", "rule", "executive", "Pay up while shareholders lost",
             f"Total pay up by more than {PAY_UP:.0%} on the previous year while the firm's total "
             "shareholder return in that year was negative (TSR comes with the §162 data).",
             "§87(1) AktG ties pay to performance and the company's situation; ISS tests pay "
             "against shareholder return (pay-for-performance alignment)."),
    Detector("one_time", "rule", "executive", "One-time payment above two years' pay",
             f"A one-time payment (severance or sign-on) above {SEVERANCE_CAP:g}× annual pay: the "
             "previous full year's total pay at the firm or, for a newcomer, this year's total "
             "pay scaled to a full year.",
             "DCGK G.13: payments on early termination should not exceed two years' "
             "remuneration (severance cap)."),
    Detector("opt_out", "rule", "firm", "No individual disclosure",
             "The firm published only the board's total pay (opt-out under §286(5) HGB).",
             "§286(5) HGB (old version), allowed with a three-quarter shareholder vote until "
             "ARUG II abolished it."),
    Detector("peers", "context", "executive", "Above the peers",
             "Pay above the peers' 90th percentile under the median peer definition (score: the "
             "median over the six definitions of log pay minus log 90th percentile).",
             "The peer benchmark (docs/peers.md); horizontal comparison of §87(1) AktG and DCGK "
             "G.3; ISS's 'multiple of median'."),
    Detector("forecast", "context", "executive", "Above the forecast range",
             "Pay above the 80 % range of the forecast made a year earlier by the best model for "
             "total pay (score: log pay minus log upper end of the range).",
             "The pay prediction (docs/prediction.md); online conformal ranges (Gibbs & Candès "
             "2021)."),
    Detector("expected", "context", "executive", "Above expected pay",
             "Log pay minus expected log pay given role, index, board size, years on the board, "
             f"age and employees (a linear regression, relative to the year's median); {TOP}.",
             "'Excess compensation' as in Core, Holthausen & Larcker (1999)."),
    Detector("robust", "structure", "executive", "Robust distance (MCD)",
             f"Mahalanobis distance from the centre of a robust covariance estimate, {STRUCTURE}; "
             f"{TOP}.",
             "Minimum covariance determinant (Rousseeuw & Van Driessen 1999): the classical "
             "multivariate outlier test, made robust to the outliers it looks for."),
    Detector("iforest", "structure", "executive", "Isolation forest",
             f"How few random splits isolate the executive-year, {STRUCTURE}; {TOP}.",
             "Liu, Ting & Zhou (2008); best on 'global' anomalies in the largest benchmark of "
             "such methods (Bouman, Bukhsh & Heskes 2024)."),
]
DETECTOR_IDS = [d.id for d in DETECTORS]
EXEC_IDS = [d.id for d in DETECTORS if d.level == "executive"]
STAT_IDS = [d.id for d in DETECTORS if d.family != "rule"]
STRUCTURE_IDS = [d.id for d in DETECTORS if d.family == "structure"]
NAME = {d.id: d.name for d in DETECTORS}

FEATURES = ["level", "fixed", "sti", "long_term"]
FEATURE_LABEL = {"fixed": "fixed salary", "sti": "annual bonus",
                 "long_term": "long-term pay (multi-year bonus and share-based)"}
ROLES = {"CEO": "CEOs", "CFO": "CFOs", "Member": "other board members"}
KEY = ["person_id", "firm_id", "year"]  # one executive-year


@dataclass
class Flags:
    rows: pd.DataFrame        # every executive-year: who, where, when, total pay
    checks: pd.DataFrame      # row, year, detector, score, flagged, evidence: where it applies
    firm_flags: pd.DataFrame  # firm_id, firm, year, detector, evidence: firm-year flags
    by_year: pd.DataFrame     # detector, year, checked, flagged: every rule and detector
    agreement: pd.DataFrame   # detector pairs: Jaccard overlap of their flags
    planted: pd.DataFrame     # detector, kind, size, detected: share of planted rows flagged
    auc: pd.DataFrame         # detector, kind, auc at MAIN_SIZE
    n_common: int             # executive-years every statistical detector checks


# --------------------------------------------------------------------------- inputs


def executive_years(p: Panel) -> pd.DataFrame:
    names = p.firms[["firm_id", "name"]].rename(columns={"name": "firm"})
    cols = ["person_id", "name", "firm_id", "firm", "year", "role", "regime", "days",
            "full_year", "total", "one_time"]
    return p.execs.merge(names, on="firm_id")[cols].reset_index(drop=True)


def observations(p: Panel, b: Benchmarks, f) -> pd.DataFrame:
    """Benchmarkable executive-years (full year, pay ≥ MIN_PAY) with the prediction's features,
    the previous year's pay of the same person, firm, role and regime, and the panel row."""
    o = forecast.observations(p, b, f.peer_method)
    prev = o[["person_id", "firm_id", "role", "regime", "year", "total"]].assign(year=o["year"] + 1)
    o = o.merge(prev, on=["person_id", "firm_id", "role", "regime", "year"], how="left",
                suffixes=("", "_prev"))
    rows = executive_years(p)[KEY].reset_index(names="row")
    return o.merge(rows, on=KEY, validate="one_to_one")


def median_without_firm(values: pd.Series, keys: list[pd.Series], firm: pd.Series) -> pd.Series:
    """Median of `values` in the row's group (`keys`) over the other firms: a firm's own pay never
    sets its own norm. NaN where no other firm is in the group."""
    out = pd.Series(np.nan, index=values.index)
    d = pd.concat([values.rename("v"), firm.rename("firm"), *keys], axis=1).dropna(subset=["v"])
    for _, g in d.groupby([k.name for k in keys], dropna=False):
        for f, own in g.groupby("firm"):
            others = g.loc[g["firm"] != f, "v"]
            if len(others):
                out[own.index] = others.median()
    return out


def folds(o: pd.DataFrame, mask: pd.Series) -> Iterator[tuple[np.ndarray, np.ndarray]]:
    """(train, test) positions per disclosure regime and fold of firms: the model that scores a
    firm never saw it, and each regime is judged by its own norms."""
    for _, d in o[mask].groupby("regime"):
        idx = d.index.to_numpy()
        for train, test in GroupKFold(FOLDS).split(idx, groups=d["firm_id"]):
            yield idx[train], idx[test]


def top_share(scores: pd.Series, regime: pd.Series) -> pd.Series:
    """Score above which an executive-year is among the FLAG_SHARE highest of its regime."""
    return scores.groupby(regime).transform(lambda s: s.quantile(1 - FLAG_SHARE))


def checks_of(o: pd.DataFrame, detector: str, score: pd.Series, flagged: pd.Series,
              evidence: Callable[[pd.DataFrame], list[str]]) -> pd.DataFrame:
    """One check per executive-year where `score` is known; evidence only where flagged."""
    d = o.assign(score=score, flagged=flagged)[score.notna()]
    d["flagged"] = d["flagged"].fillna(False).astype(bool)
    hit = d[d["flagged"]]
    d["evidence"] = pd.Series(evidence(hit) if len(hit) else [], index=hit.index, dtype=object)
    return d[["row", "score", "flagged", "evidence"]].assign(detector=detector)


def pct(v: float) -> str:
    return f"{v:+.0%}"


# --------------------------------------------------------------------------- rules


def rule_checks(o: pd.DataFrame, e: pd.DataFrame, fy: pd.DataFrame) -> list[pd.DataFrame]:
    change = o["total"] / o["total_prev"] - 1
    jump = checks_of(o, "jump", change, change > JUMP, lambda d: [
        f"Total pay {keur(t)}, {pct(t / pv - 1)} on {y - 1} ({keur(pv)}) in the same role."
        for t, pv, y in zip(d["total"], d["total_prev"], d["year"])])

    tsr = o[["firm_id", "year"]].merge(fy[["firm_id", "year", "tsr"]], how="left")["tsr"]
    tsr.index = o.index
    up = change.where(tsr.notna())
    with_tsr = o.assign(tsr=tsr)
    falls = checks_of(with_tsr, "tsr", up, (up > PAY_UP) & (tsr < 0), lambda d: [
        f"Total pay {pct(t / pv - 1)} on {y - 1} ({keur(pv)} → {keur(t)}) while the total "
        f"shareholder return of {y} was {pct(r)}."
        for t, pv, y, r in zip(d["total"], d["total_prev"], d["year"], d["tsr"])])
    return [jump, falls, one_time_checks(e)]


def one_time_checks(e: pd.DataFrame) -> pd.DataFrame:
    """One-time payments against annual pay: the previous full year's total at the firm (any
    role), else this year's total scaled to a full year."""
    full = e[e["full_year"]][["person_id", "firm_id", "year", "total"]]
    prev = e[KEY].merge(full.assign(year=full["year"] + 1), on=KEY, how="left")["total"]
    scaled = e["total"] * 365 / e["days"].where(e["days"] > 0)
    d = e.assign(row=e.index, ref=prev.fillna(scaled).to_numpy(), basis=np.where(
        prev.notna(), "total pay of " + (e["year"] - 1).astype(str), "this year's pay scaled to a full year"))
    d = d[(d["one_time"] > 0) & (d["ref"] > 0)]
    ratio = d["one_time"] / d["ref"]
    return checks_of(d, "one_time", ratio, ratio > SEVERANCE_CAP, lambda h: [
        f"One-time payment {keur(x)}: {x / r:.1f}× annual pay ({keur(r)}, {basis}). DCGK G.13 "
        f"caps severance at {SEVERANCE_CAP:g} years' pay."
        for x, r, basis in zip(h["one_time"], h["ref"], h["basis"])])


def firm_rules(fy: pd.DataFrame, firms: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Firm-year flags (opt-out from individual disclosure) and the number of firm-years the
    rule checks per year: the opt-out existed in the legacy years only."""
    opt = fy[fy["opt_out"]]
    flags = opt[["firm_id", "year"]].assign(detector="opt_out", evidence=[
        f"Only the board's total pay was published: {keur(t)} for {n:.0f} members."
        for t, n in zip(opt["board_total"], opt["n_execs"])])
    checked = (fy[fy["regime"] == "legacy"].groupby("year").size().rename("checked").reset_index()
               .assign(detector="opt_out"))
    names = firms[["firm_id", "name"]].rename(columns={"name": "firm"})
    return flags.merge(names, on="firm_id"), checked


# --------------------------------------------------------------------------- context


def peer_scores(o: pd.DataFrame, b: Benchmarks) -> pd.DataFrame:
    """Median over the peer definitions of log(pay ÷ peers' 90th percentile)."""
    res = b.results[b.results["method"].isin(METHOD_IDS)].join(b.rows[KEY + ["total"]])
    res["gap"] = np.log(res["total"] / res["p90"])
    g = res.groupby(level="row")
    per = pd.DataFrame({"score": g["gap"].median(), "above": g["gap"].agg(lambda x: (x > 0).sum()),
                        "n": g.size(), "lo": g["ratio"].min(), "hi": g["ratio"].max()})
    per = per.join(b.rows[KEY]).merge(o[KEY].reset_index(names="pos"), on=KEY).set_index("pos")
    return per.reindex(o.index)


def forecast_scores(o: pd.DataFrame, f) -> pd.DataFrame:
    """Last year's one-year forecast of total pay: log pay minus the upper end of the best
    model's 80 % range, and how many models' ranges the pay is above."""
    bt = f.backtest[(f.backtest["target"] == "total") & (f.backtest["h"] == 1)
                    & (f.backtest["model"] != "linear_demo")]  # demographics never judge anyone
    bt = bt.astype({"person_id": str, "firm": str, "role": str, "model": str, "year": int}).assign(
        year=lambda d: d["year"] + 1, above=lambda d: d["y"] > d["hi"])
    counts = bt.dropna(subset=["hi"]).groupby(["person_id", "firm", "role", "year"])["above"].agg(
        ["sum", "size"]).rename(columns={"sum": "above", "size": "n"})
    best = bt[bt["model"] == f.best["total"]].set_index(["person_id", "firm", "role", "year"])
    best = best[["y", "pred", "lo", "hi"]].join(counts)
    key = pd.MultiIndex.from_frame(o[["person_id", "firm", "role", "year"]])
    out = best.reindex(key).set_index(o.index)
    return out.assign(score=out["y"] - out["hi"])


def expected_scores(o: pd.DataFrame, gm: pd.Series) -> pd.Series:
    """Expected log pay: the other firms' median of the year, role and index plus a linear model
    of the prediction's level features, cross-fitted by firm."""
    x, target = forecast.WHAT_IF_X, o["total_log"] - gm
    expected = pd.Series(np.nan, index=o.index)
    for train, test in folds(o, gm.notna()):
        m = LinearRegression().fit(o.loc[train, x], target[train])
        expected[test] = gm[test] + m.predict(o.loc[test, x])
    return expected


# --------------------------------------------------------------------------- structure


def structure_inputs(o: pd.DataFrame, gm: pd.Series) -> tuple[pd.DataFrame, pd.DataFrame, pd.Series]:
    """The four numbers, raw and the other firms' median of the same year and role (level is
    already a distance to the other firms' median of the year, role and index). Rows need fixed
    salary, annual bonus and share-based pay reported: a blank legacy component means 'not
    reported', not zero."""
    raw = pd.DataFrame({"level": o["total_log"] - gm, "fixed": o["fixed"] / o["total"],
                        "sti": o["sti"] / o["total"],
                        "long_term": (o["mti"].fillna(0) + o["lti"]) / o["total"]})
    ok = o[["fixed", "sti", "lti"]].notna().all(axis=1) & gm.notna()
    keys = [o["year"], o["role"]]
    med = pd.DataFrame({c: median_without_firm(raw[c].where(ok), keys, o["firm_id"])
                        for c in ["fixed", "sti", "long_term"]}).assign(level=0.0)
    return raw, med, ok & med.notna().all(axis=1)


def planted_raw(raw: pd.DataFrame, kind: str, size: float) -> pd.DataFrame:
    """The four numbers after planting an anomaly (see KINDS); shares are of total pay."""
    if kind == "structure":
        return raw.assign(fixed=raw["fixed"] + size * raw["sti"], sti=(1 - size) * raw["sti"])
    return raw.assign(level=raw["level"] + np.log(size))


def fit_structure(train: np.ndarray) -> dict[str, Callable[[np.ndarray], np.ndarray]]:
    """The structure detectors fitted on `train`; each returns a score, higher = more unusual."""
    mcd = MinCovDet(random_state=SEED).fit(train)
    forest = IsolationForest(n_estimators=TREES, random_state=SEED).fit(train)
    return {"robust": mcd.mahalanobis, "iforest": lambda x: -forest.score_samples(x)}


def structure_scores(o: pd.DataFrame, raw: pd.DataFrame, med: pd.DataFrame, ok: pd.Series
                     ) -> tuple[pd.DataFrame, dict[tuple[str, float], pd.DataFrame]]:
    """Out-of-firm scores of every structure detector, for the real rows and for every planted
    variant of them (scored by the same models, which never saw the row's firm)."""
    x = (raw - med)[FEATURES]
    variants = {(k, s): (planted_raw(raw, k, s) - med)[FEATURES] for k, sizes in PLANTS.items()
                for s in sizes}
    real = pd.DataFrame(np.nan, index=o.index, columns=STRUCTURE_IDS)
    planted = {v: real.copy() for v in variants}
    for train, test in folds(o, ok):
        for name, score in fit_structure(x.loc[train].to_numpy()).items():
            real.loc[test, name] = score(x.loc[test].to_numpy())
            for v, xv in variants.items():
                planted[v].loc[test, name] = score(xv.loc[test].to_numpy())
    return real, planted


def structure_evidence(o: pd.DataFrame, raw: pd.DataFrame, med: pd.DataFrame, ok: pd.Series
                       ) -> Callable[[pd.Index], list[str]]:
    """Why a package is unusual: the numbers beyond their 2.5 % / 97.5 % percentile in the
    regime (at most two, most extreme first), with the 10–90 % range of the year and role."""
    x = (raw - med)[ok]
    rank = x.groupby(o["regime"]).rank(pct=True)
    tail = np.minimum(rank, 1 - rank)
    g = raw[ok].groupby([o["year"], o["role"]])
    lo, hi = g.transform("quantile", 0.1), g.transform("quantile", 0.9)

    def text(i) -> str:
        who = f"{ROLES[o.at[i, 'role']]} {o.at[i, 'year']}"
        parts = []
        for c in tail.loc[i].sort_values().index[:2]:
            if tail.at[i, c] > TAIL:
                break
            if c == "level":
                index = o.at[i, "index"]
                where = f"in the {index}" if isinstance(index, str) else "without an index listing"
                parts.append(f"pay {np.exp(raw.at[i, c]):.1f}× the other firms' median for {who} "
                             f"{where}")
            else:
                parts.append(f"{FEATURE_LABEL[c]} {raw.at[i, c]:.0%} of pay ({who}: 10–90 % "
                             f"range {lo.at[i, c]:.0%}–{hi.at[i, c]:.0%})")
        return ("Unusual pay package: " + "; ".join(parts) + "." if parts else
                "Unusual pay package: no single number is extreme, the combination is rare.")

    return lambda idx: [text(i) for i in idx]


# --------------------------------------------------------------------------- statistical checks


def stat_checks(o: pd.DataFrame, b: Benchmarks, f) -> tuple[list[pd.DataFrame], dict]:
    """The statistical detectors' checks, plus what the planted-anomaly test needs: per detector
    the real score, the threshold, and a function giving the score of planted variants."""
    peers = peer_scores(o, b)
    fc = forecast_scores(o, f)
    gm = median_without_firm(o["total_log"], [o["year"], o["role"], o["index"].fillna("none")],
                             o["firm_id"])
    expected = expected_scores(o, gm)
    residual = o["total_log"] - expected
    raw, med, ok = structure_inputs(o, gm)
    real, planted = structure_scores(o, raw, med, ok)
    why = structure_evidence(o, raw, med, ok)
    best = next(m for m in forecast.MODELS if m.id == f.best["total"])
    model = best.name

    out = [
        checks_of(o.join(peers[["above", "n", "lo", "hi"]]), "peers", peers["score"],
                  peers["score"] > 0, lambda d: [
                      f"Above the peers' 90th percentile under {a:.0f} of {n:.0f} definitions; "
                      f"{lo:.1f}–{hi:.1f}× the peer median."
                      for a, n, lo, hi in zip(d["above"], d["n"], d["lo"], d["hi"])]),
        checks_of(o.join(fc[["pred", "lo", "hi", "above", "n"]]), "forecast", fc["score"],
                  fc["score"] > 0, lambda d: [
                      f"Forecast from {y - 1} ({model}): {keur(np.exp(p))}, 80 % range "
                      f"{keur(np.exp(lo))}–{keur(np.exp(hi))}; paid {keur(t)}. Above the range of "
                      f"{a:.0f} of {n:.0f} models."
                      for y, p, lo, hi, t, a, n in zip(d["year"], d["pred"], d["lo"], d["hi"],
                                                       d["total"], d["above"], d["n"])]),
    ]
    thresholds = {"expected": top_share(residual.dropna(), o["regime"]).reindex(o.index)}
    out.append(checks_of(o.assign(expected=expected), "expected", residual,
                         residual > thresholds["expected"], lambda d: [
                             f"Expected for this role, index, board size, tenure, age"
                             f"{' and workforce' if w else ' and year'}: {keur(np.exp(x))}; paid {keur(t)} "
                             f"({t / np.exp(x):.1f}×)."
                             for x, t, w in zip(d["expected"], d["total"], d["has_emp"])]))
    for name in STRUCTURE_IDS:
        score = real[name]
        thresholds[name] = top_share(score.dropna(), o["regime"]).reindex(o.index)
        out.append(checks_of(o, name, score, score > thresholds[name], lambda d: why(d.index)))

    # Planted variants: a reference score moves by log(size) where the anomaly is visible to it.
    # A forecast from the executive's own past ('own' family: the prediction and its range scale
    # with last year's pay) cannot see pay that is k times higher in every year; that is exact
    # for these models and approximate for a change model, which also starts from last year.
    blind_to_level = best.family in ("own", "change")

    def variant(name: str, kind: str, size: float) -> pd.Series:
        if name in STRUCTURE_IDS:
            return planted[(kind, size)][name]
        base = {"peers": peers["score"], "forecast": fc["score"], "expected": residual}[name]
        sees = kind == "jump" or (kind == "level" and not (name == "forecast" and blind_to_level))
        return base + np.log(size) if sees else base

    return out, {"thresholds": thresholds, "variant": variant}


# --------------------------------------------------------------------------- evaluation


def agreement(checks: pd.DataFrame) -> pd.DataFrame:
    """Per pair of executive-level checks: Jaccard overlap of their flags on the executive-years
    both check (1 = the same flags, 0 = none in common)."""
    flagged = checks.pivot(index="row", columns="detector", values="flagged")
    out = []
    for a in EXEC_IDS:
        for b in EXEC_IDS:
            both = flagged[a].notna() & flagged[b].notna()
            x, y = flagged.loc[both, a].astype(bool), flagged.loc[both, b].astype(bool)
            either, together = int((x | y).sum()), int((x & y).sum())
            out.append({"a": a, "b": b, "n": int(both.sum()), "both": together, "either": either,
                        "jaccard": together / either if either else None})
    return pd.DataFrame(out)


def planted_test(o: pd.DataFrame, checks: pd.DataFrame, plant: dict) -> tuple[pd.DataFrame, pd.DataFrame, int]:
    """Plant each anomaly in every executive-year that all statistical detectors check, and count
    how many each detector flags; the AUC is the chance that the planted version scores above a
    real executive-year of the same regime (ties count half)."""
    real = checks[checks["detector"].isin(STAT_IDS)].pivot(index="row", columns="detector",
                                                            values="score")
    common = o.index[o["row"].isin(real.dropna().index)]
    stretch = o.loc[common, "sti"] > 0  # the structure anomaly needs a bonus to move
    rows, auc = [], []
    for name in STAT_IDS:
        line = plant["thresholds"].get(name, 0.0)  # peers and forecast: above 0 (the range's end)
        for kind, sizes in PLANTS.items():
            where = common[stretch] if kind == "structure" else common
            for size in sizes:
                s = plant["variant"](name, kind, size)[where]
                above = s > (line[where] if isinstance(line, pd.Series) else line)
                rows.append({"detector": name, "kind": kind, "size": float(size),
                             "detected": float(above.mean())})
            s = plant["variant"](name, kind, MAIN_SIZE[kind])[where]
            real_scores = plant["variant"](name, kind, PLANTS[kind][0])[where]
            regime = o.loc[where, "regime"]
            auc.append({"detector": name, "kind": kind, "auc": rank_auc(s, real_scores, regime, regime)})
    return pd.DataFrame(rows), pd.DataFrame(auc), len(common)


def rank_auc(pos: pd.Series, neg: pd.Series, pos_regime: pd.Series, neg_regime: pd.Series) -> float:
    """Mean over `pos` of the share of `neg` of the same regime scoring lower (ties half)."""
    shares = []
    for regime, p in pos.groupby(pos_regime):
        n = np.sort(neg[neg_regime == regime].to_numpy())
        lower = np.searchsorted(n, p.to_numpy(), "left")
        ties = np.searchsorted(n, p.to_numpy(), "right") - lower
        shares.append((lower + 0.5 * ties) / len(n))
    return float(np.concatenate(shares).mean())


# --------------------------------------------------------------------------- entry point


def compute(p: Panel, b: Benchmarks, f) -> Flags:
    e = executive_years(p)
    o = observations(p, b, f)
    fy = p.firm_years
    stats, plant = stat_checks(o, b, f)
    checks = pd.concat([*rule_checks(o, e, fy), *stats], ignore_index=True)
    checks = checks.astype({"row": int, "flagged": bool})
    checks = checks.join(e[["year"]], on="row")
    planted, auc, n_common = planted_test(o, checks, plant)
    firm_flags, firm_checked = firm_rules(fy, p.firms)
    by_year = pd.concat([
        checks.groupby(["detector", "year"])["flagged"].agg(checked="size", flagged="sum").reset_index(),
        firm_checked.merge(firm_flags.groupby(["detector", "year"]).size().rename("flagged").reset_index(),
                           how="left").fillna({"flagged": 0})], ignore_index=True)
    return Flags(rows=e, checks=checks, firm_flags=firm_flags, by_year=by_year.astype(
                     {"checked": int, "flagged": int}), agreement=agreement(checks),
                 planted=planted, auc=auc, n_common=n_common)


_lock = Lock()


@lru_cache(maxsize=1)
def _flags() -> Flags:
    return cached(CACHE.with_name("flags.pkl"),
                  lambda: compute(get_panel(), get_benchmarks(), forecast.get_forecasts()))


def get_flags() -> Flags:
    """Computed once (seconds, after the forecasts) and cached next to the panel until data or
    code change. The lock keeps a request from starting a second computation."""
    with _lock:
        return _flags()


if __name__ == "__main__":
    import time

    from app import redflags  # the importable module, so the cache pickles app.redflags classes

    start = time.time()
    fl = redflags.get_flags()
    pd.set_option("display.width", 200)
    c = fl.checks
    print(c.groupby("detector").agg(checked=("flagged", "size"), flagged=("flagged", "sum"))
          .assign(share=lambda d: d["flagged"] / d["checked"]).reindex(EXEC_IDS).round(3).to_string())
    print(fl.firm_flags.groupby("detector").size().to_string())
    print(f"planted test on {fl.n_common} executive-years")
    print(fl.planted.pivot_table(index="detector", columns=["kind", "size"], values="detected")
          .reindex(STAT_IDS).round(2).to_string())
    print(fl.auc.pivot(index="detector", columns="kind", values="auc").reindex(STAT_IDS).round(3).to_string())
    print(f"{time.time() - start:.1f} s")
