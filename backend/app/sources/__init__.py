"""Source adapters: one module per delivery format.

An adapter exposes `load_all(raw: Path) -> list[Batch]`, finds its own files under data/raw/ and
translates them into the canonical columns below. Everything else — firm and person identity,
reference tables, overrides, derived totals, validation — happens once in panel.py, so an adapter
only renames and cleans columns. To support a new format, add a module and list it in
panel.SOURCES.

Canonical columns (adapters may add more; they are kept):

    execs       firm, year, first_name, last_name, role ("CEO" | "CFO" | "Member"), days,
                fixed, sti, mti, lti, other, pension, one_time   (k€)
                optional: person_ref (stable ID from the source), female, german, birth_year, …
    firm_years  firm, year, index                                   one row per firm-year
                optional: isin, opt_out, n_execs, board_total, board_total_incl
    facts       firm, [year], any columns                           extra tables for the same
                firms, e.g. other sheets; they fill gaps and may use other spellings of names
    people      firm, first_name, last_name, person_ref             optional directory of known
                people (incl. ones without pay rows) used to link executives across sources

`firm` is the name as written in the source; panel.py maps it to a firm_id via
data/reference/firm_aliases.csv.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import pandas as pd

PAY = ["fixed", "sti", "mti", "lti", "other", "pension", "one_time"]
EXEC_COLUMNS = ["firm", "year", "first_name", "last_name", "role", "days", *PAY]
FIRM_YEAR_COLUMNS = ["firm", "year", "index"]


@dataclass
class Batch:
    label: str                 # shown in data-quality notes, e.g. "DSW 2023"
    regime: str                # disclosure regime: "legacy" or "§162"
    execs: pd.DataFrame
    firm_years: pd.DataFrame
    facts: list[pd.DataFrame] = field(default_factory=list)
    issues: list[dict] = field(default_factory=list)
    people: pd.DataFrame | None = None


def issue(id_: str, kind: str, title: str, detail: str, count: int | None = None) -> dict:
    """kind: 'fixed' (handled in code), 'decide' (needs a human), 'note' (worth knowing)."""
    return {"id": id_, "kind": kind, "title": title, "detail": detail, "count": count}


def num(s: pd.Series) -> pd.Series:
    return pd.to_numeric(s, errors="coerce")
