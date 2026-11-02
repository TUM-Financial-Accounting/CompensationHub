import { useCallback, useEffect, useState } from 'react'

// Mirrors backend/app/schemas.py. Amounts in k€, shares as fractions 0–1.

export type Role = 'CEO' | 'CFO' | 'Member'
export type Scope = 'dax' | 'all'

export interface Quantiles {
  year: number
  group: string
  p10: number
  p25: number
  median: number
  p75: number
  p90: number
  n: number
}

export interface YearValue { year: number; value: number; n: number }

export interface Summary {
  first_year: number
  last_year: number
  n_firms: number
  n_people: number
  n_exec_years: number
  n_firm_years: number
  ceo_median_first: number
  ceo_median_last: number
  female_share_first: number
  female_share_last: number
  pay_ratio_median_last: number
  ceo_pay: Quantiles[]
}

export interface Trends {
  levels: Quantiles[]
  mix: { year: number; component: Component; share: number }[]
  ceo_premium: YearValue[]
  opt_out_rate: YearValue[]
}

export interface FirmListItem {
  id: string
  name: string
  first_year: number
  last_year: number
  index: string | null
  board_total: number | null
  ceo_name: string | null
  ceo_total: number | null
}

/** Values from attribute tables in data/raw/tables/ or data/reference/tables/. */
export type Extra = Record<string, string | number | boolean | null>

export interface FirmYear {
  year: number
  regime: string
  index: string | null
  opt_out: boolean
  n_execs: number
  board_total: number
  board_total_incl: number | null
  employees: number | null
  avg_staff_cost: number | null
  tsr: number | null
  sti_esg_share: number | null
  lti_esg_share: number | null
  sti_esg_kind: EsgKind | null
  lti_esg_kind: EsgKind | null
  extra: Extra
}

export interface ExecYear {
  person_id: string
  name: string
  firm_id: string
  firm: string
  year: number
  role: Role
  index: string | null
  days: number | null
  full_year: boolean
  female: boolean
  fixed: number | null
  sti: number | null
  mti: number | null
  lti: number | null
  other: number | null
  total: number
  pension: number | null
  one_time: number | null
}

export interface Kpi { name: string; categories: string[] }

export interface FirmDetail {
  firm: {
    id: string
    name: string
    isin: string | null
    industry: string | null
    naics: string | null
    naics_title: string | null
    first_year: number
    last_year: number
    attributes: Extra
  }
  years: FirmYear[]
  execs: ExecYear[]
  design: { year: number; sti_kpis: Kpi[]; lt_kpis: Kpi[]; sti_cap_pct: number | null; lti_cap: boolean | null }[]
  dax_ceo_median: YearValue[]
}

export interface Person {
  id: string
  name: string
  female: boolean
  birth_year: number | null
  german: boolean
  years: ExecYear[]
}

export interface Design {
  kpi_usage: { year: number; plan: Plan; category: string; share: number; n: number }[]
  kpi_cells: { year: number; firm_id: string; firm: string; plan: Plan; category: string; names: string[] }[]
  ceos: {
    year: number
    firm_id: string
    firm: string
    name: string
    total: number
    pension: number | null
    sti_cap: boolean
    sti_cap_pct: number | null
    lti_cap: boolean
    max_comp: number | null
    sti_esg_share: number | null
    lti_esg_share: number | null
    sti_esg_kind: EsgKind | null
    lti_esg_kind: EsgKind | null
  }[]
  caps: { year: number; n: number; sti_capped: number; lti_capped: number; sti_cap_median: number | null }[]
}
export type Plan = 'STI' | 'Long-term'
/** How ESG enters a plan: a weighted target, a multiplier on the payout, or both. */
export type EsgKind = 'target' | 'multiplier' | 'target + multiplier'

export interface Board {
  diversity: { year: number; scope: Scope; female_share: number; non_german_share: number; median_age: number | null; n: number }[]
  ceos: {
    year: number
    firm_id: string
    firm: string
    name: string
    total: number
    avg_staff_cost: number | null
    pay_ratio: number | null
    tsr: number | null
    pay_change: number | null
  }[]
  hiring: { year: number; role: 'Board' | 'CEO'; external_share: number; n: number }[]
  pay_ratio_median: YearValue[] // median CEO-to-staff pay ratio per year
  tsr_pay_corr: YearValue[] // Pearson r of TSR and CEO pay change per year
}

