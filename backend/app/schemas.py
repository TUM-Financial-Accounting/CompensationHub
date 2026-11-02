"""Response models. Amounts are k€, shares are fractions (0–1) unless named `_pct`."""

from pydantic import BaseModel


class Quantiles(BaseModel):
    year: int
    group: str
    p10: float
    p25: float
    median: float
    p75: float
    p90: float
    n: int


class Summary(BaseModel):
    first_year: int
    last_year: int
    n_firms: int
    n_people: int
    n_exec_years: int
    n_firm_years: int
    ceo_median_first: float
    ceo_median_last: float
    female_share_first: float
    female_share_last: float
    pay_ratio_median_last: float
    ceo_pay: list[Quantiles]


class MixRow(BaseModel):
    year: int
    component: str
    share: float


class YearValue(BaseModel):
    year: int
    value: float
    n: int


class Trends(BaseModel):
    levels: list[Quantiles]
    mix: list[MixRow]
    ceo_premium: list[YearValue]
    opt_out_rate: list[YearValue]


class FirmListItem(BaseModel):
    id: str
    name: str
    first_year: int
    last_year: int
    index: str | None
    board_total: float | None
    ceo_name: str | None
    ceo_total: float | None


Value = float | str | bool | None


class Firm(BaseModel):
    id: str
    name: str
    isin: str | None
    industry: str | None     # activity text from the DSW workbooks (2022+)
    naics: str | None        # NAICS 2022 code, data/reference/industries.csv
    naics_title: str | None
    first_year: int
    last_year: int
    attributes: dict[str, Value]  # columns from firm tables (data/raw|reference/tables/)


class FirmYear(BaseModel):
    year: int
    regime: str
    index: str | None
    opt_out: bool
    n_execs: int
    board_total: float
    board_total_incl: float | None
    employees: float | None
    avg_staff_cost: float | None
    tsr: float | None
    sti_esg_share: float | None
    lti_esg_share: float | None
    sti_esg_kind: str | None  # 'target', 'multiplier' or 'target + multiplier'
    lti_esg_kind: str | None
    extra: dict[str, Value]  # columns from firm-year tables (data/raw|reference/tables/)


class ExecYear(BaseModel):
    person_id: str
    name: str
    firm_id: str
    firm: str
    year: int
    role: str
    index: str | None
    days: float | None
    full_year: bool
    female: bool
    fixed: float | None
    sti: float | None
    mti: float | None
    lti: float | None
    other: float | None
    total: float
    pension: float | None
    one_time: float | None


class Kpi(BaseModel):
    name: str
    categories: list[str]


class PlanDesign(BaseModel):
    year: int
    sti_kpis: list[Kpi]
    lt_kpis: list[Kpi]
    sti_cap_pct: float | None
    lti_cap: bool | None


class FirmDetail(BaseModel):
    firm: Firm
    years: list[FirmYear]
    execs: list[ExecYear]
    design: list[PlanDesign]
    dax_ceo_median: list[YearValue]


class Person(BaseModel):
    id: str
    name: str
    female: bool
    birth_year: int | None
    german: bool
    years: list[ExecYear]


class KpiUsage(BaseModel):
    year: int
    plan: str
    category: str
    share: float
    n: int


class KpiCell(BaseModel):
    year: int
    firm_id: str
    firm: str
    plan: str
    category: str
    names: list[str]


class CeoDesign(BaseModel):
    year: int
    firm_id: str
    firm: str
    name: str
    total: float
    pension: float | None
    sti_cap: bool
    sti_cap_pct: float | None
    lti_cap: bool
    max_comp: float | None
    sti_esg_share: float | None
    lti_esg_share: float | None
    sti_esg_kind: str | None  # 'target', 'multiplier' or 'target + multiplier'
    lti_esg_kind: str | None


class CapYear(BaseModel):
    year: int
    n: int                   # DAX CEOs with plan-design data
    sti_capped: int          # … whose annual bonus is capped
    lti_capped: int
    sti_cap_median: float | None  # % of the target bonus


class Design(BaseModel):
    kpi_usage: list[KpiUsage]
    kpi_cells: list[KpiCell]
    ceos: list[CeoDesign]
    caps: list[CapYear]


class DiversityRow(BaseModel):
    year: int
    scope: str
    female_share: float
    non_german_share: float
    median_age: float | None
    n: int


class CeoFirmYear(BaseModel):
    year: int
    firm_id: str
    firm: str
    name: str
    total: float
    avg_staff_cost: float | None
    pay_ratio: float | None
    tsr: float | None
    pay_change: float | None


