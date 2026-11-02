import numpy as np
import pandas as pd
import pytest

from app import forecast
from app.forecast import MODEL_IDS, TARGETS, make_pairs, with_ranges


@pytest.fixture(scope="module")
def f():
    return forecast.get_forecasts()


def test_pairs_stay_within_person_firm_role_and_regime():
    o = pd.DataFrame({"person_id": "a", "firm_id": "x", "role": "CEO",
                      "regime": ["legacy", "legacy", "§162"], "year": [2020, 2021, 2022],
                      **{t: [1.0, 2.0, 3.0] for t in TARGETS}})
    pairs = make_pairs(o)
    assert set(zip(pairs["year"], pairs["h"])) == {(2020, 1.0)}


def test_ranges_use_only_errors_from_earlier_origins():
    years = np.repeat([2010, 2011, 2012], 40)
    err = np.where(years == 2010, 1.0, 5.0)  # later errors are huge
    bt = pd.DataFrame({"model": "m", "h": 1.0, "year": years, "pred": 0.0, "y": err, "err": err})
    out = with_ranges(bt)
    assert out.loc[out["year"] == 2010, "lo0.8"].isna().all()  # nothing earlier to learn from
    assert out.loc[out["year"] == 2011, "hi0.8"].eq(1.0).all()
    assert out.loc[out["year"] == 2012, "hi0.8"].eq(5.0).all()


def test_scorecard_is_paired_with_the_drift_baseline(f):
    s = f.scorecard
    assert np.allclose(s.loc[s["model"] == "drift", "skill"], 0)
    assert (s["coverage"] <= 1 + 1e-9).all()
    assert set(f.best.values()) <= set(MODEL_IDS) - {"linear_demo"}


def test_a_hand_entered_year_moves_one_firm_ahead_and_firms_that_left_drop_out():
    o = pd.DataFrame({"firm_id": [*"abcdefghijk"] * 2 + ["a", "z"],
                      "year": [2024] * 11 + [2023] * 11 + [2025, 2023]})
    now = forecast.current(o)
    assert set(zip(now["firm_id"], now["year"])) == {("a", 2025), *((x, 2024) for x in "bcdefghijk")}


def test_live_forecasts_start_after_the_latest_year_and_widen_with_the_horizon(f):
    live = f.live[(f.live["model"] == "drift") & (f.live["target"] == "total")]
    assert live["year"].min() == f.last_year + 1
    width = (np.log(live["hi0.8"]) - np.log(live["lo0.8"])).groupby(live["h"]).median()
    assert width.is_monotonic_increasing


def test_promotion_to_ceo_raises_expected_pay(f):
    cfo = f.now[f.now["role"] == "CFO"].iloc[0]
    out = forecast.what_if(f, cfo["person_id"], role="CEO")
    total = next(r for r in out["rows"] if r["target"] == "total")
    assert total["changed"] > total["expected"]