export interface Issue { id: string; kind: 'fixed' | 'decide' | 'note'; title: string; detail: string; count: number | null }

export interface Quality {
  coverage: { field: string; year: number; share: number }[]
  universe: { year: number; index: string; firms: number; opt_out: number; execs: number }[]
  sources: { label: string; regime: string; execs: number; firm_years: number }[]
  issues: Issue[]
}

// ------------------------------------------------------------------ peer benchmark

/** How a definition finds peers: a partition of firms, NAICS industry first, or the most similar firms. */
export type PeerFamily = 'groups' | 'industry' | 'neighbours' | 'baseline'
export type Verdict = 'above' | 'in line' | 'below'

export interface PeerMethod {
  id: string
  family: PeerFamily
  name: string
  rule: string
  origin: string
  score: string | null // meaning of a peer's score (nearest-neighbour definitions)
  coverage: number // share of benchmarkable executive-years with a result
  n_firms_median: number
  fit: number // median |log(pay ÷ peer median)| on executive-years every definition covers
  pull: number // next-year log pay change per unit of log gap, net of the year
  pull_se: number
  stability: number // year-to-year Jaccard overlap of a firm's peer firms
  above_share: number
}

export interface PeerOverview {
  methods: PeerMethod[]
  baseline: PeerMethod
  agreement: { a: string; b: string; spearman: number; same_verdict: number }[]
  convergence: { method: string; gap: number; change: number; n: number }[]
  years: number[]
  high: number // verdict 'above' from this multiple of the peer median ('below' up to 1 / high)
  min_peer_firms: number
  min_pay: number
  n_rows: number
  n_common: number
  ceo_flagged_any: number
  ceo_flagged_all: number
  /** CEO-years 'above' under every definition that benchmarks them (robust) or only some (fragile). */
  ceo_by_year: { year: number; robust: number; fragile: number; n: number }[]
  robust_ceos: { year: number; firm_id: string; firm: string; person_id: string; name: string; total: number; n_methods: number; ratio_min: number; ratio_max: number }[]
  /** The robust/fragile count for other verdict lines (pay ÷ peer median at or above `line`). */
  fragility: { line: number; flagged_any: number; flagged_all: number }[]
}

export interface PeerResult {
  method: string
  n_peers: number
  n_firms: number
  p10: number
  p25: number
  peer_median: number
  p75: number
  p90: number
  ratio: number // pay ÷ peer median
  percentile: number // share of peers paid less (ties count half)
  verdict: Verdict
  label: string // peer group
}

export interface PeerVerdicts {
  year: number
  role: Role
  rows: { person_id: string; name: string; firm_id: string; firm: string; total: number; results: PeerResult[]; n_above: number }[]
}

export interface PeerExec {
  person_id: string
  name: string
  firm_id: string
  firm: string
  total: number
  index: string | null
  n_execs: number
  employees: number | null
  naics: string
  naics_title: string
  result: PeerResult | null // null: too few peer firms
}

export interface PeerMethodView {
  method: PeerMethod
  year: number
  role: Role
  years: number[]
  summary: { n: number; n_benchmarked: number; n_firms_median: number | null; above: number; below: number }
  executives: PeerExec[]
  links: { firm_id: string; peer_firm: string; score: number | null }[]
  groups: { label: string; n_firms: number; n_execs: number; median: number }[]
  clusters: {
    cluster: number
    name: string
    firm_years: number
    firms: number
    dax_share: number
    board_median: number
    sectors: { sector: string; share: number }[]
    examples: string[]
    ceo_median: number
  }[] | null
  cluster_choice: { k: number; silhouette: number; coverage: number; chosen: boolean }[] | null
  importance: { feature: string; importance: number }[] | null
  forest_fit: { r2: number; mdae: number; mdae_baseline: number; n: number } | null
}

