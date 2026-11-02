"""Peer benchmark: six ways to choose an executive's peers, and how much the verdict depends on it.

Every definition answers the same question for one full-year executive in one year: *which
executives in the same role at other firms are comparable?* All of them

- compare like with like: same year (so never across the 2021/22 disclosure break) and same role
  (CEO with CEOs, CFO with CFOs, other members with other members),
- never use the executive's own firm,
- pick peer *firms* and use every full-year executive in that role at those firms as a peer,
- give no result with fewer than MIN_PEER_FIRMS peer firms.

They differ in how the peer firms are picked:

    size           same index and board-size tercile (FairPay; the original plan's "rules")
    cluster        same K-means cluster of firm-years (ProxyEngine's "shadow peers")
    industry       same NAICS industry, widened 4-digit → 3-digit → sector until 5 firms
    industry_size  ISS-style: 10 firms inside a size band, industry widened step by step
    knn            the 10 nearest firms by Gower distance over industry and size (Fin1)
    forest         the 10 firms a random forest of pay treats as most alike (learned similarity)

Firm size is known only through the index listing and board size for all years, plus employees
from 2022 (docs/data.md); "size" below always means these proxies. Methodology and results:
docs/peers.md.

    uv run python -m app.peers    print the scorecard
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from functools import lru_cache

import numpy as np
import pandas as pd
from sklearn.cluster import KMeans
from sklearn.ensemble import RandomForestRegressor
from sklearn.metrics import silhouette_score
from sklearn.model_selection import GroupKFold

from . import reference
from .panel import CACHE, Panel, cached, get_panel

MIN_PEER_FIRMS = 5  # no benchmark below this (original plan: "no result below 5 peers")
K_FIRMS = 10        # peer firms for the nearest-neighbour definitions
EMPLOYEE_BAND = 2.5  # ISS size band: peers with 0.4–2.5× the employees (where known) …
BOARD_BAND = 2       # … otherwise the same index and a board within two members
MIN_PAY = 100       # k€; full-year pay below this is symbolic (founders such as Zalando's
                    # co-CEOs): neither benchmarked nor used as a peer
HIGH = 1.5          # verdict "above peers" from 1.5 × the peer median, "below" up to 1 / 1.5
FRAGILITY_LINES = (1.25, 1.5, 2.0, 2.5, 3.0)  # verdict lines for the robustness check
N_CLUSTERS = 8      # K-means; the cluster view shows silhouette and coverage for 4–12
CLUSTER_KS = range(4, 13)
TREES, LEAF, FOLDS = 300, 30, 5  # forest size, min. executive-years per leaf, firm folds
SEED = 0


@dataclass(frozen=True)
class Method:
    id: str
    family: str  # how peers are found: 'groups' (a partition of firms), 'industry' (NAICS
                 # first) or 'neighbours' (the most similar firms)
    name: str
    rule: str    # how peers are chosen
    origin: str  # where the idea comes from
    score: str | None = None  # meaning of a peer's score; None for group definitions


METHODS = [
    Method("size", "groups", "Index & board size",
           "Firms in the same index (DAX, MDAX or none) whose board size falls in the same tercile "
           "of that index and year.",
           "FairPay Radar (hackathon) and the original plan's rule-based definition."),
    Method("cluster", "groups", "Clusters (K-means)",
           f"Firms in the same of {N_CLUSTERS} K-means clusters of firm-years, formed from index, "
           "board size and NAICS sector.",
           "ProxyEngine's 'shadow peers' (hackathon): groups found in the data, not set by hand."),
    Method("industry", "industry", "Industry (NAICS)",
           "Firms in the same NAICS 2022 industry group (4-digit). With fewer than five such firms "
           "the subsector (3-digit) is used, then the sector; below that there is no result.",
           "Industry peers as in ECIS and ExComp (hackathon), but with an official classification "
           "instead of a hand-typed map and without falling back to 'all firms'."),
    Method("industry_size", "industry", "Industry & size (ISS-style)",
           "Ten firms of similar size (0.4–2.5× the employees where known, before 2022 the same "
           "index and a board within two members), taken from the same NAICS industry group "
           "first, then the subsector, the sector and any industry; closest in size first. If "
           "fewer than ten firms are that size, the nearest others fill up, industry first.",
           "ISS peer-group methodology (size band, then industry widened step by step) and the "
           "horizontal comparison of §87 AktG and DCGK G.3, which name industry, size and "
           "country.",
           "NAICS levels shared (3 = same industry group)"),
    Method("knn", "neighbours", "Nearest neighbours (Gower)",
           "The ten firms with the smallest Gower distance: an equal-weight average of the "
           "differences in industry (how many NAICS levels are shared), index, board size and, "
           "from 2022, employees.",
           "Fin1 (hackathon); Gower (1971) distance for mixed numeric and categorical data.",
           "Similarity (1 − Gower distance)"),
    Method("forest", "neighbours", "Learned similarity (random forest)",
           "The ten firms that a random forest predicting pay from role, index, board size, "
           "employees and industry most often puts in the same leaf as the executive's firm. "
           "The forest that scores a firm is trained without that firm.",
           "Random-forest proximity (Breiman 2001); machine-learning peer weights as in "
           "Geertsema & Lu (2023), Journal of Accounting Research.",
           "Share of trees that put both firms in the same leaf"),
]
METHOD_IDS = [m.id for m in METHODS]
BASELINE = "all"  # scorecard reference: every other firm in the year and role is a peer


@dataclass
class Benchmarks:
    rows: pd.DataFrame          # benchmarkable executive-years with firm features; index = row id
    links: pd.DataFrame         # method, firm_id, year, role, peer_firm, score
    results: pd.DataFrame       # index row; method, peer stats, ratio, verdict, label
    n_common: int               # executive-years benchmarked by every definition
    scorecard: pd.DataFrame     # per method and baseline: coverage, fit, pull, stability
    agreement: pd.DataFrame     # method pairs: rank correlation and verdict agreement
    convergence: pd.DataFrame   # binned gap at t against the pay change to t+1, per method
    clusters: pd.DataFrame      # cluster profiles
    cluster_choice: pd.DataFrame  # silhouette and CEO coverage for each K tried
    importance: pd.DataFrame    # forest: increase in error when a feature group is shuffled
    forest_fit: dict            # forest: out-of-firm accuracy


# --------------------------------------------------------------------------- inputs


def sector_of(codes: pd.Series) -> pd.Series:
    """NAICS sector of six-digit codes. Manufacturing, retail and transport span several
    two-digit codes ('31-33'); the spans come from the official list."""
    spans = {}
    for code in reference.naics_titles():
        if "-" in code:
            lo, hi = map(int, code.split("-"))
            spans.update({str(d): code for d in range(lo, hi + 1)})
    two = codes.str[:2]
    return two.map(spans).fillna(two)


def candidates(p: Panel) -> pd.DataFrame:
    """Benchmarkable executive-years (full year, pay ≥ MIN_PAY) with the firm features the
    definitions use. The row position is the key used everywhere below."""
    e = p.execs[p.execs["full_year"] & (p.execs["total"] >= MIN_PAY)]
    rows = (e[["person_id", "name", "firm_id", "year", "role", "index", "total", "regime"]]
            .merge(p.firm_years[["firm_id", "year", "n_execs", "employees"]],
                   on=["firm_id", "year"])
            .merge(p.firms[["firm_id", "name", "naics"]].rename(columns={"name": "firm"}),
                   on="firm_id"))
    rows["sector"] = sector_of(rows["naics"])
    rows["naics3"] = rows["naics"].str[:3]
    rows["naics4"] = rows["naics"].str[:4]
    rows["size_class"] = rows["index"].fillna("no index")
    return rows.sort_values(["year", "role", "firm_id", "person_id"], ignore_index=True)


FIRM_COLUMNS = ["firm_id", "firm", "year", "index", "size_class", "n_execs", "employees", "naics",
                "naics4", "naics3", "sector"]


def firm_years(rows: pd.DataFrame) -> pd.DataFrame:
    """One row per firm-year among `rows` (all executives of a firm-year share its features)."""
    return rows[FIRM_COLUMNS].drop_duplicates(["firm_id", "year"]).reset_index(drop=True)


# --------------------------------------------------------------------------- definitions
# Each returns the chosen peer firms: firm_id, year, role, peer_firm, score (higher = more
# similar; 1 for group definitions) and label (shown as "peer group").

UNIT = ["firm_id", "year", "role"]  # peers are chosen per firm, year and role
PEER_COLUMNS = [*UNIT, "peer_firm", "score", "label"]


def group_peers(rows: pd.DataFrame, key: pd.Series, label: pd.Series) -> pd.DataFrame:
    """Peers = every other firm with the same `key` in the same year and role."""
    g = rows[UNIT].assign(key=key.to_numpy(), label=label.to_numpy()).drop_duplicates(UNIT)
    pairs = g.merge(g[["firm_id", "year", "role", "key"]].rename(columns={"firm_id": "peer_firm"}),
                    on=["year", "role", "key"])
    return pairs[pairs["firm_id"] != pairs["peer_firm"]].assign(score=1.0)[PEER_COLUMNS]


def size_peers(rows: pd.DataFrame) -> pd.DataFrame:
    fy = firm_years(rows)

    def tercile(board: pd.Series) -> pd.Series:  # equal board sizes always share a tercile
        if board.nunique() < 2:
            return pd.Series(0, index=board.index)
        return pd.qcut(board, 3, labels=False, duplicates="drop")

    fy["tercile"] = fy.groupby(["year", "size_class"])["n_execs"].transform(tercile)
    span = fy.groupby(["year", "size_class", "tercile"])["n_execs"].agg(["min", "max"])
    fy = fy.join(span, on=["year", "size_class", "tercile"])
    fy["label"] = [f"{c} · board of {lo:.0f}" + ("" if lo == hi else f"–{hi:.0f}")
                   for c, lo, hi in zip(fy["size_class"], fy["min"], fy["max"])]
    r = rows.merge(fy[["firm_id", "year", "tercile", "label"]], on=["firm_id", "year"])
    return group_peers(r, r["size_class"] + "/" + r["tercile"].astype(str), r["label"])


INDUSTRY_LEVELS = [("naics4", "industry group"), ("naics3", "subsector"), ("sector", "sector")]


def industry_peers(rows: pd.DataFrame) -> pd.DataFrame:
    """Finest NAICS level with at least MIN_PEER_FIRMS other firms in the same year and role."""
    titles = reference.naics_titles()
    fy = rows[UNIT + [c for c, _ in INDUSTRY_LEVELS]].drop_duplicates(UNIT)
    out, todo = [], fy
    for col, level in INDUSTRY_LEVELS:
        pairs = todo.merge(fy[["firm_id", "year", "role", col]].rename(
            columns={"firm_id": "peer_firm"}), on=["year", "role", col])
        pairs = pairs[pairs["firm_id"] != pairs["peer_firm"]]
        pairs = pairs[pairs.groupby(UNIT)["peer_firm"].transform("size") >= MIN_PEER_FIRMS]
        out.append(pairs.assign(score=1.0, label=pairs[col].map(
            lambda c: f"NAICS {c} {titles[c]} ({level})"))[PEER_COLUMNS])
        done = pd.MultiIndex.from_frame(pairs[UNIT])
        todo = todo[~pd.MultiIndex.from_frame(todo[UNIT]).isin(done)]
    return pd.concat(out, ignore_index=True)


def industry_depth(fy: pd.DataFrame, a: np.ndarray, b: np.ndarray) -> np.ndarray:
    """NAICS levels two firms share: 3 = same industry group, 2 = same subsector, 1 = same
    sector, 0 = different sectors."""
    return sum((fy[col].to_numpy()[a] == fy[col].to_numpy()[b]).astype(float)
               for col, _ in INDUSTRY_LEVELS)


def size_parts(fy: pd.DataFrame, a: np.ndarray, b: np.ndarray) -> list[np.ndarray]:
    """Size differences in [0, 1]: index (0/1) and the range-normalised gap in log board size
    and log employees. NaN where either firm lacks the value (employees before 2022)."""
    parts = [(fy["size_class"].to_numpy()[a] != fy["size_class"].to_numpy()[b]).astype(float)]
    for col in ("n_execs", "employees"):
        v = np.log(fy[col].to_numpy(dtype=float))
        span = np.nanmax(v) - np.nanmin(v) if np.isfinite(v).any() else 0.0
        parts.append(np.abs(v[a] - v[b]) / span if span > 0 else np.full(len(a), np.nan))
    return parts


def gower(fy: pd.DataFrame, a: np.ndarray, b: np.ndarray) -> np.ndarray:
    """Gower distance: equal-weight mean of per-feature differences in [0, 1]. A feature missing
    for either firm is left out of that pair's mean (standard Gower)."""
    parts = [1 - industry_depth(fy, a, b) / 3, *size_parts(fy, a, b)]
    return np.nanmean(np.vstack(parts), axis=0)


