"""The dashboard's "Add data" form: the tables a user may add rows to, their columns, and a
plausibility check of a new pay row.

New executive-years and firm-years go to data/raw/manual/ in the canonical columns and are read
by sources/manual.py; corrections, aliases, industry codes and KPI categories go to the curated
CSVs in data/reference/. Every save is validated by a full panel build: if the build fails, the
file is restored and the build's error is returned. After a save every cached result is dropped
and rebuilt in the background, so the dashboard and the assistant see the new row.
"""

from __future__ import annotations

import csv
import io
import threading
from dataclasses import asdict, dataclass, field
from pathlib import Path

import pandas as pd
from pypdf import PdfReader

from . import forecast, panel, peers, reference
from .panel import CACHE, COMPONENTS, RAW, cached

MANUAL = RAW / "manual"
SHARES = {"fixed": "Fixed salary", "sti": "Annual bonus", "long_term": "Multi-year and share-based pay"}
TOO_LARGE = 50_000  # k€: a single component above 50 M€ is almost certainly entered in €
MAX_TEXT = 120_000  # characters of one document handed to the assistant


@dataclass(frozen=True)
class Column:
    name: str
    kind: str              # 'text', 'number', 'integer', 'choice', 'bool', 'firm'
    label: str
    required: bool = False
    unit: str | None = None
    options: tuple[str, ...] = ()
    help: str = ""


@dataclass(frozen=True)
class Table:
    id: str
    name: str
    path: Path
    purpose: str
    columns: tuple[Column, ...]
    deletable: bool = False   # rows of the hand-entry files; curated CSVs are edited as files


def amount(name: str, label: str, help: str = "") -> Column:
    return Column(name, "number", label, unit="k€", help=help)


SOURCE = Column("source", "text", "Source", True,
                help="Where the values come from, e.g. 'SAP Vergütungsbericht 2025, p. 14'.")
FIRM = Column("firm", "firm", "Company", True, help="A company in the panel, or a new name.")
YEAR = Column("year", "integer", "Year", True)

TABLES = [
    Table("execs", "Executive pay", MANUAL / "execs.csv",
          "A new executive-year, e.g. from a remuneration report. The company must have a "
          "firm-year row (from the data or added below) for that year.",
          (FIRM, YEAR,
           Column("first_name", "text", "First name", True),
           Column("last_name", "text", "Last name", True),
           Column("role", "choice", "Role", True, options=("CEO", "CFO", "Member")),
           Column("days", "integer", "Days in office", True, "days",
                  help="Days on the board in that year; 360 or more counts as a full year."),
           amount("fixed", "Fixed salary"), amount("sti", "Annual bonus"),
           amount("mti", "Multi-year bonus"), amount("lti", "Share-based pay"),
           amount("other", "Other benefits"), amount("pension", "Pension cost"),
           amount("one_time", "One-time payments", "Sign-on, severance and similar."),
           Column("female", "bool", "Woman"), Column("german", "bool", "German nationality"),
           Column("birth_year", "integer", "Year of birth"), SOURCE),
          deletable=True),
    Table("firm_years", "Firm-year", MANUAL / "firm_years.csv",
          "A company in a year that is not in the data yet: index listing and, where known, "
          "employees, staff costs and shareholder return.",
          (FIRM, YEAR,
           Column("index", "choice", "Index", options=("DAX", "MDAX")),
           Column("employees", "number", "Employees"),
           amount("staff_cost", "Personnel expenses"),
           Column("tsr", "number", "Total shareholder return", unit="fraction",
                  help="0.12 for +12 %."),
           SOURCE),
          deletable=True),
    Table("overrides", "Value correction", reference.REFERENCE / "overrides.csv",
          "Fix a value that is already in the panel. Each row must match exactly one record.",
          (Column("table", "choice", "Table", True, options=("execs", "firm_years")),
           FIRM, YEAR,
           Column("person", "text", "Person", help="Full name; only for the table 'execs'."),
           Column("field", "text", "Field", True, help="Column name, e.g. 'sti' or 'employees'."),
           Column("value", "text", "New value", help="Empty clears the value."),
           Column("note", "text", "Why", True))),
    Table("firm_aliases", "Firm alias", reference.REFERENCE / "firm_aliases.csv",
          "Another spelling or an old name of a company.",
          (Column("alias", "text", "Alias", True), Column("name", "text", "Name", True),
           Column("note", "text", "Note"))),
    Table("industries", "Industry code", reference.REFERENCE / "industries.csv",
          "A company's six-digit NAICS 2022 code; used by the industry peer groups.",
          (FIRM, Column("naics", "text", "NAICS code", True, help="Six digits, e.g. 513210."),
           Column("reviewed", "choice", "Reviewed", options=("yes",)),
           Column("note", "text", "Note"))),
    Table("kpi_categories", "KPI category", reference.REFERENCE / "kpi_categories.csv",
          "The category of a bonus criterion named in a remuneration report.",
          (Column("name", "text", "KPI name", True),
           Column("category", "choice", "Category", True, options=tuple(reference.KPI_GROUPS)),
           Column("reviewed", "choice", "Reviewed", options=("yes",)),
           Column("note", "text", "Note"))),
]


