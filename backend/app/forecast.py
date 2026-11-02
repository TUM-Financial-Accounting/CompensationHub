"""Pay prediction: fourteen models side by side, for total pay and each pay component.

Every model answers the same question for an executive seen in year t: *what will this pay item
be in year t + h* (h = 1…5) for the same person, firm and role, within one disclosure regime.
They differ in what they look at:

    last, drift, trend                 the executive's own past
    group, peers, board                what comparable executives earn now
    linear, linear_demo, eb            expected pay from characteristics (level models)
    change, change_162, boosting,      the change from the last value (change models)
    forest, mlp

Evaluation is a rolling origin: for each origin year o, models are fit on the pairs whose
target year is ≤ o (all that was known in o) and predict every pair that starts in o. A model's
ranges come from its own errors at earlier origins (online conformal), so their coverage is
measured, not assumed. A component that is zero in a year (no bonus, no pension) is modelled
in two parts: whether it is paid at all (logistic regression), and how much if it is.
Method and results: docs/prediction.md.

    uv run python -m app.forecast    print the scorecard
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from functools import lru_cache
from threading import Lock

import numpy as np
import pandas as pd
from joblib import Parallel, delayed
from sklearn.ensemble import HistGradientBoostingRegressor, RandomForestRegressor
from sklearn.inspection import permutation_importance
from sklearn.linear_model import LinearRegression, LogisticRegression, QuantileRegressor
from sklearn.neural_network import MLPRegressor
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

from .panel import CACHE, Panel, cached, get_panel
from .peers import METHOD_IDS, MIN_PAY, MIN_PEER_FIRMS, Benchmarks, get_benchmarks

TARGETS = {"total": "Total pay", "fixed": "Fixed salary", "sti": "Annual bonus",
           "mti": "Multi-year bonus", "lti": "Share-based pay", "pension": "Pension",
           "other": "Other benefits"}
PAID = ["sti", "mti", "lti", "pension", "other"]  # often zero: modelled in two parts
HORIZONS = range(1, 6)
BAND = 0.8                      # range shown with every prediction
LEVELS = (0.5, 0.8, 0.9)        # ranges checked for calibration
MIN_TRAIN = 1000                # pairs needed before an origin is tested
MIN_ERRORS = 30                 # earlier errors needed before a range is given
MIN_BEST = 100                  # latest-regime test pairs needed to pick the best model there
CURRENT_FIRMS = 10              # a year counts as reported once this many firms are in it
SEED = 0
MLP_SEEDS = (0, 1, 2)

LEVEL_X = ["ceo", "cfo", "dax", "mdax", "board", "tenure", "age", "emp", "has_emp", "s162", "h"]
CHANGE_X = [*LEVEL_X, "lag", "gap"]
DEMO_X = [*LEVEL_X, "female", "german"]
FEATURE_LABEL = {"ceo": "CEO", "cfo": "CFO", "dax": "DAX", "mdax": "MDAX",
                 "board": "Board size (log)", "tenure": "Years on the board",
                 "age": "Age", "emp": "Employees (log, 2022+)", "has_emp": "Employees known",
                 "s162": "§162 regime", "h": "Years ahead", "lag": "Last value (log)",
                 "gap": "Gap to group median (log)", "female": "Woman",
                 "german": "German nationality"}


@dataclass(frozen=True)
class Model:
    id: str
    family: str   # 'own' (own past), 'reference' (comparable executives), 'level', 'change'
    name: str
    idea: str     # what it does
    formula: str
    why: str      # why it is on the page


MODELS = [
    Model("last", "own", "Same as last year",
          "Next year's value is this year's value.", "ŷ(t+h) = y(t)",
          "The random walk: the bar every model has to clear."),
    Model("drift", "own", "Last year + market drift",
          "This year's value, grown by the median yearly change of continuing executives.",
          "log ŷ(t+h) = log y(t) + h·μ",
          "The honest baseline: persistence plus the market."),
    Model("trend", "own", "Own trend",
          "A straight line through the executive's own past years (log scale), extended.",
          "log ŷ(t+h) = log y(t) + h·slope(own years ≤ t)",
          "What 'just extend the trend' gives. Stands in for ARIMA, which needs longer series "
          "than any executive has."),
    Model("group", "reference", "Median of year, role and index",
          "The median of everyone in the same year, role and index, grown by the drift.",
          "log ŷ(t+h) = log median(year, role, index) + h·μ",
          "What 'typical pay' means without any model."),
    Model("peers", "reference", "Peer median",
          "The median of the executive's peers under the peer benchmark's best definition.",
          "log ŷ(t+h) = log peer median(t) + h·μ",
          "Links to the peer benchmark: how far do the peers alone get you?"),
    Model("board", "reference", "Same board",
          "The median of the executive's board colleagues, scaled by the usual ratio between "
          "their role and the rest of the board.",
          "log ŷ(t+h) = log median(colleagues, t) + ratio(role) + h·μ",
          "The 'colleagues' reference: pay inside a board moves together."),
    Model("linear", "level", "Expected pay (linear)",
          "Linear regression of log pay relative to the group median on role, index, board "
          "size, tenure, age, employees and horizon. Ignores the executive's own pay.",
          "log ŷ − log median = β·x",
          "The classic expected-pay model (Core, Holthausen & Larcker 1999)."),
    Model("linear_demo", "level", "Expected pay + gender and nationality",
          "The same regression with gender and German nationality added.",
          "log ŷ − log median = β·x + γ₁·woman + γ₂·German",
          "Shows the gap that remains after the other characteristics. Never used for "
          "predictions on executive pages."),
    Model("eb", "level", "Expected pay + firm effect",
          "The linear model plus the firm's own average deviation from it, shrunk toward zero "
          "the fewer observations the firm has (empirical Bayes).",
          "log ŷ − log median = β·x + w(firm)·ū(firm),  w = n / (n + σ²/τ²)",
          "Partial pooling: a firm's history counts as much as it is reliable."),
    Model("change", "change", "Change model (median regression)",
          "Median regression of the log change on the gap to the group median, role, index, "
          "board size, tenure, age, employees and horizon.",
          "log ŷ(t+h) − log y(t) = β·x  (median, not mean)",
          "The proposed default: persistence, drift and pull toward the group in one model."),
    Model("change_162", "change", "Change model, §162 data only",
          "The change model fitted on 2022+ pairs only.",
          "same as the change model, trained on §162 pairs",
          "Does the 2006–2021 history help or hurt forecasts in the new regime?"),
    Model("boosting", "change", "Gradient boosting",
          "Gradient-boosted trees (scikit-learn's histogram boosting) on the change model's "
          "inputs plus the last value.",
          "log ŷ(t+h) − log y(t) = Σ trees(x)",
          "Answers 'why not LightGBM': same family, measured on the same pairs."),
    Model("forest", "change", "Random forest",
          "A random forest of 100 trees on the change model's inputs.",
          "log ŷ(t+h) − log y(t) = mean of trees(x)",
          "Another flexible learner; the peer benchmark uses one to find similar firms."),
    Model("mlp", "change", "Neural network",
          "A two-layer perceptron (32 and 16 units) on the standardised inputs.",
          "log ŷ(t+h) − log y(t) = MLP(x)",
          "Answers 'why not deep learning'. Run with several seeds to show how much the answer "
          "depends on chance."),
]
MODEL_IDS = [m.id for m in MODELS]
LIVE_MODELS = [m for m in MODEL_IDS if m != "linear_demo"]  # demographics never predict anyone


@dataclass
class Forecasts:
    backtest: pd.DataFrame           # every test prediction with its 80 % range
    calibration: pd.DataFrame        # stated vs. achieved coverage of the ranges
    scorecard: pd.DataFrame          # model × target × regime
    by_horizon: pd.DataFrame         # model × target × regime × h
    paid: pd.DataFrame               # two-part models: is a component paid at all
    best: dict[str, str]             # target → model shown on executive pages
    best_rule: str
    live: pd.DataFrame               # forecasts from the latest year, every model
    live_paid: pd.DataFrame          # probability a component is paid in each future year
    now: pd.DataFrame                # each current firm's latest executives, with features
    errors: pd.DataFrame             # quantiles of past errors per model, target, regime, h
    extras: dict[str, dict]          # per model: what is specific to it (fit on total pay)
    coef: dict[str, dict]            # per target: within-year regression for what-if questions
    drift: dict[str, float]          # per target: yearly drift, latest fit
    promotions: pd.DataFrame         # observed pay change when the role changes
    peer_method: str
    origins: list[int]
    last_year: int


# --------------------------------------------------------------------------- inputs


def observations(p: Panel, b: Benchmarks, peer_method: str) -> pd.DataFrame:
    """Full-year executive-years (pay ≥ MIN_PAY, as in the peer benchmark) with the features
    every model may use and, per target, the log value and its references."""
    e = p.execs[p.execs["full_year"] & (p.execs["total"] >= MIN_PAY)]
    e = (e.merge(p.firm_years[["firm_id", "year", "n_execs", "employees"]],
                 on=["firm_id", "year"], how="left")
         .merge(p.firms[["firm_id", "name"]].rename(columns={"name": "firm"}), on="firm_id"))
    first = p.execs.groupby(["person_id", "firm_id"])["year"].min().rename("first")
    e = e.join(first, on=["person_id", "firm_id"])
    age = e["year"] - e["birth_year"]
    o = pd.DataFrame({
        "person_id": e["person_id"], "name": e["name"], "firm_id": e["firm_id"],
        "firm": e["firm"], "year": e["year"], "role": e["role"], "index": e["index"],
        "regime": e["regime"],
        "ceo": (e["role"] == "CEO") * 1.0, "cfo": (e["role"] == "CFO") * 1.0,
        "dax": (e["index"] == "DAX") * 1.0, "mdax": (e["index"] == "MDAX") * 1.0,
        "board": np.log(e["n_execs"].fillna(e["n_execs"].median())),
        "tenure": (e["year"] - e["first"]).astype(float),
        "age": age.fillna(age.median()),
        "emp": np.log(e["employees"]).fillna(0.0), "has_emp": e["employees"].notna() * 1.0,
        "s162": (e["regime"] == "§162") * 1.0,
        "female": e["female"].astype(float), "german": e["german"].astype(float),
    })
    group = [o["year"], o["role"], o["index"].fillna("none")]
    unit = ["person_id", "firm_id", "role", "regime"]
    links = b.links[b.links["method"] == peer_method]
    links = links[links.groupby(["firm_id", "year", "role"])["peer_firm"].transform("size")
                  >= MIN_PEER_FIRMS]
    for t in TARGETS:
        raw = e[t].to_numpy(dtype=float)
        o[t] = raw
        o[f"{t}_log"] = np.log(np.where(raw > 0, raw, np.nan))
        o[f"{t}_gm"] = o.groupby(group)[f"{t}_log"].transform("median")
        o[f"{t}_col"] = colleague_median(o, f"{t}_log")
        o[f"{t}_peer"] = peer_median(o, links, f"{t}_log")
        o[f"{t}_slope"] = own_slope(o.sort_values("year"), unit, f"{t}_log").reindex(o.index)
    return o.reset_index(drop=True)


def colleague_median(o: pd.DataFrame, col: str) -> np.ndarray:
    """Median log value of the other full-year executives in the same firm-year."""
    v = o[["firm_id", "year", "person_id", col]].dropna().reset_index(names="row")
    pairs = v.merge(v, on=["firm_id", "year"], suffixes=("", "_c"))
    pairs = pairs[pairs["person_id"] != pairs["person_id_c"]]
    return pairs.groupby("row")[f"{col}_c"].median().reindex(o.index).to_numpy()


def peer_median(o: pd.DataFrame, links: pd.DataFrame, col: str) -> np.ndarray:
    """Median log value of the executives at the chosen peer firms (same year and role)."""
    vals = o[["firm_id", "year", "role", col]].dropna().rename(columns={"firm_id": "peer_firm"})
    pool = links[["firm_id", "year", "role", "peer_firm"]].merge(vals, on=["peer_firm", "year", "role"])
    med = pool.groupby(["firm_id", "year", "role"])[col].median()
    return med.reindex(pd.MultiIndex.from_frame(o[["firm_id", "year", "role"]])).to_numpy()


def own_slope(o: pd.DataFrame, unit: list[str], col: str) -> pd.Series:
    """Least-squares slope of the log value on the year over the executive's years up to now
    (same firm, role and regime); undefined with fewer than two years."""
    d = o[unit + ["year", col]].dropna()
    x, y = d["year"].astype(float), d[col]
    g = pd.DataFrame({"n": 1.0, "x": x, "y": y, "xy": x * y, "xx": x * x}).groupby(
        [d[c] for c in unit]).cumsum()
    den = g["n"] * g["xx"] - g["x"] ** 2
    return ((g["n"] * g["xy"] - g["x"] * g["y"]) / den.where(den > 0)).rename(col)


def make_pairs(o: pd.DataFrame) -> pd.DataFrame:
    """Every executive-year with the same person, firm, role and regime h years later."""
    key = ["person_id", "firm_id", "role", "regime"]
    later = o[key + ["year", *TARGETS]]
    return pd.concat([o.merge(later.assign(year=later["year"] - h), on=key + ["year"],
                              suffixes=("", "_y")).assign(h=float(h)) for h in HORIZONS],
                     ignore_index=True)


def target_frame(d: pd.DataFrame, t: str) -> pd.DataFrame:
    """Columns under fixed names for one target: lag, gm, gap, col, peer, slope (and y)."""
    cols = ["person_id", "name", "firm_id", "firm", "year", "role", "regime", *LEVEL_X, *DEMO_X]
    out = d[list(dict.fromkeys(cols))].copy()
    out["lag"] = d[f"{t}_log"]
    out["gm"], out["col"], out["peer"], out["slope"] = (
        d[f"{t}_gm"], d[f"{t}_col"], d[f"{t}_peer"], d[f"{t}_slope"])
    out["gap"] = out["lag"] - out["gm"]
    if f"{t}_y" in d:
        out["y"] = np.log(d[f"{t}_y"].where(d[f"{t}_y"] > 0))
    return out.dropna(subset=["lag", "gm"] + (["y"] if "y" in out else [])).reset_index(drop=True)


# --------------------------------------------------------------------------- models
# Each takes the training pairs (with y) and the pairs to predict, and returns predicted log
# values; NaN where the model has nothing to go on.

Fit = Callable[[pd.DataFrame, pd.DataFrame], np.ndarray]


def drift_of(train: pd.DataFrame) -> float:
    return float(((train["y"] - train["lag"]) / train["h"]).median())


def ols(train: pd.DataFrame, cols: list[str], target: pd.Series) -> LinearRegression:
    return LinearRegression().fit(train[cols], target)


def fit_linear(cols: list[str]) -> Fit:
    def fit(train, test):
        m = ols(train, cols, train["y"] - train["gm"])
        return test["gm"].to_numpy() + m.predict(test[cols])
    return fit


def fit_eb(train: pd.DataFrame, test: pd.DataFrame) -> np.ndarray:
    m = ols(train, LEVEL_X, train["y"] - train["gm"])
    u = (train["y"] - train["gm"] - m.predict(train[LEVEL_X])).groupby(train["firm_id"])
    w = shrinkage(u)
    effect = (u.mean() * w).reindex(test["firm_id"]).fillna(0).to_numpy()
    return test["gm"].to_numpy() + m.predict(test[LEVEL_X]) + effect


def shrinkage(u) -> pd.Series:
    """Empirical-Bayes weight per firm, n / (n + σ²/τ²), with σ² the residual variance within
    firms and τ² the variance of true firm effects (method of moments)."""
    n, mean = u.size(), u.mean()
    within = float(u.var().mul(n - 1).sum() / max(n.sum() - len(n), 1))
    tau2 = max(float(mean.var()) - float((within / n).mean()), 1e-6)
    return n / (n + within / tau2)


def fit_change(model: Callable[[], object], cols: list[str] = CHANGE_X,
               only_162: bool = False) -> Fit:
    def fit(train, test):
        if only_162:
            train = train[train["s162"] == 1]
            if len(train) < 100:
                return np.full(len(test), np.nan)
        m = model().fit(train[cols], train["y"] - train["lag"])
        return test["lag"].to_numpy() + m.predict(test[cols])
    return fit


def median_regression() -> QuantileRegressor:
    return QuantileRegressor(quantile=0.5, alpha=0.0, solver="highs-ipm")


def boosting() -> HistGradientBoostingRegressor:
    return HistGradientBoostingRegressor(max_iter=200, learning_rate=0.05, random_state=SEED)


def forest() -> RandomForestRegressor:
    return RandomForestRegressor(100, min_samples_leaf=20, max_features=0.5, n_jobs=2,
                                 random_state=SEED)


def mlp(seed: int = SEED):
    return lambda: make_pipeline(StandardScaler(), MLPRegressor(
        hidden_layer_sizes=(32, 16), early_stopping=True, max_iter=500, random_state=seed))


def fit_board(train: pd.DataFrame, test: pd.DataFrame) -> np.ndarray:
    ratio = (train["lag"] - train["col"]).groupby(train["role"]).median()
    return (test["col"] + test["role"].map(ratio) + drift_of(train) * test["h"]).to_numpy()


FITS: dict[str, Fit] = {
    "last": lambda train, test: test["lag"].to_numpy(),
    "drift": lambda train, test: (test["lag"] + drift_of(train) * test["h"]).to_numpy(),
    "trend": lambda train, test: (test["lag"] + test["slope"] * test["h"]).to_numpy(),
    "group": lambda train, test: (test["gm"] + drift_of(train) * test["h"]).to_numpy(),
    "peers": lambda train, test: (test["peer"] + drift_of(train) * test["h"]).to_numpy(),
    "board": fit_board,
    "linear": fit_linear(LEVEL_X),
    "linear_demo": fit_linear(DEMO_X),
    "eb": fit_eb,
    "change": fit_change(median_regression),
    "change_162": fit_change(median_regression, only_162=True),
    "boosting": fit_change(boosting),
    "forest": fit_change(forest),
    "mlp": fit_change(mlp()),
}


def paid_model(train: pd.DataFrame):
    cols = [*LEVEL_X, "paid_now"]
    return make_pipeline(StandardScaler(), LogisticRegression(max_iter=1000)).fit(
        train[cols], train["paid"]), cols


# --------------------------------------------------------------------------- evaluation


def origins_of(pairs: pd.DataFrame) -> list[int]:
    """Origin years with enough history to train on and pairs to test."""
    end = pairs["year"] + pairs["h"]
    return [int(o) for o in sorted(pairs["year"].unique()) if (end <= o).sum() >= MIN_TRAIN]


def backtest(d: pd.DataFrame, origins: list[int], target: str) -> pd.DataFrame:
    out = []
    for o in origins:
        train, test = d[d["year"] + d["h"] <= o], d[d["year"] == o]
        if test.empty:
            continue
        keep = test[["person_id", "name", "firm", "year", "h", "role", "regime", "y"]]
        for m in MODEL_IDS:
            out.append(keep.assign(model=m, pred=FITS[m](train, test)))
        if target == "total":
            for seed in MLP_SEEDS[1:]:
                out.append(keep.assign(model=f"mlp@{seed}",
                                       pred=fit_change(mlp(seed))(train, test)))
    bt = pd.concat(out, ignore_index=True).dropna(subset=["pred"])
    bt["target"] = target
    bt["err"] = bt["y"] - bt["pred"]
    return with_ranges(bt)


def with_ranges(bt: pd.DataFrame) -> pd.DataFrame:
    """Online conformal ranges: for a prediction made in origin o, the quantiles of the same
    model's errors (same target and horizon) at origins before o."""
    bt = bt.sort_values("year", ignore_index=True)
    for level in LEVELS:
        bt[f"lo{level:g}"] = bt[f"hi{level:g}"] = np.nan
    for _, g in bt.groupby(["model", "h"]):
        for o in g["year"].unique():
            prior = g.loc[g["year"] < o, "err"]
            if len(prior) < MIN_ERRORS:
                continue
            rows = g.index[g["year"] == o]
            for level in LEVELS:
                lo, hi = prior.quantile([(1 - level) / 2, (1 + level) / 2])
                bt.loc[rows, f"lo{level:g}"] = bt.loc[rows, "pred"] + lo
                bt.loc[rows, f"hi{level:g}"] = bt.loc[rows, "pred"] + hi
    for level in LEVELS:
        inside = bt["y"].between(bt[f"lo{level:g}"], bt[f"hi{level:g}"])
        bt[f"in{level:g}"] = inside.where(bt[f"lo{level:g}"].notna())
    return bt