def size_band(fy: pd.DataFrame, a: np.ndarray, b: np.ndarray) -> np.ndarray:
    """ISS-style size band: employees within 0.4–2.5× where both firms report them (2022+);
    otherwise the same index and a board within two members."""
    emp = fy["employees"].to_numpy(dtype=float)
    ratio = emp[b] / emp[a]
    board = fy["n_execs"].to_numpy(dtype=float)
    same_class = fy["size_class"].to_numpy()[a] == fy["size_class"].to_numpy()[b]
    by_board = same_class & (np.abs(board[a] - board[b]) <= BOARD_BAND)
    return np.where(np.isfinite(ratio), (ratio >= 1 / EMPLOYEE_BAND) & (ratio <= EMPLOYEE_BAND),
                    by_board)


def iss_order(fy: pd.DataFrame, a: np.ndarray, b: np.ndarray) -> np.ndarray:
    """ISS order as a distance: firms inside the size band first; within it the closest NAICS
    level (4-digit, then 3-digit, sector, any); ties by size difference. Encoded as
    4 · outside band + unshared NAICS levels (0–3) + size difference (< 1)."""
    size = np.nanmean(np.vstack(size_parts(fy, a, b)), axis=0)
    return 4 * ~size_band(fy, a, b) + 3 - industry_depth(fy, a, b) + 0.999 * size


