"""Build one harmonised panel from everything in data/raw/ and data/reference/.

    sources/      one adapter per delivery format → canonical frames (contract in sources/__init__)
    reference.py  curated aliases, KPI categories, overrides and attribute tables
    this module   firm and person identity, joins, overrides, derived columns, validation

Adding a year, a firm or a firm-level dataset is a file drop (docs/data.md, "Adding data");
only a new file format needs code: a new adapter listed in SOURCES.

    uv run python -m app.panel              build and report what was loaded
    uv run python -m app.panel --add-kpis   also list new KPI names in kpi_categories.csv
"""

from __future__ import annotations

import hashlib
import pickle
import re
import unicodedata
from collections.abc import Callable
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import TypeVar

import numpy as np
import pandas as pd

from . import reference
from .sources import EXEC_COLUMNS, FIRM_YEAR_COLUMNS, Batch, dsw, issue, legacy, manual

ROOT = Path(__file__).resolve().parents[2]
RAW = ROOT / "data" / "raw"
CACHE = ROOT / "data" / "cache" / "panel.pkl"
T = TypeVar("T")

SOURCES = [legacy.load_all, dsw.load_all, manual.load_all]  # add new adapters here

COMPONENTS = ["fixed", "sti", "mti", "lti", "other"]  # total = their sum; k€

# Columns the API relies on; created empty when no source provides them.
EXEC_OPTIONAL = ["person_ref", "female", "german", "birth_year", "internal", "sti_cap",
                 "sti_cap_pct", "lti_cap", "sti_kpis", "lt_kpis", "max_comp"]
FIRM_YEAR_OPTIONAL = ["isin", "opt_out", "n_execs", "board_total", "board_total_incl",
                      "staff_cost", "employees", "tsr", "industry", "sti_esg_share",
                      "lti_esg_share", "sti_esg_kind", "lti_esg_kind"]
NUMERIC = ["staff_cost", "employees", "tsr", "sti_esg_share", "lti_esg_share", "n_execs",
           "board_total", "board_total_incl"]

FirmId = Callable[[str], str]


@dataclass
class Panel:
    firms: pd.DataFrame        # one row per firm
    firm_years: pd.DataFrame   # one row per firm × year (incl. opt-out firms)
    execs: pd.DataFrame        # one row per executive × firm × year
    issues: list[dict]
    sources: list[dict]        # what was loaded, for the data-quality view
    kpi_category: dict[str, list[str]]  # KPI name → categories (composites have several)
    kpi_unlisted: list[str]    # KPI names not yet in kpi_categories.csv
    extra_firm_columns: list[str] = field(default_factory=list)  # from attribute tables
    extra_year_columns: list[str] = field(default_factory=list)


def norm(text: object) -> str:
    """Accent- and punctuation-free lowercase key for fuzzy name joins."""
    ascii_ = unicodedata.normalize("NFKD", str(text)).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z]", "", ascii_.lower())


def slug(text: object) -> str:
    ascii_ = unicodedata.normalize("NFKD", str(text)).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", "-", ascii_.lower()).strip("-")


