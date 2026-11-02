"""Rows entered with the dashboard's "Add data" form: data/raw/manual/execs.csv and
firm_years.csv, already in the canonical columns, each row with a `source` saying where its
values come from. The regime follows the year: §162 AktG reporting starts with 2022.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from . import EXEC_COLUMNS, FIRM_YEAR_COLUMNS, Batch, issue, num

FIRST_162 = 2022
NUMBERS = ["year", "days", "fixed", "sti", "mti", "lti", "other", "pension", "one_time",
           "birth_year", "employees", "staff_cost", "tsr", "n_execs"]


def read(path: Path, columns: list[str]) -> pd.DataFrame:
    df = (pd.read_csv(path, dtype=str, keep_default_na=False).replace("", None)
          if path.exists() else pd.DataFrame(columns=columns))
    df = df.reindex(columns=list(dict.fromkeys([*columns, *df.columns])))
    for col in NUMBERS:
        if col in df:
            df[col] = num(df[col])
    for col in ("female", "german"):
        if col in df:
            df[col] = df[col].str.lower().isin(["yes", "true", "1"])
    return df


def load_all(raw: Path) -> list[Batch]:
    execs = read(raw / "manual" / "execs.csv", EXEC_COLUMNS)
    fy = read(raw / "manual" / "firm_years.csv", FIRM_YEAR_COLUMNS)
    batches = []
    for regime, years in (("legacy", lambda y: y < FIRST_162), ("§162", lambda y: y >= FIRST_162)):
        e, f = execs[years(execs["year"])], fy[years(fy["year"])]
        if e.empty and f.empty:
            continue
        note = issue(f"manual-{regime}", "note", f"Rows entered by hand ({regime})",
                     "Added with the dashboard's Add data form (data/raw/manual/); each row "
                     "names its source.", len(e) + len(f))
        batches.append(Batch(f"Manual entry ({regime})", regime, e.reset_index(drop=True),
                             f.reset_index(drop=True), issues=[note]))
    return batches