def nearest(firms: np.ndarray, closeness: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """For each row of a firms × firms closeness matrix (higher = closer; the diagonal is
    ignored): positions of the K_FIRMS closest firms *plus every firm tied with the K-th*, so
    that no peer is chosen by alphabetical accident. Returns (row, column) position pairs."""
    if len(firms) < 2:
        return np.array([], dtype=int), np.array([], dtype=int)
    c = closeness.astype(float).copy()
    np.fill_diagonal(c, -np.inf)
    kth = -np.sort(-c, axis=1)[:, min(K_FIRMS, len(firms) - 1) - 1]
    return np.nonzero(c >= kth[:, None])


def nearest_peers(rows: pd.DataFrame, distance: Callable) -> pd.DataFrame:
    """The K_FIRMS closest other firms (with ties) having an executive in the same year and
    role. Returns the distance as `d`; callers turn it into a display score."""
    out = []
    for (year, role), r in rows.groupby(["year", "role"]):
        fy = firm_years(r)
        n = len(fy)
        a, b = np.divmod(np.arange(n * n), n)
        d = distance(fy, a, b).reshape(n, n)
        i, j = nearest(fy["firm_id"].to_numpy(), -d)
        out.append(pd.DataFrame({"firm_id": fy["firm_id"].to_numpy()[i], "year": year,
                                 "role": role, "peer_firm": fy["firm_id"].to_numpy()[j],
                                 "d": d[i, j]}))
    peers = pd.concat(out, ignore_index=True)
    return peers.assign(label=same_sector_label(rows, peers))


def same_sector_label(rows: pd.DataFrame, peers: pd.DataFrame) -> pd.Series:
    """Label for chosen-not-grouped peers: how many share the executive's NAICS sector."""
    sector = rows.drop_duplicates("firm_id").set_index("firm_id")["sector"]
    same = peers["firm_id"].map(sector) == peers["peer_firm"].map(sector)
    g = same.groupby([peers[c] for c in UNIT])
    return (g.transform("sum").astype(int).astype(str) + " of " + g.transform("size").astype(str)
            + " peer firms in the same sector")


def industry_size_peers(rows: pd.DataFrame) -> pd.DataFrame:
    peers = nearest_peers(rows, iss_order)
    return peers.assign(score=3 - np.floor(peers.pop("d")) % 4)  # score = NAICS levels shared


def knn_peers(rows: pd.DataFrame) -> pd.DataFrame:
    peers = nearest_peers(rows, gower)
    return peers.assign(score=1 - peers.pop("d"))  # score = similarity, 1 − Gower distance


def cluster_features(fy: pd.DataFrame) -> np.ndarray:
    """Standardised DAX flag and log board size, plus the NAICS sector one-hot (0/1)."""
    num = pd.DataFrame({"dax": (fy["index"] == "DAX").astype(float),
                        "board": np.log(fy["n_execs"].clip(lower=1))})
    num = (num - num.mean()) / num.std()
    return np.hstack([num.to_numpy(), pd.get_dummies(fy["sector"]).to_numpy(dtype=float)])


def cluster_peers(rows: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """K-means on firm-years pooled over all years, so a cluster means the same thing every
    year; peers are the other firms of the cluster in the same year."""
    fy = firm_years(rows)
    x = cluster_features(fy)
    raw = KMeans(N_CLUSTERS, n_init=20, random_state=SEED).fit_predict(x)
    # Number clusters from large to small firms (DAX share, then median board size).
    size = fy.groupby(raw).agg(dax=("index", lambda s: (s == "DAX").mean()),
                               board=("n_execs", "median"))
    rank = size.sort_values(["dax", "board"], ascending=False).index
    fy["cluster"] = pd.Series(range(1, len(rank) + 1), index=rank).reindex(raw).to_numpy()
    names = cluster_names(fy)
    r = rows.merge(fy[["firm_id", "year", "cluster"]], on=["firm_id", "year"])
    peers = group_peers(r, r["cluster"], r["cluster"].map(names))
    return peers, cluster_profile(fy, rows, names), cluster_choice(x, fy, rows)


def cluster_names(fy: pd.DataFrame) -> dict[int, str]:
    """'C3 · DAX · board 5 · Manufacturing': number, majority index, median board size and the
    sectors with at least a quarter of the cluster's firm-years."""
    titles = reference.naics_titles()
    names = {}
    for c, g in fy.groupby("cluster"):
        top = g["sector"].value_counts(normalize=True)
        sectors = [titles[s] for s, share in top.items() if share >= 0.25][:2] or ["mixed"]
        names[c] = (f"C{c} · {g['size_class'].mode().iat[0]} · board "
                    f"{g['n_execs'].median():.0f} · " + " & ".join(sectors))
    return names


def cluster_profile(fy: pd.DataFrame, rows: pd.DataFrame, names: dict[int, str]) -> pd.DataFrame:
    titles = reference.naics_titles()
    ceo = rows[rows["role"] == "CEO"].merge(fy[["firm_id", "year", "cluster"]],
                                            on=["firm_id", "year"])
    out = []
    for c, g in fy.groupby("cluster"):
        top = g["sector"].value_counts(normalize=True).head(3)
        out.append({
            "cluster": int(c), "name": names[c], "firm_years": len(g),
            "firms": g["firm_id"].nunique(), "dax_share": (g["index"] == "DAX").mean(),
            "board_median": g["n_execs"].median(),
            "sectors": [{"sector": titles[s], "share": share} for s, share in top.items()],
            "examples": g["firm"].value_counts().index[:6].tolist(),  # most years in the cluster
            "ceo_median": ceo.loc[ceo["cluster"] == c, "total"].median(),
        })
    return pd.DataFrame(out)


def cluster_choice(x: np.ndarray, fy: pd.DataFrame, rows: pd.DataFrame) -> pd.DataFrame:
    """For each K: silhouette (how well separated the clusters are) and the share of CEO-years
    with at least MIN_PEER_FIRMS peer firms in their cluster (how usable they are)."""
    ceo = rows.loc[rows["role"] == "CEO", ["firm_id", "year"]].drop_duplicates()
    out = []
    for k in CLUSTER_KS:
        lab = KMeans(k, n_init=20, random_state=SEED).fit_predict(x)
        c = ceo.merge(fy[["firm_id", "year"]].assign(cluster=lab), on=["firm_id", "year"])
        others = c.groupby(["year", "cluster"])["firm_id"].transform("size") - 1
        out.append({"k": k, "silhouette": silhouette_score(x, lab, random_state=SEED),
                    "coverage": (others >= MIN_PEER_FIRMS).mean(), "chosen": k == N_CLUSTERS})
    return pd.DataFrame(out)


# Feature groups of the forest, by column-name prefix (for the permutation importance).
FOREST_GROUPS = {"Role": "role_", "Index": "index_", "Board size": "board",
                 "Employees": "employees", "Industry": "naics_"}


def forest_features(rows: pd.DataFrame) -> pd.DataFrame:
    return pd.concat([
        pd.get_dummies(rows["role"], prefix="role_"),
        pd.get_dummies(rows["size_class"], prefix="index_"),
        np.log(rows["n_execs"]).rename("board"),
        np.log(rows["employees"]).rename("employees"),  # 2022+ only; the trees route gaps
        pd.get_dummies(rows["sector"], prefix="naics_sector"),
        pd.get_dummies(rows["naics3"], prefix="naics_3"),
    ], axis=1).astype(float)


def forest_peers(rows: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame, dict]:
    """Learned similarity, cross-fitted by firm: the forest that chooses a firm's peers never
    saw that firm's pay.

    Target: log pay minus the median log pay of its year and role, so the trees split on what
    makes pay differ between firms, not on inflation or role. Two firm-years are as similar as
    the share of trees that put them in the same leaf (Breiman's proximity).
    """
    x = forest_features(rows)
    log_pay = np.log(rows["total"])
    y = log_pay - log_pay.groupby([rows["year"], rows["role"]]).transform("median")
    fold = np.zeros(len(rows), dtype=int)
    leaves, oof = [], np.zeros(len(rows))
    shuffled = {g: np.zeros(len(rows)) for g in FOREST_GROUPS}
    rng = np.random.default_rng(SEED)
    for k, (train, test) in enumerate(GroupKFold(FOLDS).split(x, y, groups=rows["firm_id"])):
        rf = RandomForestRegressor(TREES, min_samples_leaf=LEAF, max_features=0.33, n_jobs=-1,
                                   random_state=SEED).fit(x.iloc[train], y.iloc[train])
        fold[test] = k
        leaves.append(rf.apply(x))  # every row, so test firms can be compared with all others
        oof[test] = rf.predict(x.iloc[test])
        # Permutation importance on unseen firms. Values are shuffled within each year, so a
        # feature that exists only from 2022 (employees) is never moved into earlier years.
        years = rows["year"].to_numpy()[test]
        within = np.arange(len(test))
        for year in np.unique(years):
            same = np.flatnonzero(years == year)
            within[same] = rng.permutation(same)
        for group, prefix in FOREST_GROUPS.items():
            xs = x.iloc[test].copy()
            cols = [c for c in x.columns if c.startswith(prefix)]
            xs[cols] = xs[cols].to_numpy()[within]
            shuffled[group][test] = rf.predict(xs)

    out = []
    for (year, role), r in rows.groupby(["year", "role"]):
        first = r.drop_duplicates("firm_id")  # same firm, year and role → same features
        pos, firms = first.index.to_numpy(), first["firm_id"].to_numpy()
        # Row i holds firm i's proximities, measured with the forest of firm i's fold.
        proximity = np.vstack([
            (leaves[fold[row]][pos] == leaves[fold[row]][row]).mean(axis=1) for row in pos])
        i, j = nearest(firms, proximity)
        out.append(pd.DataFrame({"firm_id": firms[i], "year": year, "role": role,
                                 "peer_firm": firms[j], "score": proximity[i, j]}))
    peers = pd.concat(out, ignore_index=True)
    peers = peers.assign(label=same_sector_label(rows, peers))

    sse = float(((y - oof) ** 2).sum())
    importance = pd.DataFrame([
        {"feature": g, "importance": float(((y - pred) ** 2).sum()) / sse - 1}
        for g, pred in shuffled.items()]).sort_values("importance", ascending=False)
    fit = {"r2": 1 - sse / float(((y - y.mean()) ** 2).sum()),
           "mdae": float(np.median(np.abs(y - oof))),
           "mdae_baseline": float(np.median(np.abs(y))), "n": len(rows)}
    return peers, importance, fit


def baseline_peers(rows: pd.DataFrame) -> pd.DataFrame:
    """No selection at all: every other firm in the same year and role."""
    return group_peers(rows, pd.Series(0, index=rows.index),
                       pd.Series("all other firms", index=rows.index))


# --------------------------------------------------------------------------- statistics


def peer_stats(rows: pd.DataFrame, peers: pd.DataFrame) -> pd.DataFrame:
    """Per executive-year: peer count, peer pay quantiles, pay ÷ peer median, percentile rank
    (share of peers paid less, ties half), verdict and peer-group label. Units with too few peer
    firms get no row."""
    peers = peers[peers.groupby(UNIT)["peer_firm"].transform("size") >= MIN_PEER_FIRMS]
    pay = rows[["firm_id", "year", "role", "total"]].rename(columns={"firm_id": "peer_firm"})
    pool = peers[UNIT + ["peer_firm"]].merge(pay, on=["peer_firm", "year", "role"])
    g = pool.groupby(UNIT)["total"]
    unit = pd.DataFrame({
        "n_peers": g.size(), "n_firms": pool.groupby(UNIT)["peer_firm"].nunique(),
        **{f"p{q}": g.quantile(q / 100) for q in (10, 25, 50, 75, 90)},
    }).rename(columns={"p50": "peer_median"}).reset_index()
    unit = unit.merge(peers.drop_duplicates(UNIT)[UNIT + ["label"]], on=UNIT)

    own = rows[UNIT + ["total"]].reset_index(names="row")
    out = own.merge(unit, on=UNIT)
    cmp = own.merge(pool.rename(columns={"total": "peer_total"}), on=UNIT)
    cmp["below"] = (cmp["peer_total"] < cmp["total"]) + 0.5 * (cmp["peer_total"] == cmp["total"])
    out = out.merge(cmp.groupby("row")["below"].mean().rename("percentile"), on="row")
    out["ratio"] = out["total"] / out["peer_median"]
    out["verdict"] = np.select([out["ratio"] >= HIGH, out["ratio"] <= 1 / HIGH],
                               ["above", "below"], "in line")
    return out.drop(columns=UNIT + ["total"]).set_index("row").sort_index()


# --------------------------------------------------------------------------- evaluation


def common_rows(results: pd.DataFrame) -> pd.Index:
    """Executive-years benchmarked by every definition (fair ground for comparing them)."""
    per_row = results[results["method"].isin(METHOD_IDS)].groupby(level="row")["method"].nunique()
    return per_row.index[per_row == len(METHOD_IDS)]


def next_year(rows: pd.DataFrame) -> pd.DataFrame:
    """Each executive-year with the same person, firm and role full-year in the next year, within
    one disclosure regime: log pay change and the row id of year t."""
    key = ["person_id", "firm_id", "role"]
    nxt = rows[key + ["year", "total", "regime"]].assign(year=lambda d: d["year"] - 1)
    pairs = rows[key + ["year", "total", "regime"]].reset_index(names="row").merge(
        nxt, on=key + ["year"], suffixes=("", "_next"))
    pairs = pairs[pairs["regime"] == pairs["regime_next"]]
    return pairs.assign(change=np.log(pairs["total_next"] / pairs["total"]))[
        ["row", "year", "firm_id", "change"]].set_index("row")


def pull(gap: pd.Series, change: pd.DataFrame) -> dict:
    """OLS slope of next-year log pay change on today's log gap to the peer median, both net of
    year means (market-wide raises). −0.3 means 30 % of the gap closes within a year. The
    standard error is clustered by firm: a firm's executives and years are not independent."""
    d = change.join(gap.rename("gap"), how="inner")
    firm = d.pop("firm_id")
    d = d - d.groupby("year").transform("mean").assign(year=0)
    sxx = (d["gap"] ** 2).sum()
    beta = (d["gap"] * d["change"]).sum() / sxx
    score = (d["gap"] * (d["change"] - beta * d["gap"])).groupby(firm).sum()
    return {"pull": beta, "pull_se": float(np.sqrt((score ** 2).sum()) / sxx), "pull_n": len(d)}


def stability(rows: pd.DataFrame, links: pd.DataFrame) -> float:
    """Mean Jaccard overlap of a firm's peer firms (per role) between consecutive years in one
    regime: how much a peer group would change from one remuneration report to the next."""
    regime = rows.drop_duplicates(["year"]).set_index("year")["regime"]
    sets = links.groupby(UNIT)["peer_firm"].agg(frozenset)
    nxt = sets.rename(index=lambda y: y - 1, level="year")
    both = sets.to_frame("a").join(nxt.rename("b"), how="inner")
    years = both.index.get_level_values("year")
    both = both[regime.reindex(years).to_numpy() == regime.reindex(years + 1).to_numpy()]
    return float(np.mean([len(a & b) / len(a | b) for a, b in zip(both["a"], both["b"])]))


def evaluate(rows: pd.DataFrame, links: pd.DataFrame, results: pd.DataFrame
             ) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    common = common_rows(results)
    change = next_year(rows)
    gap = np.log(results["ratio"]).rename("gap")
    score, bins = [], []
    for m in [BASELINE, *METHOD_IDS]:
        r = results[results["method"] == m]
        g = gap[results["method"] == m]
        on_common = g.reindex(common)
        score.append({
            "method": m, "coverage": len(r) / len(rows),
            "n_firms_median": r["n_firms"].median(), "n_peers_median": r["n_peers"].median(),
            "fit": float(np.median(np.abs(on_common))),
            "above_share": (r["verdict"] == "above").mean(),
            "stability": stability(rows, links[links["method"] == m]),
            **pull(on_common, change),
        })
        d = change.join(on_common, how="inner")
        d["bin"] = pd.qcut(d["gap"], 10, labels=False)
        net = d["change"] - d.groupby("year")["change"].transform("mean")
        b = d.assign(net=net).groupby("bin").agg(gap=("gap", "median"), change=("net", "mean"),
                                                 n=("net", "size"))
        bins.append(b.reset_index(drop=True).assign(method=m))
    scorecard = pd.DataFrame(score)

    wide = gap.to_frame().assign(method=results["method"]).reset_index().pivot(
        index="row", columns="method", values="gap").reindex(common)
    verdict = results.reset_index().pivot(index="row", columns="method",
                                          values="verdict").reindex(common)
    rank = wide[METHOD_IDS].corr(method="spearman")
    pairs = [{"a": a, "b": b, "spearman": rank.loc[a, b],
              "same_verdict": (verdict[a] == verdict[b]).mean()}
             for a in METHOD_IDS for b in METHOD_IDS]
    return scorecard, pd.DataFrame(pairs), pd.concat(bins, ignore_index=True)


def fragility(rows: pd.DataFrame, results: pd.DataFrame, role: str = "CEO") -> pd.DataFrame:
    """For several verdict lines: executive-years at or above the line under at least one
    definition, and under every definition that benchmarks them. Shows whether "the verdict
    depends on the definition" is an artefact of the 1.5× line."""
    res = results[results["method"].isin(METHOD_IDS)
                  & results.index.isin(rows.index[rows["role"] == role])]
    out = []
    for line in FRAGILITY_LINES:
        above = (res["ratio"] >= line).groupby(level="row").agg(["sum", "size"])
        flagged = above["sum"] > 0
        out.append({"line": line, "flagged_any": int(flagged.sum()),
                    "flagged_all": int((flagged & (above["sum"] == above["size"])).sum())})
    return pd.DataFrame(out)


# --------------------------------------------------------------------------- entry point


def compute(p: Panel) -> Benchmarks:
    rows = candidates(p)
    clusters, cluster_profiles, choice = cluster_peers(rows)
    forest, importance, fit = forest_peers(rows)
    chosen = {"size": size_peers(rows), "industry": industry_peers(rows),
              "industry_size": industry_size_peers(rows), "knn": knn_peers(rows),
              "cluster": clusters, "forest": forest, BASELINE: baseline_peers(rows)}
    links = pd.concat([df.assign(method=m) for m, df in chosen.items()], ignore_index=True)
    results = pd.concat([peer_stats(rows, df).assign(method=m) for m, df in chosen.items()])
    scorecard, agreement, convergence = evaluate(rows, links, results)
    return Benchmarks(rows, links.drop(columns="label"), results, len(common_rows(results)),
                      scorecard, agreement, convergence, cluster_profiles, choice, importance, fit)


@lru_cache(maxsize=1)
def get_benchmarks() -> Benchmarks:
    """Computed once (about 20 s) and cached next to the panel until data or code change."""
    return cached(CACHE.with_name("benchmarks.pkl"), lambda: compute(get_panel()))


if __name__ == "__main__":
    import time

    from app import peers  # the importable module, so the cache pickles app.peers classes

    start = time.time()
    b = peers.get_benchmarks()
    pd.set_option("display.width", 200)
    print(b.scorecard.round(3).to_string(index=False))
    print(f"forest: {b.forest_fit}")
    print(b.importance.round(3).to_string(index=False))
    print(b.cluster_choice.round(3).to_string(index=False))
    print(f"{time.time() - start:.1f} s")
