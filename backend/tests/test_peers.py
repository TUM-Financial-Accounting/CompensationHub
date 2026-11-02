import numpy as np
import pandas as pd
import pytest

from app import peers
from app.peers import (BASELINE, HIGH, METHOD_IDS, MIN_PEER_FIRMS, group_peers, industry_peers,
                       nearest, peer_stats, sector_of)


@pytest.fixture(scope="module")
def bench():
    return peers.get_benchmarks()


def toy(firms: dict[str, tuple[float, str]], year=2020, role="CEO") -> pd.DataFrame:
    """One executive per firm: {firm: (pay, naics)}; firm features as candidates() makes them."""
    rows = pd.DataFrame([{"person_id": f"p-{f}", "name": f, "firm_id": f, "firm": f, "year": year,
                          "role": role, "index": "DAX", "size_class": "DAX", "total": pay,
                          "n_execs": 5.0, "employees": np.nan, "naics": naics}
                         for f, (pay, naics) in firms.items()])
    rows["sector"] = sector_of(rows["naics"])
    rows["naics3"], rows["naics4"] = rows["naics"].str[:3], rows["naics"].str[:4]
    return rows


# --------------------------------------------------------------------------- invariants


def test_peers_are_other_firms_in_the_same_year_and_role(bench):
    links = bench.links
    assert not (links["firm_id"] == links["peer_firm"]).any()
    present = set(zip(bench.rows["firm_id"], bench.rows["year"], bench.rows["role"]))
    assert all(k in present for k in zip(links["peer_firm"], links["year"], links["role"]))


def test_no_result_below_the_minimum_number_of_peer_firms(bench):
    assert (bench.results["n_firms"] >= MIN_PEER_FIRMS).all()


def test_ratio_and_verdict_follow_the_peer_median(bench):
    r = bench.results.join(bench.rows["total"])
    assert np.allclose(r["ratio"], r["total"] / r["peer_median"])
    assert (r.loc[r["ratio"] >= HIGH, "verdict"] == "above").all()
    assert (r.loc[r["ratio"] <= 1 / HIGH, "verdict"] == "below").all()


def test_industry_peers_share_the_naics_level_they_name(bench):
    rows = bench.rows.drop_duplicates("firm_id").set_index("firm_id")
    res = bench.results[bench.results["method"] == "industry"].join(bench.rows[peers.UNIT])
    links = bench.links[bench.links["method"] == "industry"].merge(
        res[peers.UNIT + ["label"]].drop_duplicates(), on=peers.UNIT)
    code = links["label"].str.split(" ").str[1]  # 'NAICS 336 Transportation … (subsector)'
    for col in ("naics", "sector"):
        links[col] = links["peer_firm"].map(rows[col])
    assert all(n.startswith(c) or s == c for n, s, c in zip(links["naics"], links["sector"], code))


def test_fragility_at_the_verdict_line_matches_the_verdicts(bench):
    f = peers.fragility(bench.rows, bench.results).set_index("line")
    res = bench.results[bench.results["method"].isin(METHOD_IDS)]
    ceo = res[res.index.isin(bench.rows.index[bench.rows["role"] == "CEO"])]
    flagged = (ceo["verdict"] == "above").groupby(level="row").sum()
    assert f.loc[HIGH, "flagged_any"] == (flagged > 0).sum()
    assert (f["flagged_all"] <= f["flagged_any"]).all()


def test_scorecard_covers_every_definition_and_the_baseline(bench):
    assert list(bench.scorecard["method"]) == [BASELINE, *METHOD_IDS]
    assert bench.scorecard["coverage"].between(0, 1).all()
    assert (bench.scorecard.set_index("method").loc[["industry_size", "knn", "forest"],
                                                     "coverage"] == 1).all()


# --------------------------------------------------------------------------- building blocks


def test_peer_stats_on_a_toy_group():
    rows = toy({f: (pay, "325412") for f, pay in zip("abcdef", [100, 200, 300, 400, 500, 600])})
    out = peer_stats(rows, group_peers(rows, pd.Series(0, index=rows.index),
                                       pd.Series("all", index=rows.index)))
    by_firm = out.join(rows["firm_id"]).set_index("firm_id")
    assert by_firm.loc["a", "peer_median"] == 400 and by_firm.loc["a", "verdict"] == "below"
    assert by_firm.loc["f", "ratio"] == 2 and by_firm.loc["f", "percentile"] == 1
    assert by_firm.loc["c", "percentile"] == pytest.approx(0.4)
    assert by_firm.loc["c", "verdict"] == "in line"


def test_too_few_peer_firms_give_no_result():
    rows = toy({f: (100.0, "325412") for f in "abcde"})  # four peers each
    assert peer_stats(rows, group_peers(rows, pd.Series(0, index=rows.index),
                                        pd.Series("all", index=rows.index))).empty


def test_nearest_keeps_every_firm_tied_with_the_kth():
    n = peers.K_FIRMS + 4
    closeness = np.zeros((n, n))
    closeness[0, 1:4] = 2.0  # three clear neighbours, then n - 4 firms tied
    i, j = nearest(np.arange(n), closeness)
    assert sorted(j[i == 0]) == list(range(1, n))
    assert 0 not in j[i == 0]


def test_industry_widens_from_group_to_subsector_and_stops_at_sector():
    firms = {**{f"pharma{k}": (1000.0, "325412") for k in range(6)},      # one industry group
             "cars": (1000.0, "336110"),                                     # alone in 3361 …
             **{f"parts{k}": (1000.0, "336390") for k in range(5)},        # … but not in 336
             "bank": (1000.0, "522110")}                                     # alone in sector 52
    labels = industry_peers(toy(firms)).drop_duplicates("firm_id").set_index("firm_id")["label"]
    assert labels["pharma0"].endswith("(industry group)")
    assert labels["cars"].startswith("NAICS 336 ") and labels["cars"].endswith("(subsector)")
    assert "bank" not in labels.index


def test_sector_codes_span_combined_ranges():
    assert list(sector_of(pd.Series(["325412", "445110", "492110", "522110"]))) == [
        "31-33", "44-45", "48-49", "52"]
