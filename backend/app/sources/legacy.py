"""The chair's legacy panel: pipe-delimited CSVs, DAX + MDAX, DCGK model tables (2006–2021).

Any folder under data/raw/ that contains company_year.csv, person_year.csv and
company_person.csv is read. Inside the panel the ISIN identifies a firm; each ISIN is emitted
under its latest name. A blank pay field means "not reported" (confirmed with the chair).
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

from . import Batch, issue

PAY = {
    "fixed": "salary", "sti": "one_year_bonus", "mti": "multi_year_bonus",
    "lti": "total_equity_grants", "other": "other_annual_comp",
    "pension": "pension", "one_time": "one_time_payment",
}


def load_all(raw: Path) -> list[Batch]:
    return [load(p.parent) for p in sorted(raw.glob("*/company_year.csv"))]


def load(folder: Path) -> Batch:
    cy = pd.read_csv(folder / "company_year.csv", sep="|")
    py = pd.read_csv(folder / "person_year.csv", sep="|")
    cp = pd.read_csv(folder / "company_person.csv", sep="|")
    issues: list[dict] = []

    spaced = set(cy.loc[cy["isin"].str.contains(" "), "isin"])  # e.g. IKB's "DE 0008063306"
    for df in (cy, py, cp):
        df["isin"] = df["isin"].str.replace(" ", "", regex=False)
    latest = cy.sort_values("year").groupby("isin").agg(
        short=("company_shortname", "last"), renamed=("new_cnameshort", "last"))
    delivered = latest["renamed"].fillna(latest["short"]).str.replace("_neu2017", "", regex=False)
    name = delivered.str.strip()
    spaced = sorted(spaced | set(delivered[delivered != name]))

    firm_years = pd.DataFrame({
        "firm": cy["isin"].map(name),
        "isin": cy["isin"],
        "year": cy["year"],
        "index": cy["index_listing"].replace({"DAX and MDAX": "DAX"}),
        "opt_out": cy["opting_out"].eq(1),
        "n_execs": cy["n_executives"],
        "board_total": cy["total_comp_bt"],
        "board_total_incl": cy["total_comp_pens_and_one_time_bt"],
    })

    no_id = py["exec_id"].isna()
    py = py[~no_id].astype({"exec_id": int})
    person = cp.drop_duplicates("exec_id").set_index("exec_id").loc[py["exec_id"]]
    execs = pd.DataFrame({
        "firm": py["isin"].map(name).to_numpy(),
        "isin": py["isin"].to_numpy(),
        "year": py["year"].to_numpy(),
        "person_ref": ("p" + py["exec_id"].astype(str)).to_numpy(),
        "first_name": person["exec_firstname"].to_numpy(),
        "last_name": person["exec_lastname"].to_numpy(),
        "role": np.select([py["ceo_flag_eoy"].eq(1), py["cfo_flag_eoy"].eq(1)],
                          ["CEO", "CFO"], "Member"),
        "female": person["female"].eq(1).to_numpy(),
        "german": person["nationality"].str.contains("German", na=False).to_numpy(),
        "birth_year": pd.to_datetime(person["date_of_birth"], format="%d%b%Y",
                                     errors="coerce").dt.year.to_numpy(),
        "days": py["days"].to_numpy(),
    })
    for ours, theirs in PAY.items():
        execs[ours] = py[theirs].to_numpy()

    missing_index = cy["index_listing"].isna()
    issues += [
        issue("legacy-spaces", "fixed", "Stray spaces in ISINs and firm names removed",
              "As delivered: " + ", ".join(f"'{s}'" for s in spaced) + ".", len(spaced)),
        issue("legacy-no-person-id", "fixed", "Person-years without a person ID dropped",
              "Rhön-Klinikum 2013: rows with no company_person_id and all pay fields zero.",
              int(no_id.sum())),
        issue("legacy-no-index", "decide", "Firm-years with no index listing",
              "Excluded by the DAX filter, kept under 'All firms'. About half are a firm's first "
              f"year in the panel, the rest gaps between listed years. Worst year: 2017 "
              f"({int(missing_index[cy['year'] == 2017].sum())} firms).",
              int(missing_index.sum())),
        issue("legacy-not-reported", "note", "Blank pay components mean 'not reported'",
              "From 2013/14 the multi-year bonus is blank in ~40 % of rows and one-time payments "
              "in ~90 %, after the reporting template changed. Totals are the source's own "
              "totals and may understate pay where a component was not reported; pay-mix "
              "shares use fully reported rows only."),
        issue("legacy-negative-pension", "note", "Negative pension service costs",
              "Plausible (plan changes release provisions) but worth a spot check.",
              int((py["pension"] < 0).sum())),
        issue("opt-out", "note", "Opt-out firm-years have board totals only",
              "Firms that opted out of individual disclosure (§286(5) HGB) report no "
              "per-executive rows. Rate fell from 25 % (2006) to 0 % (2021).",
              int(cy["opting_out"].sum())),
        issue("extreme-grants", "note", "Very large grant-date values",
              "Ströer 2020 (board equity grants 243 M€), Zalando 2018 (57 M€), Beiersdorf 2018 "
              "(CEO 23.5 M€). Real disclosures valued at grant; winsorise for modelling, not for "
              "display. Count: executive-years above 15 M€.",
              int((py["total_comp"] > 15_000).sum())),
        issue("metro-isin", "note", "Metro's history follows its management, as in the source",
              "Pre-2017 Metro rows carry DE000BFB0019 (new METRO AG, listed 2017), where the CEO "
              "moved after the split; the old Metro AG's ISIN DE0007257503 continues as "
              "Ceconomy. Kept as delivered."),
        issue("ceo-flag", "note", "Legacy CEO flag is end-of-year only",
              "A CEO who left during the year appears as a board member for that year. Pay "
              "statistics use full-year executives, which removes hand-over years."),
    ]
    # company_person also lists people who joined in 2022 or moved firms: a linking directory.
    people = pd.DataFrame({"firm": cp["isin"].map(name), "first_name": cp["exec_firstname"],
                           "last_name": cp["exec_lastname"],
                           "person_ref": "p" + cp["exec_id"].astype(str)}).dropna(subset=["firm"])
    years = f"{cy['year'].min()}–{cy['year'].max()}"
    return Batch(f"legacy panel {years}", "legacy", execs, firm_years, issues=issues, people=people)
