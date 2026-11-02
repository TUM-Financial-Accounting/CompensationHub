"""Hand-curated reference tables in data/reference/ (versioned in git, no confidential data).

    firm_aliases.csv    alias,name,note              other spellings and renames → one firm name
    kpi_categories.csv  name,category,reviewed,note  KPI name → category (see KPI_GROUPS); rules guess the rest
    industries.csv      firm,naics,reviewed,note     each firm's NAICS 2022 code (main activity)
    naics_2022.csv      code,title                   official NAICS 2022 list (US Census Bureau)
    overrides.csv       table,firm,year,person,field,value,note
                                                     manual corrections, applied after loading
    tables/*.csv        firm[,year],…                curated firm or firm-year attributes
"""

from __future__ import annotations

import re
from pathlib import Path

import pandas as pd

REFERENCE = Path(__file__).resolve().parents[2] / "data" / "reference"

# KPI categories and the group each belongs to. Groups follow the four kinds of performance
# criteria in Armeli & Fligge (2026), "Die Ausgestaltung der Vorstandsvergütung in Deutschland",
# Hans-Böckler-Stiftung, Mitbestimmungsreport 89. Definitions: docs/data.md, "KPI categories".
KPI_GROUPS = {
    "Profit & EPS": "Financial",
    "Return on capital": "Financial",
    "Cash flow & balance sheet": "Financial",
    "Revenue & growth": "Financial",
    "Financial, unspecified": "Financial",
    "Share price & TSR": "Capital market",
    "ESG": "Non-financial",
    "Strategic & operational": "Non-financial",
    "Non-financial, unspecified": "Non-financial",
    "Individual & discretionary": "Individual",
    "Unspecified": "Unspecified",
}

# Guesses for KPI names not yet in kpi_categories.csv (new data). First match wins.
KPI_RULES: list[tuple[str, str]] = [
    ("Unspecified", r"^(kriterien|gesamtleistung|zielbetrag|weitere ziele|konzernziele$)"),
    ("Financial, unspecified", r"^(finanzielle|konzernfinanz|segmentfinanz)"),
    ("Non-financial, unspecified", r"^nicht-?finanz"),
    ("ESG", r"esg|nachhaltig|sustainab|co2|dekarbon|emission|klima|climate|\bnps\b|promoter|"
            r"kundenzufriedenheit|mitarbeiter|engagement|diversit|safety|compliance|vorschrift|"
            r"regulat"),
    ("Return on capital", r"roce|roic|\broe\b|rote|\broi\b|kapitalrendite|kapitalrentabilit|"
                          r"\beva\b|asset charge|\beac\b|eingesetzte|wacc"),
    ("Cash flow & balance sheet", r"cash|fcf|focf|working capital|verschuldung|\bnta\b|tbvps|"
                                  r"buchwert|kapitalwachstum"),
    ("Profit & EPS", r"ebit|\bebt\b|\beps\b|ergebnis|gewinn|marge|margin|umsatzrendite|\bros\b|"
                     r"jahresüberschuss|income|profit|earnings|kosten|\bffo\b"),
    ("Revenue & growth", r"umsatz|erlöse|erträge|revenue|sales|wachstum|growth|backlog|"
                         r"warenvolumen"),
    ("Share price & TSR", r"tsr|aktie|kurs|stoxx|msci|\bdax\b|relative performance"),
    ("Individual & discretionary", r"individu|persönlich|leistungsfaktor|perfo?rmance.?faktor|"
                                   r"beitrag|multiplikator|modifier|scorecard|ressort|ermessen|"
                                   r"anpassungsfaktor"),
    ("Strategic & operational", r"strateg|transformation|innovation|operating model|"
                                r"betriebsmodell|führungsposition|prioritäten|markt|digital|risik"),
]


def read(name: str, columns: list[str]) -> pd.DataFrame:
    """A reference CSV as strings; an absent file is an empty table."""
    path = REFERENCE / name
    if not path.exists():
        return pd.DataFrame(columns=columns)
    df = pd.read_csv(path, dtype=str, keep_default_na=False).apply(lambda c: c.str.strip())
    missing = set(columns) - set(df.columns)
    if missing:
        raise ValueError(f"{path}: missing columns {sorted(missing)}")
    return df


def aliases() -> dict[str, str]:
    df = read("firm_aliases.csv", ["alias", "name"])
    return dict(zip(df["alias"], df["name"]))


def guess_kpi_category(name: str) -> str:
    text = name.lower()
    return next((cat for cat, pattern in KPI_RULES if re.search(pattern, text)), "Unspecified")


def kpi_categories(names: set[str]) -> tuple[dict[str, list[str]], list[str], int]:
    """Categories for every name: curated where listed (several, separated by ';', for composite
    metrics), keyword guess otherwise.

    Returns (categories, names missing from the CSV, listed names not yet reviewed).
    """
    df = read("kpi_categories.csv", ["name", "category", "reviewed"])
    curated = {n: [c.strip() for c in cats.split(";")] for n, cats in zip(df["name"], df["category"])}
    for n, cats in curated.items():
        unknown = [c for c in cats if c not in KPI_GROUPS]
        if unknown:
            raise ValueError(f"kpi_categories.csv: unknown category {unknown} for '{n}'. "
                             f"Allowed: {', '.join(KPI_GROUPS)}")
    missing = sorted(names - curated.keys())
    unreviewed = int((df["reviewed"] != "yes").sum())
    return {n: curated.get(n) or [guess_kpi_category(n)] for n in names}, missing, unreviewed


def add_kpi_names(names: list[str]) -> None:
    """Append names with the keyword guess, marked unreviewed, for someone to check."""
    path = REFERENCE / "kpi_categories.csv"
    new = pd.DataFrame({"name": names, "category": [guess_kpi_category(n) for n in names],
                        "reviewed": "", "note": ""})
    old = read("kpi_categories.csv", ["name", "category", "reviewed"])
    pd.concat([old, new], ignore_index=True).to_csv(path, index=False)


def naics_titles() -> dict[str, str]:
    """NAICS 2022 code → title, for every level (sector '31-33' to six-digit industry)."""
    df = read("naics_2022.csv", ["code", "title"])
    return dict(zip(df["code"], df["title"]))


def industries() -> pd.DataFrame:
    """Each firm's six-digit NAICS code. An unknown code stops the build, like an unknown KPI
    category: a typo would silently put a firm in the wrong peer group."""
    df = read("industries.csv", ["firm", "naics", "reviewed"])
    titles = naics_titles()
    bad = df.loc[~df["naics"].isin(titles) | (df["naics"].str.len() != 6), ["firm", "naics"]]
    if not bad.empty:
        raise ValueError(f"industries.csv: not a six-digit NAICS 2022 code: "
                         f"{bad.to_dict('records')[:5]}")
    return df


def overrides() -> pd.DataFrame:
    return read("overrides.csv", ["table", "firm", "year", "person", "field", "value", "note"])


def tables(*folders: Path) -> list[tuple[str, pd.DataFrame]]:
    """Every CSV in the given folders, as (file name, frame). Each needs a `firm` column."""
    out = []
    for folder in folders:
        for path in sorted(folder.glob("*.csv")):
            df = pd.read_csv(path)
            if "firm" not in df:
                raise ValueError(f"{path}: needs a 'firm' column (name, alias or firm id)")
            out.append((path.name, df))
    return out