def build() -> Panel:
    alias = reference.aliases()

    def firm_id(name: str) -> str:
        return slug(alias.get(name, name))

    batches = [b for load in SOURCES for b in load(RAW)]
    if not batches:
        raise ValueError(f"No source files found under {RAW}")
    issues = [i for b in batches for i in b.issues]
    execs, fy = stack(batches)
    execs["firm_id"] = execs["firm"].map(firm_id)
    fy["firm_id"] = fy["firm"].map(firm_id)
    validate_keys(execs, fy)

    execs["name"] = execs["first_name"].str.strip() + " " + execs["last_name"].str.strip()
    directory = [b.people.assign(firm_id=b.people["firm"].map(firm_id))
                 for b in batches if b.people is not None]
    execs["person_id"], linked = assign_people(execs, directory)
    if execs.duplicated(["firm_id", "year", "person_id"]).any():
        raise ValueError("An executive appears twice in the same firm-year")

    seen = set(execs["firm"]) | set(fy["firm"])
    for b in batches:
        for facts in b.facts:
            issues += attach(fy, facts, b.label, firm_id)
            seen |= set(facts["firm"])

    firms = firm_table(fy, alias)
    codes = reference.industries()
    issues += attach(firms, codes[["firm", "naics"]], "industries.csv", firm_id)
    firms["naics_title"] = firms["naics"].map(reference.naics_titles())
    issues.append(industry_issue(firms, codes))
    extra_firm, extra_year = [], []
    for label, table in reference.tables(RAW / "tables", reference.REFERENCE / "tables"):
        target, extra = (fy, extra_year) if "year" in table else (firms, extra_firm)
        before = set(target.columns)
        issues += attach(target, table, label, firm_id)
        extra += sorted(set(target.columns) - before)
        seen |= set(table["firm"])

    issues += apply_overrides(reference.overrides(), execs, fy, firm_id)
    derive(execs, fy)
    firms = firms.merge(fy.groupby("firm_id")["year"].agg(first_year="min", last_year="max"),
                        on="firm_id")
    industry = fy.dropna(subset=["industry"]).sort_values("year").groupby("firm_id")["industry"]
    firms = firms.merge(industry.last(), on="firm_id", how="left")

    names = {k for ks in execs["sti_kpis"].dropna().tolist() + execs["lt_kpis"].dropna().tolist()
             for k in ks}
    categories, unlisted, unreviewed = reference.kpi_categories(names)

    issues += panel_issues(alias, seen, linked, unlisted, unreviewed, len(names))
    for df in (execs, fy):  # keep the spelling each source used; `firm_id` is the key
        df.rename(columns={"firm": "source_name"}, inplace=True)
    sources = [{"label": b.label, "regime": b.regime, "execs": len(b.execs),
                "firm_years": len(b.firm_years)} for b in batches]
    return Panel(firms, fy, execs, issues, sources, categories, unlisted, extra_firm, extra_year)


def stack(batches: list[Batch]) -> tuple[pd.DataFrame, pd.DataFrame]:
    for b in batches:
        for df, cols, what in ((b.execs, EXEC_COLUMNS, "execs"),
                               (b.firm_years, FIRM_YEAR_COLUMNS, "firm_years")):
            missing = set(cols) - set(df.columns)
            if missing:
                raise ValueError(f"{b.label}: {what} lacks columns {sorted(missing)}")
    execs = pd.concat([b.execs.assign(regime=b.regime, batch=b.label) for b in batches],
                      ignore_index=True)
    fy = pd.concat([b.firm_years.assign(regime=b.regime) for b in batches], ignore_index=True)
    for col in EXEC_OPTIONAL:
        if col not in execs:
            execs[col] = np.nan
    for col in FIRM_YEAR_OPTIONAL:
        if col not in fy:
            fy[col] = np.nan
    return execs, fy


def validate_keys(execs: pd.DataFrame, fy: pd.DataFrame) -> None:
    dup = fy[fy.duplicated(["firm_id", "year"], keep=False)]
    if not dup.empty:
        raise ValueError("Firm-year delivered twice (two sources, or an alias collision): "
                         f"{sorted(set(zip(dup['firm'], dup['year'])))[:5]}")
    keys = set(zip(fy["firm_id"], fy["year"]))
    orphans = {(f, y) for f, fid, y in zip(execs["firm"], execs["firm_id"], execs["year"])
               if (fid, y) not in keys}
    if orphans:
        raise ValueError(f"Executives without a firm-year row: {sorted(orphans)[:5]}")
    isins = fy.dropna(subset=["isin"]).groupby("firm_id")["isin"].nunique()
    if (isins > 1).any():
        raise ValueError(f"One firm id, several ISINs (alias collision?): "
                         f"{list(isins[isins > 1].index)}")