def custom_tables() -> list[Table]:
    """Firm and firm-year attribute tables in data/*/tables/: columns from the file header."""
    out = []
    for folder in (RAW / "tables", reference.REFERENCE / "tables"):
        for path in sorted(folder.glob("*.csv")):
            header = next(csv.reader(path.open(encoding="utf-8")))
            cols = tuple(FIRM if c == "firm" else YEAR if c == "year" else Column(c, "text", c)
                         for c in header)
            out.append(Table(f"custom:{path.stem}", f"Table {path.name}", path,
                             "An attribute table; values fill empty cells only.", cols))
    return out


def tables() -> list[Table]:
    return TABLES + custom_tables()


def table(table_id: str) -> Table | None:
    return next((t for t in tables() if t.id == table_id), None)


def rows(t: Table) -> list[dict]:
    if not t.path.exists():
        return []
    return pd.read_csv(t.path, dtype=str, keep_default_na=False).to_dict("records")


def describe(t: Table) -> dict:
    return {**{k: v for k, v in asdict(t).items() if k != "path"},
            "file": str(t.path.relative_to(panel.ROOT)), "rows": rows(t)}


# --------------------------------------------------------------------------- saving


def clean(t: Table, row: dict) -> dict[str, str]:
    """Strings in the table's column order; raises ValueError naming the field and the fix."""
    out = {}
    for c in t.columns:
        v = str(row.get(c.name) if row.get(c.name) is not None else "").strip()
        if not v:
            if c.required:
                raise ValueError(f"{c.label} is required.")
        elif c.kind == "number":
            try:
                float(v)
            except ValueError:
                raise ValueError(f"{c.label}: '{v}' is not a number (use a dot for decimals).") from None
        elif c.kind == "integer" and not v.lstrip("-").isdigit():
            raise ValueError(f"{c.label}: '{v}' is not a whole number.")
        elif c.kind == "choice" and v not in c.options:
            raise ValueError(f"{c.label}: choose one of {', '.join(c.options)}.")
        elif c.kind == "bool":
            v = "yes" if v.lower() in ("yes", "true", "1") else "no"
        out[c.name] = v
    return out


_saving = threading.Lock()


def write(changes: dict[Table, list[dict]]) -> None:
    """Replace the rows of each table, rebuild the panel once, and restore every file if the
    build fails: a draft that spans a firm-year and its executives is kept whole or not at all."""
    with _saving:
        before = {t: t.path.read_bytes() if t.path.exists() else None for t in changes}
        for t, new_rows in changes.items():
            header = [c.name for c in t.columns]
            if before[t]:  # keep columns a hand-edited file may have beyond the form's
                header += [c for c in next(csv.reader(before[t].decode("utf-8").splitlines()))
                           if c not in header]
            t.path.parent.mkdir(parents=True, exist_ok=True)
            with t.path.open("w", newline="", encoding="utf-8") as f:
                w = csv.DictWriter(f, header, extrasaction="ignore")
                w.writeheader()
                w.writerows(new_rows)
        try:
            built = panel.build()
        except Exception:
            for t, old in before.items():
                if old is None:
                    t.path.unlink(missing_ok=True)
                else:
                    t.path.write_bytes(old)
            raise
        cached(CACHE, lambda: built)
    refresh()


def add(changes: list[tuple[Table, list[dict]]]) -> int:
    """Append rows to one or more tables in one build; returns how many were added."""
    new = {t: [clean(t, r) for r in rs] for t, rs in changes}
    write({t: [*rows(t), *rs] for t, rs in new.items()})
    return sum(map(len, new.values()))


def delete(t: Table, index: int) -> None:
    current = rows(t)
    if not t.deletable or not 0 <= index < len(current):
        raise ValueError("Only rows of the hand-entry tables can be deleted here.")
    write({t: current[:index] + current[index + 1:]})