def scores(bt: pd.DataFrame, n_pairs: pd.DataFrame, by: list[str]) -> pd.DataFrame:
    """Error, paired comparison with the drift baseline on the same pairs, range coverage."""
    ref = bt[bt["model"] == "drift"].set_index(["target", "person_id", "firm", "year", "h"])["err"]
    k = pd.MultiIndex.from_frame(bt[["target", "person_id", "firm", "year", "h"]])
    bt = bt.assign(abs=bt["err"].abs(), ref=ref.reindex(k).abs().to_numpy(),
                   width=bt[f"hi{BAND:g}"] - bt[f"lo{BAND:g}"])
    g = bt.groupby(by)
    out = pd.DataFrame({
        "n": g.size(), "mae": g["abs"].mean(), "mdae": g["abs"].median(),
        "mae_ref": g["ref"].mean(), "band_cover": g[f"in{BAND:g}"].mean(),
        "band_width": g["width"].median(),
    }).reset_index()
    out["skill"] = 1 - out["mae"] / out["mae_ref"]
    if "h" not in by:
        out = out.merge(n_pairs, on=["target", "regime"])
        out["coverage"] = out["n"] / out.pop("n_pairs")
    return out


def calibration(bt: pd.DataFrame) -> pd.DataFrame:
    rows = [bt.groupby(["model", "target", "regime"])[f"in{lv:g}"].mean().rename("achieved")
            .reset_index().assign(level=lv) for lv in LEVELS]
    return pd.concat(rows, ignore_index=True)