export interface FirmPeerRow { year: number; person_id: string; name: string; total: number; result: PeerResult }

// ------------------------------------------------------------------ pay prediction

export type ModelFamily = 'own' | 'reference' | 'level' | 'change'

export interface PredictionModel { id: string; family: ModelFamily; name: string; idea: string; formula: string; why: string }
export interface Target { id: string; label: string }

export interface Score {
  model: string
  target: string
  regime: string
  n: number
  coverage: number
  mae: number // mean absolute error of log values
  mdae: number
  mae_ref: number // drift baseline on the same pairs
  skill: number // 1 − mae / mae_ref
  band_cover: number | null
  band_width: number | null
}

export interface HorizonScore { model: string; target: string; regime: string; h: number; n: number; mae: number; skill: number; band_cover: number | null }
export interface PaidScore { target: string; regime: string; n: number; share_paid: number; accuracy: number; accuracy_same: number }
export interface Seed { seed: number; mae: number }

export interface PredictionOverview {
  models: PredictionModel[]
  targets: Target[]
  scorecard: Score[]
  by_horizon: HorizonScore[]
  paid: PaidScore[]
  best: Record<string, string>
  best_rule: string
  band: number
  peer_method: string
  origins: number[]
  last_year: number
  latest_regime: string
  gap_woman: number
  gap_german: number
  mlp_seeds: Seed[]
  coherence: number | null
}

export interface PredictionModelView {
  model: PredictionModel
  target: string
  targets: Target[]
  scores: Score[]
  by_horizon: HorizonScore[]
  calibration: { regime: string; level: number; achieved: number | null }[]
  by_role: { regime: string; role: Role; n: number; mae: number; mae_ref: number }[]
  points: { regime: string; h: number; actual: number; predicted: number }[]
  misses: { person_id: string; name: string; firm: string; year: number; h: number; actual: number; predicted: number; error: number }[]
  best: Record<string, string>
  coefficients: { feature: string; coef: number }[] | null
  importance: { feature: string; importance: number }[] | null
  firms: { firm_id: string; firm: string; n: number; effect: number; weight: number }[] | null
  seeds: Seed[] | null
}

export interface ForecastRow { target: string; model: string; year: number; h: number; value: number; lo: number | null; hi: number | null; source: string | null }

export interface PersonPrediction {
  person_id: string
  name: string
  firm_id: string
  firm: string
  role: Role
  year: number
  regime: string
  best: Record<string, string>
  band: number
  history: { target: string; years: { year: number; value: number | null }[] }[]
  forecasts: ForecastRow[]
  paid: { target: string; year: number; p: number }[]
  board: { person_id: string; name: string; role: Role; total: number; ratio_to_ceo: number | null; is_self: boolean }[]
  avg_staff_cost: number | null
  staff_ratio: number | null
  method: string
  methods: { id: string; name: string }[]
  peer_firms: { firm_id: string; firm: string }[]
  peers: { target: string; value: number | null; p10: number; p25: number; median: number; p75: number; p90: number; n: number; percentile: number | null }[]
}

export interface FirmForecast { person_id: string; name: string; role: Role; year: number; total: number; value: number; lo: number | null; hi: number | null; model: string }

export interface WhatIf {
  person_id: string
  name: string
  firm: string
  role: Role
  year: number
  years: number
  growth: number | null
  rows: { target: string; now: number; expected: number; changed: number; change: number }[]
  effects: { target: string; feature: string; effect: number }[]
  promotion: { change: number; n: number } | null
}

// ------------------------------------------------------------------ data entry

export interface DataColumn {
  name: string
  kind: 'text' | 'number' | 'integer' | 'choice' | 'bool' | 'firm'
  label: string
  required: boolean
  unit: string | null
  options: string[]
  help: string
}

export interface DataTable { id: string; name: string; file: string; purpose: string; columns: DataColumn[]; deletable: boolean; rows: Record<string, string>[] }
export interface Finding { level: 'error' | 'warning' | 'info' | 'ok'; field: string | null; message: string }
export interface TableRows { table: string; rows: Record<string, string>[] }
export interface RowFindings { table: string; row: number; findings: Finding[] }
export interface Extracted { name: string; text: string; pages: number | null; truncated: boolean }