class HiringRow(BaseModel):
    year: int
    role: str
    external_share: float
    n: int


class Board(BaseModel):
    diversity: list[DiversityRow]
    ceos: list[CeoFirmYear]
    hiring: list[HiringRow]
    pay_ratio_median: list[YearValue]  # median CEO-to-staff pay ratio per year
    tsr_pay_corr: list[YearValue]      # Pearson r of TSR and CEO pay change per year


class Coverage(BaseModel):
    field: str
    year: int
    share: float


class UniverseRow(BaseModel):
    year: int
    index: str
    firms: int
    opt_out: int
    execs: int


class Issue(BaseModel):
    id: str
    kind: str
    title: str
    detail: str
    count: int | None


class Source(BaseModel):
    label: str
    regime: str
    execs: int
    firm_years: int


class Quality(BaseModel):
    coverage: list[Coverage]
    universe: list[UniverseRow]
    sources: list[Source]
    issues: list[Issue]


# --------------------------------------------------------------------------- peer benchmark


class PeerMethod(BaseModel):
    id: str
    family: str              # 'groups', 'industry', 'neighbours' ('baseline' for the reference)
    name: str
    rule: str
    origin: str
    score: str | None        # what a peer's score means (nearest-neighbour definitions)
    coverage: float          # share of benchmarkable executive-years with a result
    n_firms_median: float    # peer firms per executive-year
    fit: float               # median |log(pay ÷ peer median)| on executive-years all methods cover
    pull: float              # slope: next-year log pay change on today's log gap (net of year)
    pull_se: float
    stability: float         # mean year-to-year overlap (Jaccard) of a firm's peer firms
    above_share: float       # share of executive-years with verdict 'above'


class Agreement(BaseModel):
    a: str
    b: str
    spearman: float          # rank correlation of pay ÷ peer median
    same_verdict: float      # share of executive-years with the same verdict


class ConvergenceBin(BaseModel):
    method: str
    gap: float               # median log(pay ÷ peer median) in the decile
    change: float            # mean log pay change to next year, net of the year's mean
    n: int


class PeerYearCount(BaseModel):
    year: int
    robust: int              # CEO-years 'above' under every definition that benchmarks them
    fragile: int             # … under some definitions, not all
    n: int                   # benchmarked CEO-years


class RobustCeo(BaseModel):
    year: int
    firm_id: str
    firm: str
    person_id: str
    name: str
    total: float
    n_methods: int
    ratio_min: float         # lowest pay ÷ peer median across the definitions
    ratio_max: float


class FragilityLine(BaseModel):
    line: float              # verdict line: pay ÷ peer median at or above this
    flagged_any: int         # CEO-years at or above it under at least one definition
    flagged_all: int         # … under every definition that benchmarks them


class PeerOverview(BaseModel):
    methods: list[PeerMethod]
    baseline: PeerMethod     # no selection: every other firm in the year and role
    agreement: list[Agreement]
    convergence: list[ConvergenceBin]
    years: list[int]
    high: float              # verdict 'above' from this multiple of the peer median
    min_peer_firms: int
    n_rows: int              # benchmarkable executive-years (full year, pay ≥ min_pay)
    n_common: int            # … benchmarked by every definition
    min_pay: float
    ceo_flagged_any: int     # CEO-years 'above' under at least one definition
    ceo_flagged_all: int     # … under every definition that benchmarks them
    ceo_by_year: list[PeerYearCount]
    robust_ceos: list[RobustCeo]
    fragility: list[FragilityLine]  # the same count for other verdict lines


class PeerResult(BaseModel):
    method: str
    n_peers: int
    n_firms: int
    p10: float
    p25: float
    peer_median: float
    p75: float
    p90: float
    ratio: float             # pay ÷ peer median
    percentile: float        # share of peers paid less (ties count half)
    verdict: str             # 'above', 'in line' or 'below'
    label: str               # peer group, e.g. 'DAX · board of 6–8'


class PeerVerdict(BaseModel):
    person_id: str
    name: str
    firm_id: str
    firm: str
    total: float
    results: list[PeerResult]
    n_above: int             # definitions with verdict 'above'


class PeerVerdicts(BaseModel):
    year: int
    role: str
    rows: list[PeerVerdict]


class PeerExec(BaseModel):
    person_id: str
    name: str
    firm_id: str
    firm: str
    total: float
    index: str | None
    n_execs: float
    employees: float | None
    naics: str
    naics_title: str
    result: PeerResult | None  # None: fewer than min_peer_firms peer firms


