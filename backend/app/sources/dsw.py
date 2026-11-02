"""DSW §162 AktG workbooks (2022 onwards, DAX).

Every data/raw/<year>/ folder with an Executive_Compensation*.xlsx is one batch; an
Executive_Compensation_ESG*.xlsx next to it is read too. Sheets are found by name prefix
(Compensation…, Members…, Companies…, DAX…), so a new year works without code changes as long
as the DSW keeps its column names.
"""

from __future__ import annotations

import re
from pathlib import Path

import numpy as np
import pandas as pd

from . import Batch, issue, num

PAY = {
    "fixed": "fix", "sti": "sti", "mti": "mtiprov", "lti": "lti", "other": "others",
    "pension": "pension", "one_time": "payoff",
}
MEMBER_COLUMNS = ["pdob", "pgender", "pnationality", "pboardentry", "TAGE im AMT", "Position",
                  "Intern/Extern"]


def load_all(raw: Path) -> list[Batch]:
    batches = []
    for folder in sorted(p for p in raw.iterdir() if p.is_dir() and p.name.isdigit()):
        books = sorted(folder.glob("Executive_Compensation*.xlsx"))
        main = [b for b in books if "ESG" not in b.name]
        esg = [b for b in books if "ESG" in b.name]
        if main:
            batches.append(load(int(folder.name), main[0], esg[0] if esg else None))
    return batches


def read_sheet(path: Path, prefix: str) -> pd.DataFrame:
    """First sheet whose name starts with `prefix`; the header is the row starting with
    `cnameshort`. Unnamed columns take the German label above; duplicate names keep the first."""
    sheet = next(s for s in pd.ExcelFile(path, engine="calamine").sheet_names
                 if s.startswith(prefix))
    raw = pd.read_excel(path, sheet_name=sheet, header=None, engine="calamine")
    header = raw.index[raw[0].astype(str).str.startswith("cnameshort")][0]
    labels = raw.iloc[header - 1] if header else raw.iloc[header]
    df = raw.iloc[header + 1:]
    df = df[df[0].notna()].copy()
    df.columns = [str(n if pd.notna(n) else lab).strip()
                  for n, lab in zip(raw.iloc[header], labels)]
    df = df.loc[:, ~df.columns.duplicated()].rename(columns={df.columns[0]: "cnameshort"})
    for col in ("cnameshort", "pfirstname", "psurname"):
        if col in df:
            df[col] = df[col].astype(str).str.strip()
    return df.reset_index(drop=True)


def role(position: object) -> str:
    """'CEO' and 'CEO/ <portfolio>' chair the board; 'CEO Healthcare' heads a division."""
    p = str(position).strip().lower()
    if p in ("ceo", "co-ceo") or re.match(r"ceo ?/", p):
        return "CEO"
    return "CFO" if p.startswith("cfo") else "Member"


def kpi_names(row: pd.Series) -> list[str]:
    """Named criteria of one plan; blanks and leaked Excel formulas ('+SUMMEWENN…') dropped."""
    return [s for v in row if isinstance(v, str) and (s := " ".join(v.split())) and s[0] not in "+="]


