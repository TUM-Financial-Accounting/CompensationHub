import os

import psycopg
import pytest

from app import entry


def table(tmp_path):
    t = entry.TABLES[1]  # firm_years
    return entry.Table(t.id, t.name, tmp_path / "firm_years.csv", t.purpose, t.columns, True)


def test_rows_are_validated_with_a_message_that_says_how_to_fix():
    t = entry.TABLES[1]
    with pytest.raises(ValueError, match="Company is required"):
        entry.clean(t, {"year": "2025", "source": "x"})
    with pytest.raises(ValueError, match="not a number"):
        entry.clean(t, {"firm": "SAP", "year": "2025", "employees": "many", "source": "x"})
    with pytest.raises(ValueError, match="choose one of DAX, MDAX"):
        entry.clean(t, {"firm": "SAP", "year": "2025", "index": "SDAX", "source": "x"})


def test_a_failing_build_restores_the_file(tmp_path, monkeypatch):
    t = table(tmp_path)
    t.path.write_text("firm,year,index,employees,staff_cost,tsr,source\nA,2025,DAX,,,,r\n")
    before = t.path.read_bytes()

    def broken():
        raise ValueError("Firm-year delivered twice")

    monkeypatch.setattr(entry.panel, "build", broken)
    with pytest.raises(ValueError, match="delivered twice"):
        entry.add([(t, [{"firm": "B", "year": "2025", "source": "report"}])])
    assert t.path.read_bytes() == before


def test_add_and_delete_round_trip(tmp_path, monkeypatch):
    t = table(tmp_path)
    monkeypatch.setattr(entry.panel, "build", lambda: None)
    monkeypatch.setattr(entry, "cached", lambda path, make: make())
    monkeypatch.setattr(entry, "refresh", lambda: None)
    entry.add([(t, [{"firm": "New AG", "year": 2025, "index": "DAX", "source": "report"}])])
    assert entry.rows(t)[0]["firm"] == "New AG"
    entry.delete(t, 0)
    assert entry.rows(t) == []


def test_amounts_in_euro_instead_of_keur_are_flagged():
    row = {"firm": "SAP", "year": "2025", "first_name": "Christian", "last_name": "Klein",
           "role": "CEO", "days": "365", "fixed": "1400000", "source": "test"}
    found = entry.check(row)["findings"]
    assert any(x["field"] == "fixed" and "did you mean 1,400 k€" in x["message"] for x in found)


def test_replay_applies_the_log_once_and_keeps_hand_edits(tmp_path, monkeypatch):
    t = table(tmp_path)
    monkeypatch.setattr(entry, "table", lambda table_id: t)
    t.path.write_text("firm,year,index,employees,staff_cost,tsr,source\nA,2025,DAX,,,,r\nB,2025,,,,,r\n")
    row = lambda firm: {"firm": firm, "year": "2025", "index": "", "employees": "", "staff_cost": "",  # noqa: E731
                        "tsr": "", "source": "hosted"}
    log = [("firm_years", "add", row("C")), ("firm_years", "add", row("D")),
           ("firm_years", "delete", row("D")), ("firm_years", "delete", {**row("A"), "index": "DAX", "source": "r"})]
    (merged,) = entry.merged(log).values()
    assert [r["firm"] for r in merged] == ["B", "C"]
    entry.save_file(t, merged, t.path.read_bytes())
    assert entry.merged(log) == {}  # already applied: the files stay as they are


@pytest.mark.skipif(not os.getenv("TEST_DATABASE_URL"), reason="needs a throwaway Postgres (see test_feedback.py)")
def test_saved_rows_survive_a_deploy(tmp_path, monkeypatch):
    t = table(tmp_path)
    monkeypatch.setenv("DATABASE_URL", os.environ["TEST_DATABASE_URL"])
    monkeypatch.setattr(entry, "table", lambda table_id: t)
    monkeypatch.setattr(entry, "cached", lambda path, make: make())
    monkeypatch.setattr(entry, "refresh", lambda: None)
    with psycopg.connect(os.environ["TEST_DATABASE_URL"]) as db:
        db.execute("DROP TABLE IF EXISTS data_change")
    monkeypatch.setattr(entry.panel, "build", lambda: None)
    entry.add([(t, [{"firm": "New AG", "year": 2025, "source": "report"}])], "boss@example.org")

    def broken():
        raise ValueError("Firm-year delivered twice")

    monkeypatch.setattr(entry.panel, "build", broken)
    with pytest.raises(ValueError):  # a failed build logs nothing
        entry.add([(t, [{"firm": "Other AG", "year": 2025, "source": "report"}])])
    t.path.unlink()  # a deploy replaces the container's files
    entry.replay()
    assert [r["firm"] for r in entry.rows(t)] == ["New AG"]
    with psycopg.connect(os.environ["TEST_DATABASE_URL"]) as db:
        assert db.execute("SELECT by_email FROM data_change").fetchall() == [("boss@example.org",)]
        db.execute("DROP TABLE data_change")  # a server on this database would replay the row