def assign_people(execs: pd.DataFrame, directory: list[pd.DataFrame]
                  ) -> tuple[list[str], dict[str, list[int]]]:
    """Stable person IDs. Sources with their own IDs keep them; others are matched — against
    the sources' people directories and earlier records — at the same firm by surname
    (+ first initial if ambiguous). A person moving firms keeps one ID only via a directory."""
    known: dict[tuple[str, str], set[tuple[str, str]]] = {}
    for people in directory:
        for fid, first, last, ref in people[["firm_id", "first_name", "last_name",
                                             "person_ref"]].itertuples(index=False):
            known.setdefault((fid, norm(last)), set()).add((ref, norm(first)[:1]))
    ids, linked = [], {}
    cols = ["batch", "firm_id", "first_name", "last_name", "person_ref"]
    for batch, fid, first, last, ref in execs[cols].itertuples(index=False):
        first, last = norm(first), norm(last)
        if isinstance(ref, str):
            pid = ref
        else:
            cands = known.get((fid, last), set())
            if len({c[0] for c in cands}) > 1:
                cands = {c for c in cands if c[1] == first[:1]}
            pids = {c[0] for c in cands}
            counts = linked.setdefault(batch, [0, 0])
            counts[1] += 1
            if len(pids) == 1:
                pid = pids.pop()
                counts[0] += 1
            else:
                pid = f"{fid}-{first}-{last}"
        known.setdefault((fid, last), set()).add((pid, first[:1]))
        ids.append(pid)
    return ids, linked


def firm_table(fy: pd.DataFrame, alias: dict[str, str]) -> pd.DataFrame:
    """One row per firm, named after its latest spelling in the sources (after aliases)."""
    latest = fy.sort_values("year").groupby("firm_id")
    return pd.DataFrame({
        "name": latest["firm"].last().map(lambda n: alias.get(n, n)),
        "isin": latest["isin"].last(),
    }).reset_index()


def attach(target: pd.DataFrame, facts: pd.DataFrame, label: str, firm_id: FirmId) -> list[dict]:
    """Fill empty cells of `target` (firm_years if `facts` has a year column, else firms).

    Existing values are never overwritten — corrections belong in overrides.csv. Rows naming a
    firm or firm-year that is not in the panel are reported, not silently dropped.
    """
    keys = ["firm_id", "year"] if "year" in facts else ["firm_id"]
    df = facts.assign(firm_id=facts["firm"].map(firm_id))
    found = df.merge(target[keys].drop_duplicates(), on=keys, how="left",
                     indicator=True)["_merge"].eq("both").to_numpy()
    issues = []
    if not found.all():
        names = sorted(set(df.loc[~found, "firm"].astype(str)))
        issues.append(issue(
            f"unmatched-{label}", "decide", f"{label}: rows for firms not in the panel",
            "Either firms outside the compensation data (fine) or another spelling of a known "
            "firm (add it to data/reference/firm_aliases.csv): " + ", ".join(names[:12])
            + (" …" if len(names) > 12 else ""), int((~found).sum())))
    values = df[found].drop(columns="firm").drop_duplicates(keys).set_index(keys)
    index = pd.MultiIndex.from_frame(target[keys]) if len(keys) > 1 else pd.Index(target[keys[0]])
    for col in values.columns:
        new = pd.Series(values[col].reindex(index).to_numpy(), index=target.index)
        target[col] = target[col].combine_first(new) if col in target else new
    return issues


def industry_issue(firms: pd.DataFrame, codes: pd.DataFrame) -> dict:
    """Coverage and review status of the NAICS codes in industries.csv."""
    missing = sorted(firms.loc[firms["naics"].isna(), "name"])
    unreviewed = int((codes["reviewed"] != "yes").sum())
    detail = (f"{len(firms) - len(missing)} of {len(firms)} firms have a six-digit NAICS 2022 code "
              "for their main activity; the industry peer groups use it. The codes were suggested "
              "with AI assistance from public company descriptions; set `reviewed` to `yes` once "
              f"checked. Not reviewed: {unreviewed}.")
    if missing:
        detail += " Without a code: " + ", ".join(missing)
    return issue("industries", "decide" if missing or unreviewed else "fixed",
                 "Industry codes (data/reference/industries.csv)", detail,
                 len(missing) + unreviewed)