class PeerLink(BaseModel):
    firm_id: str
    peer_firm: str
    score: float | None


class PeerGroup(BaseModel):
    label: str
    n_firms: int
    n_execs: int
    median: float            # median pay of the benchmarked executives in the group


class ClusterSector(BaseModel):
    sector: str
    share: float


class ClusterProfile(BaseModel):
    cluster: int
    name: str
    firm_years: int
    firms: int
    dax_share: float
    board_median: float
    sectors: list[ClusterSector]
    examples: list[str]
    ceo_median: float


class ClusterChoice(BaseModel):
    k: int
    silhouette: float
    coverage: float          # share of CEO-years with enough peer firms in their cluster
    chosen: bool


class Importance(BaseModel):
    feature: str
    importance: float        # relative increase in squared error when shuffled


class ForestFit(BaseModel):
    r2: float                # out-of-firm R² of log pay relative to its year and role
    mdae: float
    mdae_baseline: float
    n: int


class PeerYearSummary(BaseModel):
    n: int                   # benchmarkable executives in the year and role
    n_benchmarked: int       # … with enough peer firms for a result
    n_firms_median: float | None
    above: int
    below: int


class PeerMethodView(BaseModel):
    method: PeerMethod
    year: int
    role: str
    years: list[int]
    summary: PeerYearSummary
    executives: list[PeerExec]
    links: list[PeerLink]
    groups: list[PeerGroup]
    clusters: list[ClusterProfile] | None = None
    cluster_choice: list[ClusterChoice] | None = None
    importance: list[Importance] | None = None
    forest_fit: ForestFit | None = None


class FirmPeerRow(BaseModel):
    year: int
    person_id: str
    name: str
    total: float
    result: PeerResult


# --------------------------------------------------------------------------- pay prediction


class PredictionModel(BaseModel):
    id: str
    family: str              # 'own', 'reference', 'level', 'change'
    name: str
    idea: str
    formula: str
    why: str


class Target(BaseModel):
    id: str
    label: str


class Score(BaseModel):
    model: str
    target: str
    regime: str
    n: int                   # test pairs the model predicts
    coverage: float          # … as a share of all test pairs
    mae: float               # mean absolute error of log values (0.2 ≈ 20 %)
    mdae: float
    mae_ref: float           # the drift baseline on the same pairs
    skill: float             # 1 − mae / mae_ref: above 0 beats the baseline
    band_cover: float | None  # share of actual values inside the 80 % range
    band_width: float | None  # median width of the range (log)


class HorizonScore(BaseModel):
    model: str
    target: str
    regime: str
    h: int
    n: int
    mae: float
    skill: float
    band_cover: float | None


class PaidScore(BaseModel):
    target: str
    regime: str
    n: int
    share_paid: float
    accuracy: float          # logistic model: is the component paid h years later
    accuracy_same: float     # baseline: paid then if paid now


class Seed(BaseModel):
    seed: int
    mae: float


class PredictionOverview(BaseModel):
    models: list[PredictionModel]
    targets: list[Target]
    scorecard: list[Score]
    by_horizon: list[HorizonScore]
    paid: list[PaidScore]
    best: dict[str, str]     # target → model shown on executive pages
    best_rule: str
    band: float
    peer_method: str
    origins: list[int]
    last_year: int
    latest_regime: str
    gap_woman: float         # effect of 'woman' in the demographic variant (fraction)
    gap_german: float
    mlp_seeds: list[Seed]
    coherence: float | None  # median of (sum of component forecasts) ÷ total forecast


class Calibration(BaseModel):
    regime: str
    level: float
    achieved: float | None


class RoleScore(BaseModel):
    regime: str
    role: str
    n: int
    mae: float
    mae_ref: float


class Point(BaseModel):
    regime: str
    h: int
    actual: float
    predicted: float


class Miss(BaseModel):
    person_id: str
    name: str
    firm: str
    year: int
    h: int
    actual: float
    predicted: float
    error: float             # log(actual ÷ predicted)


class Coefficient(BaseModel):
    feature: str
    coef: float              # on log pay: exp(coef) − 1 is the % effect


class FirmEffect(BaseModel):
    firm_id: str
    firm: str
    n: int
    effect: float
    weight: float