def validate(changes: list[tuple[Table, list[dict]]]) -> list[dict]:
    """Per row: the error that would stop saving, or the plausibility check of a pay row.
    Firm-years in the same draft count as present."""
    pending = {(panel.slug(reference.aliases().get(r.get("firm", ""), r.get("firm", ""))), str(r.get("year")))
               for t, rs in changes if t.id == "firm_years" for r in rs}
    out = []
    for t, rs in changes:
        for i, r in enumerate(rs):
            if t.id == "execs":
                findings = check(r, pending)["findings"]
            else:
                try:
                    clean(t, r)
                    findings = []
                except ValueError as e:
                    findings = [{"level": "error", "field": None, "message": str(e)}]
            out.append({"table": t.id, "row": i, "findings": findings})
    return out


def refresh() -> None:
    """Drop every cached result and rebuild them in the background."""
    panel.get_panel.cache_clear()
    peers.get_benchmarks.cache_clear()
    forecast._forecasts.cache_clear()
    from . import assistant
    assistant.database.cache_clear()
    threading.Thread(target=forecast.get_forecasts, daemon=True).start()


def extract_text(name: str, data: bytes) -> dict:
    """Plain text of a PDF (pages marked, so a row can cite its page) or of a text file."""
    pages = None
    if name.lower().endswith(".pdf"):
        texts = [page.extract_text() or "" for page in PdfReader(io.BytesIO(data)).pages]
        pages = len(texts)
        text = "\n\n".join(f"[page {i}]\n{t}" for i, t in enumerate(texts, 1))
    else:
        text = data.decode("utf-8", errors="replace")
    return {"name": name, "text": text[:MAX_TEXT], "pages": pages, "truncated": len(text) > MAX_TEXT}


# --------------------------------------------------------------------------- checking


@dataclass
class Check:
    findings: list[dict] = field(default_factory=list)   # level, field, message
    context: dict = field(default_factory=dict)

    def add(self, level: str, message: str, field_: str | None = None) -> None:
        self.findings.append({"level": level, "field": field_, "message": message})


def keur(v: float) -> str:
    return f"{v:,.0f} k€"


def check(row: dict, pending: set[tuple[str, str]] = frozenset()) -> dict:
    """Plausibility of a new executive-year: typos first, then the executive's own forecast,
    the board and the peers. Warnings never block saving: an unusual value can be real."""
    c = Check()
    try:
        r = clean(TABLES[0], row)
    except ValueError as e:
        c.add("error", str(e))
        return asdict(c)
    pay = {k: float(r[k]) for k in [*COMPONENTS, "pension", "one_time"] if r.get(k)}
    for k, v in pay.items():
        if v > TOO_LARGE:
            c.add("warning", f"{keur(v)} is over 50 M€. Amounts are in k€: did you mean "
                             f"{keur(v / 1000)}?", k)
        if v < 0 and k != "pension":
            c.add("warning", "Negative amount.", k)
    if int(r["days"]) < 360:
        c.add("info", "Fewer than 360 days: pay statistics and forecasts leave this row out.", "days")
    if pay.get("one_time"):
        c.add("info", "One-time payments are not part of total pay and have no model.", "one_time")
    total = sum(pay.get(k, 0) for k in COMPONENTS)
    if total <= 0:
        return asdict(c)
    c.context["total"] = total

    p, f, b = panel.get_panel(), forecast.get_forecasts(), peers.get_benchmarks()
    firm_id = panel.slug(reference.aliases().get(r["firm"], r["firm"]))
    year, role = int(r["year"]), r["role"]
    known = ((p.firm_years["firm_id"] == firm_id) & (p.firm_years["year"] == year)).any()
    if not known and (firm_id, str(year)) not in pending:
        c.add("info", f"{r['firm']} {year} has no firm-year yet: add it in the table 'Firm-year' "
                      "first, or saving will fail.", "firm")
    own = own_history(c, p, f, firm_id, r, year, total)
    board_ratio(c, f, firm_id, role, total, own)
    peer_range(c, f, b, firm_id, role, total)
    mix(c, f, role, pay, total)
    return asdict(c)