def apply_overrides(table: pd.DataFrame, execs: pd.DataFrame, fy: pd.DataFrame,
                    firm_id: FirmId) -> list[dict]:
    """Apply data/reference/overrides.csv. Every row must match exactly one record."""
    done = []
    for line, r in enumerate(table.itertuples(index=False), start=2):
        where = f"overrides.csv line {line}"
        target = {"execs": execs, "firm_years": fy}.get(r.table)
        if target is None:
            raise ValueError(f"{where}: table must be 'execs' or 'firm_years'")
        if r.field not in target:
            raise ValueError(f"{where}: unknown field '{r.field}'")
        mask = (target["firm_id"] == firm_id(r.firm)) & (target["year"] == int(r.year))
        if r.table == "execs":
            mask &= target["name"] == r.person
        if mask.sum() != 1:
            raise ValueError(f"{where}: matches {int(mask.sum())} rows, expected 1")
        column = target[r.field]
        if pd.api.types.is_bool_dtype(column):
            value: object = r.value.lower() in ("1", "true", "yes")
        elif pd.api.types.is_numeric_dtype(column):
            target[r.field] = column.astype(float)
            value = float(r.value) if r.value else np.nan
        else:
            value = r.value or None
        old = column[mask].iloc[0]
        target.loc[mask, r.field] = value
        done.append(f"{r.firm} {r.year}{' ' + r.person if r.person else ''}, {r.field}: "
                    f"{old} → {r.value or 'empty'}" + (f" ({r.note})" if r.note else ""))
    if not done:
        return []
    return [issue("overrides", "fixed", "Manual corrections (data/reference/overrides.csv)",
                  "; ".join(done), len(done))]


def derive(execs: pd.DataFrame, fy: pd.DataFrame) -> None:
    """Totals, flags and board aggregates, computed once for every source."""
    for col in [*COMPONENTS, "pension", "one_time", "days", "max_comp", "sti_cap_pct"]:
        execs[col] = pd.to_numeric(execs[col], errors="coerce")
    # A blank component means "not reported"; the total is what was reported (= source totals).
    execs["total"] = execs[COMPONENTS].fillna(0).sum(axis=1)
    execs["total_incl"] = execs["total"] + execs[["pension", "one_time"]].fillna(0).sum(axis=1)
    execs["reported"] = execs[COMPONENTS].notna().all(axis=1)
    execs["full_year"] = execs["days"] >= 360

    for col in NUMERIC:
        fy[col] = pd.to_numeric(fy[col], errors="coerce")
    agg = execs.groupby(["firm_id", "year"]).agg(
        n_execs=("person_id", "size"), board_total=("total", "sum"),
        board_total_incl=("total_incl", "sum"))
    index = pd.MultiIndex.from_frame(fy[["firm_id", "year"]])
    for col in agg:  # a source's own board totals win (opt-out firms have no executives)
        fy[col] = fy[col].combine_first(pd.Series(agg[col].reindex(index).to_numpy(), fy.index))
    fy["opt_out"] = fy["opt_out"].astype("boolean").fillna(False).astype(bool)
    fy["avg_staff_cost"] = fy["staff_cost"] / fy["employees"]
    fy.sort_values(["firm_id", "year"], inplace=True, ignore_index=True)
    lookup = fy.set_index(["firm_id", "year"])["index"]
    execs["index"] = lookup.reindex(pd.MultiIndex.from_frame(execs[["firm_id", "year"]])).to_numpy()