class PredictionModelView(BaseModel):
    model: PredictionModel
    target: str
    targets: list[Target]
    scores: list[Score]
    by_horizon: list[HorizonScore]   # this model and the drift baseline
    calibration: list[Calibration]
    by_role: list[RoleScore]
    points: list[Point]
    misses: list[Miss]
    best: dict[str, str]
    coefficients: list[Coefficient] | None = None
    importance: list[Importance] | None = None
    firms: list[FirmEffect] | None = None
    seeds: list[Seed] | None = None


class YearAmount(BaseModel):
    year: int
    value: float | None


class TargetHistory(BaseModel):
    target: str
    years: list[YearAmount]


class ForecastRow(BaseModel):
    target: str
    model: str
    year: int
    h: int
    value: float
    lo: float | None         # 80 % range
    hi: float | None
    source: str | None       # which test years the range comes from


class PaidChance(BaseModel):
    target: str
    year: int
    p: float


class Colleague(BaseModel):
    person_id: str
    name: str
    role: str
    total: float
    ratio_to_ceo: float | None
    is_self: bool


class PeerQuantiles(BaseModel):
    target: str
    value: float | None
    p10: float
    p25: float
    median: float
    p75: float
    p90: float
    n: int
    percentile: float | None


class PeerFirm(BaseModel):
    firm_id: str
    firm: str


class Option(BaseModel):
    id: str
    name: str


class PersonPrediction(BaseModel):
    person_id: str
    name: str
    firm_id: str
    firm: str
    role: str
    year: int
    regime: str
    best: dict[str, str]
    band: float
    history: list[TargetHistory]
    forecasts: list[ForecastRow]
    paid: list[PaidChance]
    board: list[Colleague]
    avg_staff_cost: float | None
    staff_ratio: float | None  # total pay ÷ average staff cost of the firm
    method: str
    methods: list[Option]
    peer_firms: list[PeerFirm]
    peers: list[PeerQuantiles]


class FirmForecast(BaseModel):
    person_id: str
    name: str
    role: str
    year: int
    total: float
    value: float
    lo: float | None
    hi: float | None
    model: str


class WhatIfRow(BaseModel):
    target: str
    now: float
    expected: float          # this executive in `years` years, nothing changed
    changed: float           # … with the changes
    change: float


class WhatIfEffect(BaseModel):
    target: str
    feature: str
    effect: float


class Promotion(BaseModel):
    change: float            # median log pay change observed for this role change
    n: int


class WhatIf(BaseModel):
    person_id: str
    name: str
    firm: str
    role: str
    year: int
    years: int
    growth: float | None
    rows: list[WhatIfRow]
    effects: list[WhatIfEffect]
    promotion: Promotion | None


# --------------------------------------------------------------------------- data entry


class DataColumn(BaseModel):
    name: str
    kind: str                # 'text', 'number', 'integer', 'choice', 'bool', 'firm'
    label: str
    required: bool
    unit: str | None
    options: list[str]
    help: str


class DataTable(BaseModel):
    id: str
    name: str
    file: str
    purpose: str
    columns: list[DataColumn]
    deletable: bool
    rows: list[dict[str, str]]


Cell = str | float | int | bool | None


class TableRows(BaseModel):
    table: str               # a table id from /api/tables
    rows: list[dict[str, Cell]]


class Changes(BaseModel):
    changes: list[TableRows]  # saved together: one panel build, all or nothing


class Saved(BaseModel):
    added: int


class Finding(BaseModel):
    level: str               # 'error', 'warning', 'info', 'ok'
    field: str | None
    message: str


class RowFindings(BaseModel):
    table: str
    row: int                 # position in that table's rows of the request
    findings: list[Finding]


class Document(BaseModel):
    name: str
    data: str                # file content, base64


class Extracted(BaseModel):
    name: str
    text: str                # PDF pages are marked "[page n]"
    pages: int | None
    truncated: bool


# --------------------------------------------------------------------------- assistant


class ChatModel(BaseModel):
    id: str                  # provider:model
    available: bool          # its key is set in backend/.env
    default: bool
    thinking: list[str]      # thinking settings: Gemma ['off', 'on'], Qwen ['off', 'low', 'medium', 'xhigh']; [] none


class ChatSetup(BaseModel):
    models: list[ChatModel]
    examples: list[str]


class ChatMessage(BaseModel):
    role: str                # 'user' or 'assistant'
    content: str


class ChatRequest(BaseModel):
    model: str
    messages: list[ChatMessage]
    thinking: str = "off"    # one of the model's thinking settings
    page: str | None = None  # the dashboard page the user is on, e.g. 'companies/sap'
    draft: list[TableRows] | None = None  # rows proposed earlier, as the user has edited them