def load(year: int, path: Path, esg_path: Path | None) -> Batch:
    key = ["cnameshort", "pfirstname", "psurname"]
    comp = read_sheet(path, "Compensation")
    members = read_sheet(path, "Members")
    comp = comp.merge(members[key + MEMBER_COLUMNS], on=key, how="left", validate="one_to_one")
    max_col = next((c for c in comp if c.startswith("Maximalvergütung")), None)
    lt_cols = [c for c in ("mtipi1", "mtipi2", "mtipi3", "ltipi1", "ltipi2") if c in comp]

    execs = pd.DataFrame({
        "firm": comp["cnameshort"],
        "year": year,
        "first_name": comp["pfirstname"],
        "last_name": comp["psurname"],
        "role": comp["Position"].map(role),
        "female": comp["pgender"].astype(str).str.lower().eq("f"),
        "german": comp["pnationality"].astype(str).str.lower().str.contains("deutsch"),  # dual too
        "birth_year": pd.to_datetime(comp["pdob"], errors="coerce").dt.year,
        "days": num(comp["TAGE im AMT"]),
        "internal": comp["Intern/Extern"].where(comp["Intern/Extern"].isin(["Intern", "Extern"])),
        "sti_cap": num(comp["sticapdummy"]).eq(1),
        "sti_cap_pct": num(comp["sticap"]),
        "lti_cap": num(comp["lticapdummy"]).eq(1),
        "sti_kpis": comp[["stipi1", "stipi2", "stipi3"]].apply(kpi_names, axis=1),
        "lt_kpis": comp[lt_cols].apply(kpi_names, axis=1),
        "max_comp": num(comp[max_col]) if max_col else np.nan,
    })
    for ours, theirs in PAY.items():
        execs[ours] = num(comp[theirs])

    # The DSW study covers the DAX, and listed firms can no longer opt out after 2021.
    firm_years = pd.DataFrame({"firm": comp["cnameshort"].unique(), "year": year,
                               "index": "DAX", "opt_out": False})

    dax = read_sheet(path, "DAX")
    info = "cInformation" if "cInformation" in dax else "dax_exit"  # 2022: text sits in dax_exit
    companies = read_sheet(path, "Companies")
    tsr = "TSR" if "TSR" in companies else "Shareholder Return"
    facts = [
        pd.DataFrame({
            "firm": dax["cnameshort"], "year": year,
            "staff_cost": num(dax["cpersonnelexpenses"]),
            "employees": num(dax["cnremployees"]),
            "industry": dax[info].where(dax[info].map(lambda v: isinstance(v, str))),
        }).loc[lambda d: d["firm"].isin(comp["cnameshort"])],  # drops the 'Median'/'ø DAX' rows
        pd.DataFrame({"firm": companies["cnameshort"], "year": year,
                      "tsr": num(companies[tsr])}),
    ]

    issues = []
    serial = num(comp["pboardentry"]).notna().sum()
    if serial:
        issues.append(issue(f"serial-date-{year}", "fixed",
                            f"Excel serial number as board-entry date ({year})",
                            "Stored as a number instead of a date in the Members sheet.",
                            int(serial)))
    if esg_path:
        esg, esg_issues = load_esg(year, esg_path)
        facts.append(esg)
        issues += esg_issues
    return Batch(f"DSW {year}", "§162", execs, firm_years, facts, issues)


ESG_KIND = {1: "multiplier", 2: "target"}  # codes of <plan>_ESG_KPI_as_multiplier_or_KPI


def split(cell: object) -> list[float]:
    """'33,33; 100' → [33.33, 100.0]; blanks give []."""
    if pd.isna(cell):
        return []
    return [float(p.replace(",", ".")) for p in str(cell).split(";") if p.strip()]


def esg_plan(share: object, kind: object) -> tuple[float, str | None, bool]:
    """ESG share of one plan and how ESG enters it: an ESG target with a weight, or an ESG
    multiplier on the payout. Plans with both give two shares; the kind column lists the codes in
    the same order, so the target's value is the weight. Returns (share, kind, unresolved)."""
    values, kinds = split(share), [ESG_KIND.get(int(k)) for k in split(kind)]
    if len(values) <= 1:
        return (values[0] if values else np.nan), (kinds[0] if kinds and values and values[0] else None), False
    if sorted(kinds) == ["multiplier", "target"] and len(values) == 2:
        return values[kinds.index("target")], "target + multiplier", False
    return np.nan, "multiplier" if set(kinds) == {"multiplier"} else None, True


def load_esg(year: int, path: Path) -> tuple[pd.DataFrame, list[dict]]:
    df = read_sheet(path, "")
    df = df[df["cindex"].eq("DAX") & num(df["year"]).eq(year)]
    out = pd.DataFrame({"firm": df["cnameshort"], "year": year})
    unresolved = pd.Series(False, index=df.index)
    for plan in ("STI", "LTI"):
        parsed = [esg_plan(s, k) for s, k in
                  zip(df[f"{plan}_total_ESG_Share"], df[f"{plan}_ESG_KPI_as_multiplier_or_KPI"])]
        out[f"{plan.lower()}_esg_share"] = [v for v, _, _ in parsed]
        out[f"{plan.lower()}_esg_kind"] = [k for _, k, _ in parsed]
        unresolved |= pd.Series([u for _, _, u in parsed], index=df.index)
    issues = []
    if unresolved.any():
        issues.append(issue(
            f"esg-two-values-{year}", "decide", f"ESG shares with two values ({year})",
            "Plans that report two ESG multipliers (e.g. '75; 100') are left empty: the file does "
            "not say which share of pay each acts on. Settle them with data/reference/overrides.csv: "
            + ", ".join(df.loc[unresolved, "cnameshort"]), int(unresolved.sum())))
    return out, issues