// ------------------------------------------------------------------ assistant

/** `thinking`: the model's thinking settings, e.g. ['off', 'on'] or ['off', 'low', 'medium', 'xhigh']; empty if none. */
export interface ChatSetup { models: { id: string; available: boolean; default: boolean; thinking: string[] }[]; examples: string[] }
export interface ChatMessage { role: 'user' | 'assistant'; content: string }
export interface ChartSpec { title: string; kind: 'line' | 'bar' | 'dot'; x: string; y: string; color: string | null; rows: Record<string, string | number | null>[] }
export interface Draft { changes: TableRows[]; checks: RowFindings[] }
export type ChatEvent =
  | { type: 'thinking'; text: string }
  | ({ type: 'draft' } & Draft)
  | ({ type: 'chart' } & ChartSpec)
  | { type: 'tool'; name: string; args: Record<string, unknown> }
  | { type: 'result'; name: string; preview: string }
  | { type: 'answer'; text: string; unverified: string[] }
  | { type: 'error'; text: string }

export const COMPONENTS = ['fixed', 'sti', 'mti', 'lti', 'other'] as const
export type Component = (typeof COMPONENTS)[number]

// ------------------------------------------------------------------ fetching

const cache = new Map<string, unknown>()

/** Forget every cached response, e.g. after data was added. */
export const clearCache = () => cache.clear()

/** POST or DELETE with a JSON body; rejects with the backend's error message. */
export async function send<T>(method: 'POST' | 'DELETE', path: string, body?: unknown): Promise<T> {
  const r = await fetch(`/api${path}`, {
    method,
    headers: body === undefined ? undefined : { 'Content-Type': 'application/json' },
    body: body === undefined ? undefined : JSON.stringify(body),
  })
  const data = await r.json().catch(() => ({}))
  if (!r.ok) throw new Error(typeof data.detail === 'string' ? data.detail : `${r.status} ${r.statusText}`)
  return data as T
}

export interface ChatRequest { model: string; thinking: string; messages: ChatMessage[]; page: string; draft: TableRows[] | null }

/** POST /api/chat and call `onEvent` for each line of the streamed answer. */
export async function streamChat(request: ChatRequest, onEvent: (e: ChatEvent) => void, signal: AbortSignal) {
  const r = await fetch('/api/chat', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(request),
    signal,
  })
  if (!r.ok || !r.body) throw new Error(`${r.status} ${r.statusText}`)
  const reader = r.body.pipeThrough(new TextDecoderStream()).getReader()
  let buffer = ''
  for (;;) {
    const { done, value } = await reader.read()
    if (done) break
    buffer += value
    const lines = buffer.split('\n')
    buffer = lines.pop() ?? ''
    for (const line of lines) if (line.trim()) onEvent(JSON.parse(line) as ChatEvent)
  }
}

export type Loadable<T> = { data?: T; error?: string; reload: () => void }

/** GET /api{path}; responses are cached for the session so back-navigation is instant.
 *  A null path waits (e.g. until another request supplies a parameter). */
export function useApi<T>(path: string | null): Loadable<T> {
  const [result, setResult] = useState<{ path: string; data?: T; error?: string }>()
  const [attempt, setAttempt] = useState(0)

  useEffect(() => {
    if (path === null || cache.has(path)) return
    let live = true
    fetch(`/api${path}`)
      .then((r) => (r.ok ? r.json() : Promise.reject(new Error(`${r.status} ${r.statusText}`))))
      .then(
        (data: T) => {
          cache.set(path, data)
          if (live) setResult({ path, data })
        },
        (e: Error) => live && setResult({ path, error: e.message }),
      )
    return () => {
      live = false
    }
  }, [path, attempt])

  const reload = useCallback(() => {
    setResult(undefined)
    setAttempt((n) => n + 1)
  }, [])

  if (path !== null && cache.has(path)) return { data: cache.get(path) as T, reload }
  // Ignore a result left over from a previous path while the new request is in flight.
  return result?.path === path ? { data: result.data, error: result.error, reload } : { reload }
}