def compact(bt: pd.DataFrame) -> pd.DataFrame:
    lo, hi = f"lo{BAND:g}", f"hi{BAND:g}"
    cols = ["target", "model", "person_id", "name", "firm", "role", "regime"]
    out = bt[[*cols, "year", "h", "y", "pred", lo, hi]].astype(
        {**dict.fromkeys(cols, "category"), "year": "int16", "h": "int8", "y": "float32",
         "pred": "float32", lo: "float32", hi: "float32"})
    return out.rename(columns={lo: "lo", hi: "hi"})


def choose_best(score: pd.DataFrame, latest: str) -> tuple[dict[str, str], str]:
    rule = (f"Lowest mean error on the {latest} test pairs among models that predict at least "
            f"half of them (on all test pairs if there are fewer than {MIN_BEST}); the "
            "demographic variant is never chosen.")
    best = {}
    for t in TARGETS:
        s = score[(score["target"] == t) & (score["model"].isin(MODEL_IDS))
                  & (score["model"] != "linear_demo")]
        here = s[s["regime"] == latest]
        if here["n"].max() < MIN_BEST:
            here = s.groupby("model").apply(
                lambda g: pd.Series({"mae": np.average(g["mae"], weights=g["n"]),
                                     "coverage": np.average(g["coverage"], weights=g["n"])}),
                include_groups=False).reset_index()
        best[t] = here[here["coverage"] >= 0.5].sort_values("mae")["model"].iloc[0]
    return best, rule


