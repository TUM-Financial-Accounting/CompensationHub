import shutil

import pandas as pd
import pytest
from fastapi.testclient import TestClient

from app import panel as panel_module
from app import reference
from app.main import app
from app.panel import RAW, apply_overrides, build, get_panel
from app.sources.dsw import esg_plan


@pytest.fixture(scope="module")
def panel():
    return get_panel()


def test_every_source_is_discovered(panel):
    labels = [s["label"] for s in panel.sources]
    assert labels[0].startswith("legacy panel") and labels[1:] == ["DSW 2022", "DSW 2023", "DSW 2024"]


def test_keys_are_unique(panel):
    assert not panel.firms["firm_id"].duplicated().any()
    assert not panel.firm_years.duplicated(["firm_id", "year"]).any()
    assert not panel.execs.duplicated(["firm_id", "year", "person_id"]).any()


def test_legacy_total_equals_source_total_comp(panel):
    src = pd.read_csv(RAW / "2006-2021" / "person_year.csv", sep="|").dropna(subset=["exec_id"])
    ours = panel.execs[panel.execs["regime"] == "legacy"]
    assert len(ours) == len(src)
    assert ours["total"].sum() == pytest.approx(src["total_comp"].sum(), rel=1e-9)


def test_all_source_facts_find_their_firm(panel):
    assert not [i["title"] for i in panel.issues if i["id"].startswith("unmatched-")]


def test_renamed_firms_join_across_sources(panel):
    modern = set(panel.execs.loc[panel.execs["regime"] == "§162", "firm_id"])
    no_isin = set(panel.firms.loc[panel.firms["isin"].isna(), "firm_id"])
    assert modern & no_isin == {"porsche-ag"}  # the only firm that is new in 2022
    assert {"mercedes-benz", "heidelberg-materials", "airbus", "porsche-se"} <= modern


def test_one_dax_universe_per_year_after_break(panel):
    fy = panel.firm_years[panel.firm_years["regime"] == "§162"]
    assert fy.groupby("year").size().eq(40).all()
    assert (fy["index"] == "DAX").all()


def test_dropped_in_tables_and_overrides(tmp_path, monkeypatch):
    """The extension workflow end to end: a firm table, a firm-year table and an override."""
    ref = tmp_path / "reference"
    shutil.copytree(reference.REFERENCE, ref)
    (ref / "tables").mkdir(exist_ok=True)
    (ref / "tables" / "sector.csv").write_text("firm,sector\nSAP,Software\nNew Firm AG,Retail\n")
    (ref / "tables" / "size.csv").write_text("firm,year,revenue\nsap,2024,34176\nDaimler,2021,1\n")
    (ref / "overrides.csv").write_text(
        "table,firm,year,person,field,value,note\n"
        "firm_years,Allianz,2024,,lti_esg_share,33.33,test\n"
        "execs,SAP,2024,Christian Klein,other,0,test\n")
    monkeypatch.setattr(reference, "REFERENCE", ref)

    p = build()
    firms = p.firms.set_index("firm_id")
    fy = p.firm_years.set_index(["firm_id", "year"])
    assert firms.loc["sap", "sector"] == "Software"
    assert fy.loc[("sap", 2024), "revenue"] == 34176
    assert fy.loc[("mercedes-benz", 2021), "revenue"] == 1  # alias resolved
    assert p.extra_firm_columns == ["sector"] and p.extra_year_columns == ["revenue"]
    assert any(i["id"] == "unmatched-sector.csv" for i in p.issues)  # New Firm AG reported
    assert fy.loc[("allianz", 2024), "lti_esg_share"] == pytest.approx(33.33)
    klein = p.execs[(p.execs["name"] == "Christian Klein") & (p.execs["year"] == 2024)]
    assert klein["other"].item() == 0
    assert klein["total"].item() == pytest.approx(klein[panel_module.COMPONENTS[:4]].sum(axis=1).item())


def test_override_that_matches_nothing_fails():
    table = pd.DataFrame([{"table": "firm_years", "firm": "Nope", "year": "2024", "person": "",
                           "field": "tsr", "value": "1", "note": ""}])
    fy = pd.DataFrame({"firm_id": ["sap"], "year": [2024], "tsr": [0.1]})
    with pytest.raises(ValueError, match="matches 0 rows"):
        apply_overrides(table, pd.DataFrame(), fy, str.lower)


@pytest.mark.parametrize("name, category", [
    ("ROCE", "Return on capital"),
    ("Relativer TSR vs. DAX", "Share price & TSR"),
    ("Bereinigtes Ergebnis je Vorzugsaktie (EPS)", "Profit & EPS"),
    ("Free Cashflow Konzern", "Cash flow & balance sheet"),
    ("ESG-Faktor", "ESG"),
    ("Erträge Privatkundenbank (PB)", "Revenue & growth"),
    ("Individueller Multiplikator", "Individual & discretionary"),
    ("Komponente strategische Fokusziele", "Strategic & operational"),
    ("Konzernfinanzziele", "Financial, unspecified"),
    ("Gesamtleistung", "Unspecified"),
])
def test_kpi_keyword_rules_for_new_names(name, category):
    assert reference.guess_kpi_category(name) == category


@pytest.mark.parametrize("share,kind,expected", [
    (25.0, 2, (25.0, "target", False)),
    (100, 1, (100.0, "multiplier", False)),
    ("20; 33,33", "1; 2", (33.33, "target + multiplier", False)),  # Deutsche Telekom 2023
    ("100; 25", "1; 2", (25.0, "target + multiplier", False)),     # Heidelberg 2024
    (0, None, (0.0, None, False)),
])
def test_esg_share_follows_the_kind_column(share, kind, expected):
    assert esg_plan(share, kind) == expected


def test_two_esg_multipliers_stay_unresolved():
    value, kind, unresolved = esg_plan("75; 100", "1; 1")  # Mercedes-Benz 2023
    assert pd.isna(value) and kind == "multiplier" and unresolved


def test_every_kpi_name_is_reviewed(panel):
    assert panel.kpi_unlisted == []
    issue = next(i for i in panel.issues if i["id"] == "kpi-categories")
    assert issue["kind"] == "fixed"


def test_every_route_answers():
    with TestClient(app) as client:
        for url in ["/api/summary", "/api/trends", "/api/trends?scope=all", "/api/firms",
                    "/api/firms/sap", "/api/executives?year=2014", "/api/people/p4",
                    "/api/design", "/api/board", "/api/quality", "/api/peers",
                    "/api/peers/verdicts?year=2024", "/api/peers/size?year=2010&role=CFO",
                    "/api/peers/cluster", "/api/peers/forest", "/api/firms/sap/peers"]:
            assert client.get(url).status_code == 200, url
        assert client.get("/api/firms/nope").status_code == 404
        assert client.get("/api/peers/nope").status_code == 404