def own_history(c: Check, p, f, firm_id: str, r: dict, year: int, total: float) -> str | None:
    """Compare with the executive's last year and, after the latest year, their forecast."""
    e = p.execs[(p.execs["firm_id"] == firm_id) & (p.execs["last_name"].str.strip() == r["last_name"])
                & (p.execs["year"] < year) & p.execs["full_year"]]
    if e.empty:
        c.add("info", "No earlier year of this executive at this company: compared with the board "
                      "and the peers only.")
        return None
    last = e.sort_values("year").iloc[-1]
    change = total / last["total"] - 1
    c.context["previous"] = {"year": int(last["year"]), "total": float(last["total"])}
    if abs(change) > 0.5:
        c.add("warning", f"Total pay {change:+.0%} against {int(last['year'])} "
                         f"({keur(last['total'])}).", "total")
    live = f.live[(f.live["person_id"] == last["person_id"]) & (f.live["target"] == "total")
                  & (f.live["model"] == f.best["total"]) & (f.live["year"] == year)]
    if len(live):
        x = live.iloc[0]
        lo, hi = x[f"lo{forecast.BAND:g}"], x[f"hi{forecast.BAND:g}"]
        c.context["forecast"] = {"value": float(x["value"]), "lo": float(lo), "hi": float(hi)}
        inside = lo <= total <= hi
        c.add("ok" if inside else "warning",
              f"Forecast for {year}: {keur(x['value'])} (80 % range {keur(lo)}–{keur(hi)}); "
              f"entered {keur(total)} is {'inside' if inside else 'outside'} the range.", "total")
    return last["person_id"]


def board_ratio(c: Check, f, firm_id: str, role: str, total: float, person: str | None) -> None:
    """Non-CEOs against their CEO, compared with the usual ratio for the role."""
    if role == "CEO":
        return
    board = f.now[(f.now["firm_id"] == firm_id)]
    ceo = board.loc[(board["role"] == "CEO") & (board["person_id"] != person), "total"].max()
    if not ceo > 0:
        return
    ceo_pay = f.now[f.now["role"] == "CEO"].groupby("firm_id")["total"].max()
    same = f.now[f.now["role"] == role]
    usual = (same["total"] / same["firm_id"].map(ceo_pay)).dropna()
    lo, hi = usual.quantile([0.1, 0.9])
    ratio = total / ceo
    c.context["ratio_to_ceo"] = {"value": ratio, "lo": lo, "hi": hi}
    c.add("ok" if lo <= ratio <= hi else "warning",
          f"{ratio:.2f}× the CEO's pay ({keur(ceo)}); usual for this role {lo:.2f}–{hi:.2f}×.")


def peer_range(c: Check, f, b, firm_id: str, role: str, total: float) -> None:
    year = f.now.loc[f.now["firm_id"] == firm_id, "year"].max()
    year = f.last_year if pd.isna(year) else int(year)
    links = b.links[(b.links["method"] == f.peer_method) & (b.links["firm_id"] == firm_id)
                    & (b.links["year"] == year) & (b.links["role"] == role)]
    pool = f.now.loc[f.now["firm_id"].isin(links["peer_firm"]) & (f.now["role"] == role), "total"]
    if pool.size < peers.MIN_PEER_FIRMS:
        return
    q = pool.quantile([0.1, 0.5, 0.9])
    c.context["peers"] = {"p10": q[0.1], "median": q[0.5], "p90": q[0.9], "n": int(pool.size)}
    inside = q[0.1] <= total <= q[0.9]
    c.add("ok" if inside else "warning",
          f"Peers in {year} ({pool.size} executives): median {keur(q[0.5])}, 10–90 % "
          f"{keur(q[0.1])}–{keur(q[0.9])}; entered {keur(total)} is "
          f"{'inside' if inside else 'outside'} that range.", "total")


def mix(c: Check, f, role: str, pay: dict, total: float) -> None:
    """Each share of pay against the 5–95 % range of the same role in the latest year."""
    now = f.now[(f.now["role"] == role) & (f.now["total"] > 0)]
    usual = pd.DataFrame({"fixed": now["fixed"], "sti": now["sti"],
                          "long_term": now[["mti", "lti"]].fillna(0).sum(axis=1)}).div(now["total"], axis=0)
    shares = {"fixed": pay.get("fixed", 0), "sti": pay.get("sti", 0),
              "long_term": pay.get("mti", 0) + pay.get("lti", 0)}
    for k, v in shares.items():
        share, (lo, hi) = v / total, usual[k].quantile([0.05, 0.95])
        if not lo <= share <= hi:
            c.add("warning", f"{SHARES[k]} is {share:.1%} of total pay; usual for {role}s in "
                             f"{f.last_year} (5–95 %): {lo:.1%}–{hi:.1%}.", k)
    c.context["shares"] = {k: v / total for k, v in shares.items()}