def error_quantiles(bt: pd.DataFrame) -> pd.DataFrame:
    """Quantiles of past errors per model, target, regime and horizon, for live ranges."""
    qs = [(1 - lv) / 2 for lv in LEVELS] + [(1 + lv) / 2 for lv in LEVELS]
    g = bt.groupby(["model", "target", "regime", "h"])["err"]
    out = g.quantile(qs).unstack()
    out.columns = [f"q{q:g}" for q in qs]
    return out.assign(n=g.size()).reset_index()


def paid_backtest(pairs: pd.DataFrame, origins: list[int]) -> tuple[pd.DataFrame, list]:
    rows, live_models = [], []
    for t in PAID:
        d = pairs.dropna(subset=[t, f"{t}_y"]).assign(paid_now=lambda x: (x[t] > 0) * 1.0,
                                                      paid=lambda x: x[f"{t}_y"] > 0)
        for o in origins:
            train, test = d[d["year"] + d["h"] <= o], d[d["year"] == o]
            if test.empty or train["paid"].nunique() < 2:
                continue
            m, cols = paid_model(train)
            rows.append(test[["regime"]].assign(
                target=t, hit=m.predict(test[cols]) == test["paid"],
                same=(test["paid_now"] == 1) == test["paid"], paid=test["paid"]))
        live_models.append((t, *paid_model(d)))
    r = pd.concat(rows).groupby(["target", "regime"])
    return pd.DataFrame({"n": r.size(), "share_paid": r["paid"].mean(), "accuracy": r["hit"].mean(),
                         "accuracy_same": r["same"].mean()}).reset_index(), live_models


