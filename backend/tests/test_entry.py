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
