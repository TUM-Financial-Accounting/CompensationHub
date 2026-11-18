import numpy as np
import pandas as pd
import pytest
from fastapi.testclient import TestClient

from app import redflags
from app.main import app
from app.redflags import (FLAG_SHARE, JUMP, PAY_UP, PLANTS, SEVERANCE_CAP, STAT_IDS, STRUCTURE_IDS,
                          fit_structure, folds, median_without_firm, rank_auc)


@pytest.fixture(scope="module")
def fl():
    return redflags.get_flags()


def of(fl, detector: str) -> pd.DataFrame:
    return fl.checks[fl.checks["detector"] == detector]


# --------------------------------------------------------------------------- invariants


def test_rules_flag_exactly_from_their_threshold(fl):
    for detector, line in [("jump", JUMP), ("one_time", SEVERANCE_CAP)]:
        c = of(fl, detector)
        assert (c["flagged"] == (c["score"] > line)).all(), detector
    tsr = of(fl, "tsr")
    assert (tsr.loc[tsr["flagged"], "score"] > PAY_UP).all()


def test_every_flag_has_evidence_and_nothing_else_does(fl):
    c = fl.checks
    assert c.loc[c["flagged"], "evidence"].str.len().gt(20).all()
    assert c.loc[~c["flagged"], "evidence"].isna().all()
    assert fl.firm_flags["evidence"].str.len().gt(20).all()


def test_model_based_detectors_flag_the_set_share_of_each_regime(fl):
    regime = fl.rows["regime"]
    for detector in ["expected", *STRUCTURE_IDS]:
        c = of(fl, detector)
        share = c.groupby(c["row"].map(regime))["flagged"].mean()
        assert share.between(FLAG_SHARE - 0.01, FLAG_SHARE + 0.01).all(), (detector, share)


def test_no_check_twice_on_one_executive_year(fl):
    assert not fl.checks.duplicated(["row", "detector"]).any()


def test_opt_out_only_in_legacy_years(fl):
    assert fl.firm_flags.loc[fl.firm_flags["detector"] == "opt_out", "year"].max() <= 2021  # ARUG II ended it


# --------------------------------------------------------------------------- method


def test_folds_keep_firms_and_regimes_apart():
    o = pd.DataFrame({"firm_id": np.repeat(list("abcdefghij"), 4),
                      "regime": np.tile(["legacy", "legacy", "§162", "§162"], 10)})
    for train, test in folds(o, pd.Series(True, index=o.index)):
        assert not set(o.loc[train, "firm_id"]) & set(o.loc[test, "firm_id"])
        assert o.loc[np.r_[train, test], "regime"].nunique() == 1


def test_a_firm_never_sets_its_own_norm():
    v = pd.Series([1.0, 2.0, 3.0, 100.0, 5.0])
    firm = pd.Series(["a", "b", "c", "c", "d"])
    group = pd.Series(["g", "g", "g", "g", "h"], name="group")
    m = median_without_firm(v, [group], firm)
    assert m.tolist()[:4] == [3.0, 3.0, 1.5, 1.5]  # c's two rows: the median of a and b only
    assert np.isnan(m[4])  # alone in its group: no norm, not judged


def test_every_structure_detector_scores_an_extreme_package_highest():
    rng = np.random.default_rng(0)
    train = rng.normal(size=(400, 4))
    centre, extreme = np.zeros((1, 4)), np.full((1, 4), 6.0)
    for name, score in fit_structure(train).items():
        assert score(extreme)[0] > score(centre)[0], name


def test_rank_auc_is_a_half_when_blind_and_one_when_separated():
    neg = pd.Series(np.arange(100.0))
    regime = pd.Series("legacy", index=neg.index)
    assert rank_auc(neg, neg, regime, regime) == pytest.approx(0.5)
    assert rank_auc(neg + 1000, neg, regime, regime) == 1.0


def test_planted_anomalies_reach_only_the_detectors_that_can_see_them(fl):
    p = fl.planted.set_index(["detector", "kind", "size"])["detected"].sort_index()
    # A persistent pay level leaves the forecast blind: it learns from the executive's own past.
    assert p.loc["forecast", "level"].nunique() == 1
    # A bonus turned into fixed pay leaves total pay unchanged: the reference detectors are blind.
    auc = fl.auc.set_index(["detector", "kind"])["auc"]
    for d in ("peers", "forecast", "expected"):
        assert p.loc[d, "structure"].nunique() == 1
        assert auc[d, "structure"] == pytest.approx(0.5)
    # Bigger jumps are found at least as often by the reference detectors (their score moves by
    # log(size); a structure detector's distance can first shrink for a row paid below the median).
    for d in ("peers", "forecast", "expected"):
        assert p.loc[d, "jump"].is_monotonic_increasing, d
    assert len(fl.planted) == len(STAT_IDS) * sum(map(len, PLANTS.values()))


# --------------------------------------------------------------------------- API


def test_flag_routes(fl):
    client = TestClient(app)  # no lifespan: get_flags() loads the cache
    o = client.get("/api/flags").json()
    assert [d["id"] for d in o["detectors"]] == redflags.DETECTOR_IDS
    year = o["years"][-1]
    rows = client.get(f"/api/flags/executives?year={year}").json()["rows"]
    assert rows and all(r["year"] == year and r["flags"] for r in rows)
    firm = rows[0]["firm_id"]
    assert all(r["firm_id"] == firm for r in client.get(f"/api/flags/executives?firm={firm}").json()["rows"])
    assert client.get("/api/flags/executives").status_code == 422
    assert client.get("/api/flags/executives?firm=no-such-firm").status_code == 404