# --------------------------------------------------------------------------- live forecasts


def current(o: pd.DataFrame) -> pd.DataFrame:
    """Each firm's executives in the firm's latest year, for firms still reporting in the
    latest year that at least CURRENT_FIRMS firms report: a firm whose next report was added by
    hand moves ahead without pushing the others out, and firms that left the index drop out."""
    firms = o.groupby("year")["firm_id"].nunique()
    reporting = firms[firms >= CURRENT_FIRMS].index.max()
    latest = o.groupby("firm_id")["year"].transform("max")
    return o[(o["year"] == latest) & (latest >= reporting)]


def live_rows(now: pd.DataFrame) -> pd.DataFrame:
    """The current executives, once per horizon."""
    return pd.concat([now.assign(h=float(h)) for h in HORIZONS], ignore_index=True)


def live_forecasts(now: pd.DataFrame, pairs: pd.DataFrame, errors: pd.DataFrame) -> pd.DataFrame:
    now = live_rows(now)
    regime = now["regime"].mode()[0]
    out = []
    for t in TARGETS:
        train, test = target_frame(pairs, t), target_frame(now, t)
        for m in LIVE_MODELS:
            pred = FITS[m](train, test)
            out.append(test[["person_id", "firm_id", "role", "year", "h"]].assign(
                target=t, model=m, pred=pred))
    live = pd.concat(out, ignore_index=True).dropna(subset=["pred"])
    q = errors_for(errors, regime)
    live = live.merge(q, on=["model", "target", "h"], how="left")
    live["value"] = np.exp(live["pred"])
    for lv in LEVELS:
        live[f"lo{lv:g}"] = np.exp(live["pred"] + live[f"q{(1 - lv) / 2:g}"])
        live[f"hi{lv:g}"] = np.exp(live["pred"] + live[f"q{(1 + lv) / 2:g}"])
    live["year"] = (live["year"] + live["h"]).astype(int)
    return live.drop(columns=[c for c in live if c.startswith("q")] + ["pred"])