def panel_issues(alias: dict[str, str], seen: set, linked: dict[str, list[int]],
                 unlisted: list[str], unreviewed: int, n_kpis: int) -> list[dict]:
    used = [f"{a} → {n}" for a, n in alias.items() if a in seen]
    links = "; ".join(f"{b}: {m} of {t}" for b, (m, t) in linked.items())
    return [
        issue("regime-break", "note", "Disclosure regime break between 2021 and 2022",
              "2006–2021 follows the DCGK model tables; from 2022 firms report §162 AktG "
              "'granted and owed' amounts. Same unit (k€), but definitions differ, especially "
              "for multi-year and share-based pay. Charts mark the break."),
        issue("universe-change", "note", "Universe shrinks from DAX + MDAX to DAX only",
              "Legacy covers ~90 firms a year (DAX + MDAX); 2022+ covers the 40 DAX firms. "
              "Unfiltered medians jump because of composition, not pay — filter to DAX to "
              "compare across the break."),
        issue("person-linking", "fixed", "Executives linked across sources by name",
              "Sources without person IDs are matched to people directories and earlier "
              "records at the same firm by surname (+ first initial). Linked to an existing "
              f"person: {links}. The rest are new to the data."),
        issue("firm-aliases", "fixed", "Firm names reconciled (data/reference/firm_aliases.csv)",
              "; ".join(used) or "none needed", len(used)),
        issue("kpi-categories", "decide" if unlisted or unreviewed else "fixed",
              "KPI names mapped to categories (data/reference/kpi_categories.csv)",
              f"{n_kpis} distinct free-text names. {len(unlisted)} not listed yet (categorised "
              "by keyword rules; add them with `uv run python -m app.panel --add-kpis`), "
              f"{unreviewed} listed but not reviewed. Weights are not used.",
              len(unlisted) + unreviewed),
        issue("esg-shares", "note", "ESG shares need careful reading",
              "2022 records ESG as multiplier ranges ('0,8-1,2') or prose, so only 2023+ are "
              "numeric. From 2023 each plan says how ESG enters it: as a target with a weight, "
              "or as a multiplier on the payout. Only target weights are ESG weights; a "
              "multiplier's number is not (100 % can mean a modifier on the whole plan)."),
        issue("no-financials", "note", "No firm financials",
              "Revenue, assets, profit and market value are not available. Employees and staff "
              "costs exist from 2022; index and board size are the size proxies for all years. "
              "Financials can be added as a firm-year table in data/raw/tables/."),
    ]


def fingerprint() -> str:
    """Changes whenever an input file or the backend code is added, removed or edited."""
    files = sorted(p for p in [*RAW.rglob("*"), *reference.REFERENCE.rglob("*"),
                               *Path(__file__).parent.rglob("*.py")] if p.is_file())
    digest = hashlib.sha1()
    for p in files:
        stat = p.stat()
        digest.update(f"{p}|{stat.st_mtime_ns}|{stat.st_size}\n".encode())
    return digest.hexdigest()


def cached(path: Path, make: Callable[[], T]) -> T:
    """`make()`, or the pickle at `path` from an earlier run while inputs and code are unchanged."""
    key = fingerprint()
    try:
        with path.open("rb") as f:
            stored = pickle.load(f)
        if isinstance(stored, tuple) and stored[0] == key:
            return stored[1]
    except (OSError, pickle.UnpicklingError, AttributeError, EOFError, ImportError):
        pass  # no cache yet, or one from an older code version: rebuild
    value = make()
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("wb") as f:
        pickle.dump((key, value), f)
    return value


@lru_cache(maxsize=1)
def get_panel() -> Panel:
    """Build once per process; reuse the pickle while the inputs are unchanged."""
    return cached(CACHE, build)


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Build the panel and report what was loaded.")
    parser.add_argument("--add-kpis", action="store_true",
                        help="append unlisted KPI names to data/reference/kpi_categories.csv")
    args = parser.parse_args()
    panel = build()
    for s in panel.sources:
        print(f"{s['label']:<24} {s['regime']:<7} {s['execs']:>6} executive-years "
              f"{s['firm_years']:>5} firm-years")
    print(f"→ {len(panel.firms)} firms, {len(panel.firm_years)} firm-years, "
          f"{len(panel.execs)} executive-years")
    for i in panel.issues:
        if i["kind"] == "decide":
            print(f"  needs a decision: {i['title']}" + (f" ({i['count']})" if i["count"] else ""))
    if args.add_kpis and panel.kpi_unlisted:
        reference.add_kpi_names(panel.kpi_unlisted)
        print(f"Added {len(panel.kpi_unlisted)} KPI names to kpi_categories.csv for review.")