def errors_for(errors: pd.DataFrame, regime: str) -> pd.DataFrame:
    """Error quantiles of the regime where it has enough test pairs, else of all regimes; the
    `source` column says which."""
    own = errors[(errors["regime"] == regime) & (errors["n"] >= MIN_ERRORS)].assign(source=regime)
    key = ["model", "target", "h"]
    qs = [c for c in errors if c.startswith("q")]
    g = errors[qs].mul(errors["n"], axis=0).groupby([errors[k] for k in key])
    pooled = g.sum().div(errors.groupby(key)["n"].sum(), axis=0).reset_index().assign(source="all years")
    rest = pooled.merge(own[key], on=key, how="left", indicator=True)
    rest = rest[rest["_merge"] == "left_only"].drop(columns="_merge")
    return pd.concat([own.drop(columns=["regime", "n"]), rest], ignore_index=True)


def live_paid(now: pd.DataFrame, models: list) -> pd.DataFrame:
    now = live_rows(now)
    out = []
    for t, m, cols in models:
        d = now.dropna(subset=[t]).assign(paid_now=lambda x: (x[t] > 0) * 1.0)
        out.append(d[["person_id", "firm_id", "h"]].assign(
            target=t, year=(d["year"] + d["h"]).astype(int), p=m.predict_proba(d[cols])[:, 1]))
    return pd.concat(out, ignore_index=True)


# --------------------------------------------------------------------------- model details


def details(d: pd.DataFrame) -> dict[str, dict]:
    """What is specific to each model, fitted on every total-pay pair."""
    def coefficients(cols, target):
        m = ols(d, cols, target)
        return [{"feature": FEATURE_LABEL[c], "coef": float(b)} for c, b in zip(cols, m.coef_)]

    level = d["y"] - d["gm"]
    change = median_regression().fit(d[CHANGE_X], d["y"] - d["lag"])
    m = ols(d, LEVEL_X, level)
    u = (level - m.predict(d[LEVEL_X])).groupby(d["firm_id"])
    w = shrinkage(u)
    firms = pd.DataFrame({"n": u.size(), "effect": u.mean(), "weight": w}).reset_index()
    firms = firms.merge(d.drop_duplicates("firm_id")[["firm_id", "firm"]], on="firm_id")
    sample = d.sample(min(len(d), 2000), random_state=SEED)
    importance = {}
    for name, make in (("boosting", boosting), ("forest", forest)):
        fitted = make().fit(d[CHANGE_X], d["y"] - d["lag"])
        imp = permutation_importance(fitted, sample[CHANGE_X], sample["y"] - sample["lag"],
                                     n_repeats=3, random_state=SEED)
        importance[name] = sorted(({"feature": FEATURE_LABEL[c], "importance": float(v)}
                                   for c, v in zip(CHANGE_X, imp.importances_mean)),
                                  key=lambda r: -r["importance"])
    return {
        "linear": {"coefficients": coefficients(LEVEL_X, level)},
        "linear_demo": {"coefficients": coefficients(DEMO_X, level)},
        "change": {"coefficients": [{"feature": FEATURE_LABEL[c], "coef": float(b)}
                                    for c, b in zip(CHANGE_X, change.coef_)]},
        "eb": {"firms": firms.sort_values("n", ascending=False).to_dict("records")},
        "boosting": {"importance": importance["boosting"]},
        "forest": {"importance": importance["forest"]},
    }


WHAT_IF_X = ["ceo", "cfo", "dax", "mdax", "board", "tenure", "age", "emp", "has_emp"]


def what_if_models(o: pd.DataFrame) -> dict[str, dict]:
    """Per target, log value on role, index, board size, tenure, age and employees, compared
    within the same year (year fixed effects), for what-if questions."""
    out = {}
    for t in TARGETS:
        d = o.dropna(subset=[f"{t}_log"])
        x = pd.concat([d[WHAT_IF_X], pd.get_dummies(d["year"], prefix="y", dtype=float)], axis=1)
        m = LinearRegression().fit(x, d[f"{t}_log"])
        out[t] = dict(zip(WHAT_IF_X, map(float, m.coef_)))
    return out


def promotions(o: pd.DataFrame) -> pd.DataFrame:
    """Same person and firm in consecutive years of one regime, in a different role."""
    nxt = o[["person_id", "firm_id", "regime", "year", "role", "total"]].assign(
        year=lambda x: x["year"] - 1)
    m = o.merge(nxt, on=["person_id", "firm_id", "regime", "year"], suffixes=("", "_next"))
    m = m[m["role"] != m["role_next"]]
    g = np.log(m["total_next"] / m["total"]).groupby([m["role"], m["role_next"]])
    return pd.DataFrame({"change": g.median(), "n": g.size()}).reset_index().rename(
        columns={"role": "from", "role_next": "to"})


def what_if(f: Forecasts, person_id: str, years: int = 1, role: str | None = None,
            index: str | None = None, board: int | None = None, employees: float | None = None,
            growth: float | None = None) -> dict | None:
    """Change some characteristics of an executive of the latest year and keep what is specific
    to them: y' = y · exp(f(x') − f(x)) · growth^years, with f the within-year regression of each
    target and growth the market drift unless given. Associations, not causal effects."""
    now = f.now[f.now["person_id"] == person_id]
    if now.empty:
        return None
    x = now.iloc[0]
    new = {"ceo": float(role == "CEO"), "cfo": float(role == "CFO")} if role else {}
    if index:
        new |= {"dax": float(index == "DAX"), "mdax": float(index == "MDAX")}
    if board:
        new["board"] = float(np.log(board))
    if employees:
        new |= {"emp": float(np.log(employees)), "has_emp": 1.0}
    rows, effects = [], []
    for t, coef in f.coef.items():
        if not x[t] > 0:
            continue
        parts = {k: coef[k] * (v - x[k]) for k, v in new.items() if v != x[k]}
        g = np.log1p(growth) if growth is not None else f.drift[t]
        expected = float(x[t] * np.exp(g * years))
        changed = float(expected * np.exp(sum(parts.values())))
        rows.append({"target": t, "now": float(x[t]), "expected": expected, "changed": changed,
                     "change": changed / expected - 1})
        effects += [{"target": t, "feature": FEATURE_LABEL[k], "effect": float(np.expm1(v))}
                    for k, v in parts.items()]
    promo = f.promotions[(f.promotions["from"] == x["role"]) & (f.promotions["to"] == role)]
    return {"person_id": person_id, "name": x["name"], "firm": x["firm"], "role": x["role"],
            "year": int(x["year"]), "years": years, "growth": growth, "rows": rows,
            "effects": effects,
            "promotion": promo.iloc[0].to_dict() if role and role != x["role"] and len(promo) else None}


# --------------------------------------------------------------------------- entry point


def best_peer_method(b: Benchmarks) -> str:
    return str(b.scorecard.set_index("method").loc[METHOD_IDS, "fit"].idxmin())


def compute(p: Panel, b: Benchmarks) -> Forecasts:
    method = best_peer_method(b)
    o = observations(p, b, method)
    pairs = make_pairs(o)
    origins = origins_of(pairs)
    frames = {t: target_frame(pairs, t) for t in TARGETS}
    bt = pd.concat(Parallel(n_jobs=-1)(delayed(backtest)(frames[t], origins, t) for t in TARGETS),
                   ignore_index=True)
    n_pairs = pd.concat([f[f["year"].isin(origins)].groupby("regime").size()
                         .rename("n_pairs").reset_index().assign(target=t)
                         for t, f in frames.items()])
    main = bt[bt["model"].isin(MODEL_IDS)]
    scorecard = scores(main, n_pairs, ["model", "target", "regime"])
    by_h = scores(main, n_pairs, ["model", "target", "regime", "h"])
    now = current(o)
    last = int(o["year"].max())
    latest = o.loc[o["year"] == last, "regime"].iloc[0]
    best, rule = choose_best(scorecard, latest)
    paid, paid_models = paid_backtest(pairs, origins)
    errors = error_quantiles(main)
    extras = details(frames["total"])
    seeds = bt[bt["model"].str.startswith("mlp") & (bt["target"] == "total")]
    extras["mlp"] = {"seeds": [{"seed": int(s.split("@")[1]) if "@" in s else SEED,
                                "mae": float(g["err"].abs().mean())}
                               for s, g in seeds.groupby("model")]}
    return Forecasts(
        backtest=compact(main), calibration=calibration(main), scorecard=scorecard,
        by_horizon=by_h, paid=paid, best=best, best_rule=rule,
        live=live_forecasts(now, pairs, errors), live_paid=live_paid(now, paid_models),
        now=now, errors=errors, extras=extras,
        coef=what_if_models(o), drift={t: drift_of(f) for t, f in frames.items()},
        promotions=promotions(o), peer_method=method, origins=origins, last_year=last)


_lock = Lock()


@lru_cache(maxsize=1)
def _forecasts() -> Forecasts:
    return cached(CACHE.with_name("forecasts.pkl"), lambda: compute(get_panel(), get_benchmarks()))


def get_forecasts() -> Forecasts:
    """Computed once (about two minutes) and cached next to the panel until data or code change.
    The lock keeps a request from starting a second computation while the first one runs."""
    with _lock:
        return _forecasts()


if __name__ == "__main__":
    import time

    from app import forecast  # the importable module, so the cache pickles app.forecast classes

    start = time.time()
    f = forecast.get_forecasts()
    pd.set_option("display.width", 200, "display.max_rows", 200)
    cols = ["model", "regime", "n", "coverage", "mae", "skill", "band_cover", "band_width"]
    for t in TARGETS:
        print(f"\n{TARGETS[t]} (best: {f.best[t]})")
        s = f.scorecard[f.scorecard["target"] == t].sort_values(["regime", "mae"])
        print(s[cols].round(3).to_string(index=False))
    print(f.paid.round(3).to_string(index=False))
    print(f"origins {f.origins}, peer definition {f.peer_method}, {time.time() - start:.0f} s")
