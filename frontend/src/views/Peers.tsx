import * as Plot from '@observablehq/plot'
import { useState } from 'react'

import { useApi, type FirmPeerRow, type Loadable, type PeerExec, type PeerMethod, type PeerMethodView, type PeerOverview, type PeerVerdicts, type Role } from '../api'
import { FAMILY_COLOR, FAMILY_LABEL, REGIME_BREAK, base, labelAxis, meurAxis, methodStyle, narrow, onPick, ratioAxis, ratioPositions, regimeBreak, swarmHeight, verdictZones, yearAxis, yearBar } from '../charts'
import { ROLE_LABEL, keur, logPct, meur, multiple, pct, spell } from '../format'
import { Async, Chart, Legend, PageHead, PageSkeleton, Panel, PanelsSkeleton, Segmented, Skeleton, Stat, Table, type Column } from '../ui'

// Every number on these pages comes from backend/app/peers.py; see docs/peers.md for the method.

const ROLES: { value: Role; label: string }[] = (['CEO', 'CFO', 'Member'] as Role[]).map((r) => ({ value: r, label: ROLE_LABEL[r] }))
const ONE: Record<Role, string> = { CEO: 'CEO', CFO: 'CFO', Member: 'other board member' }
const MANY: Record<Role, string> = { CEO: 'CEOs', CFO: 'CFOs', Member: 'other board members' }

/** Legend items for the definitions: family colour plus a symbol per definition. */
function methodLegend(methods: PeerMethod[]) {
  return methodStyle(methods).style.map((s) => ({ label: s.name, color: s.color, shape: s.symbol }))
}

// ------------------------------------------------------------------ overview

export function PeersView() {
  const state = useApi<PeerOverview>('/peers')
  return (
    <>
      <PageHead title="Peer benchmark">
        {state.data &&
          `Is an executive paid more than comparable executives? That depends on who counts as comparable. ${spell(state.data.methods.length, true)} peer definitions, from simple rules to a machine-learned similarity, applied to the same executives side by side.`}
      </PageHead>
      <Async state={state} skeleton={<PanelsSkeleton heights={[420, 520, 520]} />}>
        {(o) => <Overview o={o} />}
      </Async>
    </>
  )
}

function Overview({ o }: { o: PeerOverview }) {
  const byFit = [...o.methods].sort((a, b) => a.fit - b.fit)
  const [best, worst] = [byFit[0], byFit[byFit.length - 1]]
  const strongest = [...o.methods].sort((a, b) => a.pull - b.pull)[0]
  const flipped = o.ceo_flagged_any - o.ceo_flagged_all
  const stricter = o.fragility.find((f) => f.line > o.high && f.flagged_any > 0)
  return (
    <>
      <div className="stats">
        <Stat
          label="Typical gap, best definition"
          value={logPct(best.fit)}
          sub={`between pay and the peer median with ${best.name}; ${logPct(o.baseline.fit)} when every firm counts as a peer`}
        />
        <Stat
          label="Typical gap, weakest definition"
          value={logPct(worst.fit)}
          sub={`with ${worst.name}: ${worst.fit > o.baseline.fit ? 'worse' : 'better'} than no peer selection at all`}
        />
        <Stat
          label="CEO verdicts that depend on the definition"
          value={o.ceo_flagged_any ? pct(flipped / o.ceo_flagged_any) : '–'}
          sub={`${flipped} of the ${o.ceo_flagged_any} CEO-years paid at least ${o.high}× their peer median under some definitions are not under all${stricter ? `; at ${stricter.line}× it is ${pct(1 - stricter.flagged_all / stricter.flagged_any)}` : ''}`}
        />
        <Stat
          label="Gap closed within a year"
          value={pct(-strongest.pull)}
          sub={`pay moves toward the peer median (${strongest.name}); ${pct(-o.baseline.pull)} toward the median of all firms`}
        />
      </div>

      <nav aria-label="Peer definitions" className="views methods">
        {o.methods.map((m) => (
          <a key={m.id} href={`#/peers/${m.id}`}>
            <strong>
              <MethodMark methods={o.methods} id={m.id} /> {m.name}
            </strong>
            <span>{m.rule}</span>
            <span className="card-stats">
              {pct(m.coverage)} covered · {m.n_firms_median.toFixed(0)} peer firms · typical gap {logPct(m.fit)}
            </span>
          </a>
        ))}
      </nav>

      <Scorecard o={o} />
      <Agreement o={o} />
      <VerdictStrip o={o} />
      <Robust o={o} />
      <Convergence o={o} />
    </>
  )
}

/** The definition's colour and symbol, inline in text. */
export function MethodMark({ methods, id }: { methods: PeerMethod[]; id: string }) {
  const s = methodStyle(methods).style[methods.findIndex((m) => m.id === id)]
  return s ? <i className={`swatch ${s.symbol}`} style={{ background: s.color }} aria-hidden="true" /> : null
}

// ------------------------------------------------------------------ scorecard

type Metric = { key: string; title: string; caption: (o: PeerOverview) => string; value: (m: PeerMethod) => number; error?: (m: PeerMethod) => number; better: 'lower' | 'higher' }

const METRICS: Metric[] = [
  {
    key: 'fit',
    title: 'Typical gap to the peer median',
    caption: () => 'Median distance between pay and the peer median. Lower means the peers explain pay better.',
    value: (m) => Math.exp(m.fit) - 1,
    better: 'lower',
  },
  {
    key: 'pull',
    title: 'Gap closed within a year',
    caption: () =>
      'Share of the gap to the peer median that next year’s pay change closes, net of market-wide raises (bars: ±2 standard errors, clustered by firm). Higher means pay gravitates to these peers.',
    value: (m) => -m.pull,
    error: (m) => 2 * m.pull_se,
    better: 'higher',
  },
  {
    key: 'stability',
    title: 'Peers kept from one year to the next',
    caption: () => 'Average overlap of a firm’s peer firms in consecutive years (Jaccard). Higher means a steadier, easier to defend peer group.',
    value: (m) => m.stability,
    better: 'higher',
  },
  {
    key: 'coverage',
    title: 'Executive-years with a result',
    caption: (o) => `Definitions that find fewer than ${o.min_peer_firms} peer firms give no benchmark.`,
    value: (m) => m.coverage,
    better: 'higher',
  },
]

function Scorecard({ o }: { o: PeerOverview }) {
  const rows = [...o.methods, o.baseline]
  return (
    <Panel
      title="Which definition explains pay best"
      caption={`Four tests on the same ${o.n_common.toLocaleString('en-GB')} executive-years that every definition can benchmark (coverage on all ${o.n_rows.toLocaleString('en-GB')}). The grey row uses every other firm of the year as peers: the benchmark without any peer selection.`}
      note="Fit and pull are out of sample for the firm: an executive's own firm is never among the peers, and the random forest that picks a firm's peers was trained without that firm."
    >
      <Legend items={[...methodLegend(o.methods), { label: o.baseline.name, color: FAMILY_COLOR.baseline, shape: 'circle' }]} />
      <div className="grid-2">
        {METRICS.map((metric) => (
          <div key={metric.key} className="subchart">
            <h3>{metric.title}</h3>
            <p className="caption">{metric.caption(o)}</p>
            <Chart label={scoreLabel(rows, metric)} render={(width) => scoreChart(rows, o.methods, metric, width)} />
          </div>
        ))}
      </div>
    </Panel>
  )
}

function scoreLabel(rows: PeerMethod[], metric: Metric) {
  const sorted = [...rows].sort((a, b) => metric.value(a) - metric.value(b))
  const top = metric.better === 'lower' ? sorted[0] : sorted[sorted.length - 1]
  return `${metric.title}: best is ${top.name} at ${pct(metric.value(top))}.`
}

function scoreChart(rows: PeerMethod[], methods: PeerMethod[], metric: Metric, width: number) {
  const { color, symbol } = methodStyle(methods)
  const data = rows.map((m) => ({ ...m, v: metric.value(m), e: metric.error?.(m) ?? 0 }))
  const baseline = data[data.length - 1]
  const names = rows.map((m) => m.name)
  const labels = labelAxis(names, width)
  const reach = Math.max(...data.map((d) => d.v + d.e)) * 1.08
  return Plot.plot({
    ...base(width, rows.length * 28 + 40),
    marginLeft: labels.marginLeft,
    marginRight: 52,
    x: { label: null, grid: true, tickFormat: '.0%', ticks: narrow(width) ? (reach > 0.8 ? 3 : 4) : undefined, domain: [0, reach] },
    y: { label: null, domain: names, tickFormat: labels.tickFormat },
    color: { ...color, domain: [...(color.domain as string[]), baseline.name], range: [...(color.range as string[]), FAMILY_COLOR.baseline] },
    symbol: { ...symbol, domain: [...(symbol.domain as string[]), baseline.name], range: [...(symbol.range as string[]), 'circle'] },
    marks: [
      Plot.ruleX([baseline.v], { stroke: 'var(--c-member)', strokeOpacity: 0.6 }),
      Plot.ruleY(data.filter((d) => d.e > 0), { y: 'name', x1: (d) => d.v - d.e, x2: (d) => d.v + d.e, stroke: 'var(--muted)', strokeOpacity: 0.6 }),
      Plot.dot(data, {
        x: 'v',
        y: 'name',
        fill: 'name',
        symbol: 'name',
        r: 5.5,
        stroke: 'var(--surface)',
        strokeWidth: 1.5,
        tip: true,
        title: (d) => `${d.name}\n${metric.title}: ${pct(d.v, 1)}${d.e ? ` ± ${pct(d.e, 1)}` : ''}`,
      }),
      Plot.text(data, { x: (d) => d.v + d.e, y: 'name', text: (d) => pct(d.v), dx: 10, textAnchor: 'start', fill: 'var(--muted)', fontSize: 11 }),
    ],
  })
}

// ------------------------------------------------------------------ agreement

function Agreement({ o }: { o: PeerOverview }) {
  const [measure, setMeasure] = useState<'spearman' | 'same_verdict'>('spearman')
  const names = new Map(o.methods.map((m) => [m.id, m.name]))
  const order = o.methods.map((m) => m.id)
  // Lower triangle: each pair once.
  const cells = o.agreement
    .filter((c) => order.indexOf(c.a) > order.indexOf(c.b))
    .map((c) => ({ a: names.get(c.a)!, b: names.get(c.b)!, value: c[measure] }))
  const lowest = [...cells].sort((x, y) => x.value - y.value)[0]
  if (!lowest) return null
  return (
    <Panel
      title="Do the definitions agree?"
      caption={
        measure === 'spearman'
          ? 'Rank correlation of pay ÷ peer median between two definitions, over the executive-years both benchmark: 1 means they rank everyone identically.'
          : `Share of executive-years with the same verdict under both definitions (above ${o.high}× the peer median, below 1 / ${o.high}, or in line).`
      }
      controls={
        <Segmented
          label="Measure"
          value={measure}
          onChange={setMeasure}
          options={[
            { value: 'spearman', label: 'Rank correlation' },
            { value: 'same_verdict', label: 'Same verdict' },
          ]}
        />
      }
    >
      <Chart
        minWidth={520}
        label={`Agreement between peer definitions; the lowest is ${lowest.a} with ${lowest.b} at ${lowest.value.toFixed(2)}.`}
        render={(width) => {
          const domain = o.methods.map((m) => m.name)
          const labels = labelAxis(domain, width, 0.3)
          return Plot.plot({
            ...base(Math.min(width, 980), domain.length * 44 + 120), // cells stay readable on wide screens
            marginLeft: labels.marginLeft,
            marginBottom: 110,
            x: { label: null, domain: domain.slice(0, -1), tickRotate: -30, tickFormat: labels.tickFormat },
            y: { label: null, domain: domain.slice(1), tickFormat: labels.tickFormat },
            marks: [
              Plot.cell(cells, { x: 'b', y: 'a', fill: 'var(--grid)', inset: 1 }),
              Plot.cell(cells, {
                x: 'b',
                y: 'a',
                fill: 'var(--c-band)',
                fillOpacity: (d) => Math.max(0.05, (d.value - 0.5) / 0.5),
                inset: 1,
                tip: true,
                title: (d) => `${d.a} × ${d.b}\n${measure === 'spearman' ? 'rank correlation' : 'same verdict'}: ${measure === 'spearman' ? d.value.toFixed(2) : pct(d.value)}`,
              }),
              Plot.text(cells, {
                x: 'b',
                y: 'a',
                text: (d) => (measure === 'spearman' ? d.value.toFixed(2) : pct(d.value)),
                fill: (d) => ((d.value - 0.5) / 0.5 > 0.55 ? 'var(--on-accent)' : 'var(--ink)'),
                fontSize: 12,
              }),
            ],
          })
        }}
      />
    </Panel>
  )
}

// ------------------------------------------------------------------ verdict strip

function VerdictStrip({ o }: { o: PeerOverview }) {
  const [picked, setYear] = useState<number>()
  const [role, setRole] = useState<Role>('CEO')
  const [only, setOnly] = useState(false)
  const year = picked ?? o.years[o.years.length - 1]
  const state = useApi<PeerVerdicts>(year ? `/peers/verdicts?year=${year}&role=${role}` : null)
  return (
    <Panel
      title="Same executive, different verdicts"
      caption={`Pay ÷ peer median under each definition, one row per ${ONE[role]}. Shaded: at least ${o.high}× the peer median (right) or at most 1 / ${o.high} (left). The number on the right counts the definitions with an 'above' verdict.`}
      controls={
        <>
          <label className="field">
            <span>Year</span>
            <select value={year} onChange={(e) => setYear(Number(e.target.value))}>
              {[...o.years].reverse().map((y) => (
                <option key={y}>{y}</option>
              ))}
            </select>
          </label>
          <Segmented label="Role" value={role} onChange={setRole} options={ROLES.slice(0, 2)} />
          <Segmented
            label="Show"
            value={only ? 1 : 0}
            onChange={(v) => setOnly(v === 1)}
            options={[
              { value: 0, label: 'All' },
              { value: 1, label: 'Verdict depends on definition' },
            ]}
          />
        </>
      }
    >
      <Legend items={methodLegend(o.methods)} />
      <Async state={state} skeleton={<Skeleton height={800} />}>
        {(v) => {
          const rows = v.rows
            .filter((r) => r.results.length > 0 && (!only || (r.n_above > 0 && r.n_above < r.results.length)))
            .sort((a, b) => b.n_above - a.n_above || b.total - a.total)
          if (!rows.length) return <p className="callout">No {ONE[role]} in {year} gets different verdicts from the definitions.</p>
          return <Chart label={stripLabel(rows, year)} render={(width) => stripChart(rows, o, width)} />
        }}
      </Async>
    </Panel>
  )
}

type StripRow = PeerVerdicts['rows'][number]

function stripLabel(rows: StripRow[], year: number) {
  const all = rows.filter((r) => r.n_above === r.results.length && r.n_above > 0).length
  const some = rows.filter((r) => r.n_above > 0).length
  return `${year}: ${some} executives are above their peers under at least one definition, ${all} under every definition.`
}

function stripChart(rows: StripRow[], o: PeerOverview, width: number) {
  const { color, symbol } = methodStyle(o.methods)
  const names = new Map(o.methods.map((m) => [m.id, m.name]))
  // Firm names label the rows; a second executive of the same firm (co-CEOs) adds the surname.
  const seen = new Set<string>()
  const label = new Map(
    rows.map((r) => {
      const l = seen.has(r.firm) ? `${r.firm} (${r.name.split(' ').at(-1)})` : r.firm
      seen.add(r.firm)
      return [r, l]
    }),
  )
  const points = rows.flatMap((r) => r.results.map((x) => ({ ...x, row: label.get(r)!, who: r, method: names.get(x.method) ?? x.method })))
  const axis = ratioAxis(points.map((p) => p.ratio), width)
  const rowNames = rows.map((r) => label.get(r)!)
  const labels = labelAxis(rowNames, width, 0.34)
  const plot = Plot.plot({
    ...base(width, rows.length * 19 + 60),
    marginLeft: labels.marginLeft,
    marginRight: 44,
    x: axis,
    y: { label: null, domain: rowNames, tickFormat: labels.tickFormat },
    color,
    symbol,
    marks: [
      ...verdictZones(o.high, axis),
      Plot.ruleY(points, Plot.groupY({ x1: 'min', x2: 'max' }, { y: 'row', x1: 'ratio', x2: 'ratio', stroke: 'var(--rule)', strokeWidth: 2 })),
      Plot.dot(points, {
        x: 'ratio',
        y: 'row',
        fill: 'method',
        symbol: 'method',
        r: 4.5,
        stroke: 'var(--surface)',
        strokeWidth: 1,
        tip: true,
        title: (p) =>
          `${p.who.name}, ${p.who.firm}\n${p.method}: ${multiple(p.ratio)} the peer median\npay ${meur(p.who.total, 2)} · peer median ${meur(p.peer_median, 2)}\n${p.n_firms} peer firms · ${p.label}`,
      }),
      Plot.text(rows, { y: (r) => label.get(r)!, text: (r) => `${r.n_above}/${r.results.length}`, frameAnchor: 'right', dx: 36, fill: 'var(--muted)', fontSize: 11 }),
    ],
  })
  onPick<(typeof points)[number]>(plot, (p) => (location.hash = `#/companies/${p.who.firm_id}`))
  return plot
}

// ------------------------------------------------------------------ robust verdicts over time

/** Share of flagged executive-years whose flag depends on the definition. */
const fragile = (f: PeerOverview['fragility'][number]) => (f.flagged_any ? 1 - f.flagged_all / f.flagged_any : 0)

function Robust({ o }: { o: PeerOverview }) {
  const KIND = [
    { key: 'robust' as const, label: 'Above under every definition', color: 'var(--warn)' },
    { key: 'fragile' as const, label: 'Above under some definitions only', color: 'color-mix(in srgb, var(--warn) 35%, transparent)' },
  ]
  const bars = o.ceo_by_year.flatMap((y) => KIND.map((k) => ({ year: y.year, label: k.label, value: y[k.key] / y.n, count: y[k.key], n: y.n })))
  const latest = o.ceo_by_year[o.ceo_by_year.length - 1]
  const [first, last] = [o.fragility[0], o.fragility[o.fragility.length - 1]]
  if (!latest || !first) return null
  return (
    <Panel
      title="Robust and fragile 'above peers' verdicts, year by year"
      caption={`Share of benchmarked CEOs paid at least ${o.high}× their peer median under every definition that benchmarks them (dark) or under some only (light).`}
      note={`Until ${Math.floor(REGIME_BREAK)} the panel covers DAX and MDAX firms, from ${Math.ceil(REGIME_BREAK)} the DAX firms only; peers always come from the same year.`}
    >
      <Legend items={KIND.map((k) => ({ label: k.label, color: k.color }))} />
      <Chart
        label={`In ${latest.year}, ${latest.robust} CEOs are above their peers under every definition and ${latest.fragile} under some only.`}
        render={(width) =>
          Plot.plot({
            ...base(width, 260),
            x: yearAxis,
            y: { label: 'Share of CEOs', grid: true, tickFormat: '%' },
            color: { domain: KIND.map((k) => k.label), range: KIND.map((k) => k.color) },
            marks: [
              Plot.rectY(
                bars,
                Plot.stackY({
                  ...yearBar,
                  y: 'value',
                  fill: 'label',
                  order: KIND.map((k) => k.label),
                  tip: true,
                  title: (b: (typeof bars)[number]) => `${b.year} · ${b.label}
${b.count} of ${b.n} CEOs (${pct(b.value)})`,
                }),
              ),
              Plot.ruleY([0]),
              ...regimeBreak(width),
            ],
          })
        }
      />
      <h3>Does it depend on the {o.high}× line?</h3>
      <p className="caption">
        Share of flagged CEO-years (all years) whose verdict depends on the definition, for other lines. A stricter line,
        closer to the multiples proxy advisers use, makes the verdict more fragile, not less.
      </p>
      <Chart
        label={`At every verdict line most flags depend on the definition: from ${pct(fragile(first))} at ${first.line}× to ${pct(fragile(last))} at ${last.line}×.`}
        render={(width) =>
          Plot.plot({
            ...base(width, 200),
            x: { label: narrow(width) ? 'Verdict line (pay ÷ peer median)' : 'Verdict line: pay ÷ peer median at least', type: 'log', ticks: o.fragility.map((f) => f.line), tickFormat: (v: number) => `${v}×` },
            y: { label: narrow(width) ? '↑ Depend on the definition' : '↑ Flags that depend on the definition', grid: true, tickFormat: '%', domain: [0, 1] },
            marks: [
              Plot.lineY(o.fragility, { x: 'line', y: fragile, stroke: 'var(--warn)', strokeWidth: 2 }),
              Plot.dot(o.fragility, {
                x: 'line',
                y: fragile,
                r: (f) => (f.line === o.high ? 6 : 4),
                fill: (f) => (f.line === o.high ? 'var(--ink)' : 'var(--warn)'),
                stroke: 'var(--surface)',
                tip: true,
                title: (f) => `At ${f.line}×: ${f.flagged_any} CEO-years flagged by some definition, ${f.flagged_all} by all (${pct(fragile(f))} depend on the definition)`,
              }),
              Plot.text(o.fragility, { x: 'line', y: fragile, text: (f) => pct(fragile(f)), dy: -12, fill: 'var(--muted)', fontSize: 11 }),
            ],
          })
        }
      />
      <Table
        caption="CEOs above their peers under every definition"
        tall
        rows={o.robust_ceos}
        rowKey={(r) => `${r.year}|${r.person_id}|${r.firm_id}`}
        sort={{ key: 'year', desc: true }}
        columns={[
          { key: 'year', label: 'Year', value: (r) => r.year },
          { key: 'firm', label: 'Company', value: (r) => r.firm, render: (r) => <a href={`#/companies/${r.firm_id}`}>{r.firm}</a> },
          { key: 'name', label: 'CEO', value: (r) => r.name, render: (r) => <a href={`#/people/${r.person_id}`}>{r.name}</a> },
          { key: 'total', label: 'Pay (k€)', numeric: true, value: (r) => r.total, render: (r) => keur(r.total) },
          { key: 'min', label: 'Lowest ratio', numeric: true, value: (r) => r.ratio_min, render: (r) => multiple(r.ratio_min) },
          { key: 'max', label: 'Highest ratio', numeric: true, value: (r) => r.ratio_max, render: (r) => multiple(r.ratio_max) },
          { key: 'n', label: 'Definitions', numeric: true, value: (r) => r.n_methods },
        ]}
      />
    </Panel>
  )
}

// ------------------------------------------------------------------ convergence

function Convergence({ o }: { o: PeerOverview }) {
  const strongest = [...o.methods].sort((a, b) => a.pull - b.pull)[0]
  return (
    <Panel
      title="Pay drifts toward the peer median"
      caption={`Executives in ${o.convergence.filter((d) => d.method === o.baseline.id).length} equal-sized groups by their gap to the peer median in one year, against their average pay change to the next year (same person, firm and role, net of that year's average change). Grey: the same with every other firm as peers.`}
      note="Part of the drift is chance (an unusually high year tends to be followed by a lower one), which the grey baseline also shows. Peer groups whose median attracts pay more strongly than the baseline capture what boards actually benchmark against; this is the pattern Bizjak, Lemmon & Naveen (2008) report for US firms."
    >
      <Chart
        label={`Executives paid below their peers get larger raises the next year; strongest with ${strongest.name}, which closes ${pct(-strongest.pull)} of the gap per year.`}
        render={(width) => convergenceChart(o, width)}
      />
    </Panel>
  )
}

function convergenceChart(o: PeerOverview, width: number) {
  const cols = narrow(width) ? 1 : width < 820 ? 2 : 3
  const names = new Map(o.methods.map((m, i) => [m.id, { name: m.name, i, color: FAMILY_COLOR[m.family] }]))
  const point = (d: PeerOverview['convergence'][number]) => ({ ...d, x: Math.exp(d.gap), y: Math.exp(d.change) - 1 })
  const own = o.convergence.filter((d) => names.has(d.method)).map((d) => ({ ...point(d), ...names.get(d.method)! }))
  const baseline = o.methods.flatMap((m, i) =>
    o.convergence.filter((d) => d.method === o.baseline.id).map((d) => ({ ...point(d), name: m.name, i })),
  )
  const facet = { fx: (d: { i: number }) => d.i % cols, fy: (d: { i: number }) => Math.floor(d.i / cols) }
  const titles = o.methods.map((m, i) => ({ i, name: m.name, pull: m.pull }))
  const xs = [...own, ...baseline].map((d) => d.x)
  return Plot.plot({
    ...base(width, Math.ceil(o.methods.length / cols) * 210 + 50),
    x: { ...ratioAxis(xs, width, 'Pay ÷ peer median this year'), ticks: [0.5, 1, 2], grid: true },
    y: { label: '↑ Pay change next year', grid: true, tickFormat: '+.0%' },
    fx: { axis: null, padding: 0.12 },
    fy: { axis: null, padding: 0.2 },
    marks: [
      Plot.ruleY([0], { stroke: 'var(--rule)' }),
      Plot.ruleX([1], { stroke: 'var(--rule)' }),
      Plot.lineY(baseline, { ...facet, x: 'x', y: 'y', stroke: 'var(--c-member)', strokeWidth: 1.5 }),
      Plot.lineY(own, { ...facet, x: 'x', y: 'y', stroke: (d) => d.color, strokeWidth: 2 }),
      Plot.dot(own, {
        ...facet,
        x: 'x',
        y: 'y',
        fill: (d) => d.color,
        r: 3.5,
        stroke: 'var(--surface)',
        tip: true,
        title: (d) => `${d.name}\npaid ${multiple(d.x)} the peer median → next year ${d.y > 0 ? '+' : ''}${pct(d.y, 1)}\n(${d.n} executive-years)`,
      }),
      Plot.text(titles, {
        ...facet,
        text: (d) => `${d.name}\n${pct(-d.pull)} of the gap closes per year`,
        frameAnchor: 'top-right',
        textAnchor: 'end',
        dx: -4,
        dy: 4,
        fontSize: 11,
        fill: 'var(--ink)',
        lineHeight: 1.2,
      }),
    ],
  })
}

// ------------------------------------------------------------------ one definition

export function PeerMethodPage({ id }: { id: string }) {
  const overview = useApi<PeerOverview>('/peers')
  const [picked, setYear] = useState<number>()
  const [role, setRole] = useState<Role>('CEO')
  const o = overview.data
  const method = o?.methods.find((m) => m.id === id)
  const year = picked ?? o?.years[o.years.length - 1]
  const state = useApi<PeerMethodView>(method && year ? `/peers/${encodeURIComponent(id)}?year=${year}&role=${role}` : null)

  if (overview.error) return <Async state={overview}>{() => null}</Async>
  if (!o) return <PageSkeleton />
  if (!method) return <p>Unknown peer definition. <a href="#/peers">Back to the peer benchmark</a>.</p>
  return (
    <>
      <PageHead crumb={<a href="#/peers">Peer benchmark</a>} title={method.name}>
        {method.rule}
      </PageHead>
      <p className="muted origin">
        <MethodMark methods={o.methods} id={method.id} /> {FAMILY_LABEL[method.family]} · Idea from: {method.origin}
      </p>
      <div className="controls">
        <label className="field">
          <span>Year</span>
          <select value={year} onChange={(e) => setYear(Number(e.target.value))}>
            {[...o.years].reverse().map((y) => (
              <option key={y}>{y}</option>
            ))}
          </select>
        </label>
        <Segmented label="Role" value={role} onChange={setRole} options={ROLES} />
      </div>
      <Async state={state} skeleton={<PanelsSkeleton heights={[300, 500, 500]} />}>
        {(v) => <MethodBody v={v} o={o} />}
      </Async>
    </>
  )
}

function MethodBody({ v, o }: { v: PeerMethodView; o: PeerOverview }) {
  const benchmarked = v.executives.filter((e): e is PeerExec & { result: NonNullable<PeerExec['result']> } => e.result != null)
  const missing = v.executives.filter((e) => e.result == null)
  const [selectedKey, select] = useState<string>()
  const key = (e: PeerExec) => `${e.person_id}|${e.firm_id}`
  const top = [...benchmarked].sort((a, b) => b.total - a.total)[0]
  const selected = benchmarked.find((e) => key(e) === selectedKey) ?? top
  const m = v.method

  return (
    <>
      <div className="stats">
        <Stat label={`Benchmarked, ${v.year}`} value={`${v.summary.n_benchmarked} of ${v.summary.n}`} sub={`${MANY[v.role]} with a full year in office`} />
        <Stat label="Peer firms per executive" value={v.summary.n_firms_median?.toFixed(0) ?? '–'} sub={`median in ${v.year}; at least ${o.min_peer_firms} required`} />
        <Stat
          label={`Above ${o.high}× the peer median`}
          value={`${v.summary.above}`}
          sub={`${v.summary.below} at most 1 / ${o.high} of it, ${v.summary.n_benchmarked - v.summary.above - v.summary.below} in line`}
        />
        <Stat label="Typical gap, all years" value={logPct(m.fit)} sub={`${pct(-m.pull)} of it closes within a year · ${pct(m.stability)} of peers kept year to year`} />
      </div>

      {v.clusters && v.cluster_choice && <Clusters v={v} minPeers={o.min_peer_firms} />}
      {v.importance && v.forest_fit && <Forest v={v} />}
      {m.score == null ? <Groups v={v} /> : <SectorShare v={v} />}

      {benchmarked.length > 0 && (
        <Panel
          title={`Where each ${ONE[v.role]} stands, ${v.year}`}
          caption={`Pay ÷ peer median, one dot per executive. Shaded: at least ${o.high}× the peer median, or at most 1 / ${o.high} of it. Click or tap a dot to see that executive's peers.`}
          note={missing.length ? `No result (fewer than ${o.min_peer_firms} peer firms): ${[...new Set(missing.map((e) => e.firm))].join(', ')}.` : undefined}
        >
          <Chart
            label={`${v.summary.above} of ${v.summary.n_benchmarked} executives are paid at least ${o.high} times their peer median in ${v.year}.`}
            render={(width) => standingChart(benchmarked, selected, o.high, FAMILY_COLOR[m.family], width, (e) => select(key(e)))}
          />
        </Panel>
      )}

      {selected && <PeerDetail v={v} selected={selected} />}

      <Panel title={`All ${MANY[v.role]}, ${v.year}`} caption="Amounts in k€. Choose a name to see the peers.">
        <Table
          caption={`Peer benchmark ${m.name} ${v.year}`}
          tall
          rows={benchmarked}
          rowKey={key}
          sort={{ key: 'ratio', desc: true }}
          columns={tableColumns((e) => select(key(e)))}
        />
      </Panel>
    </>
  )
}

type Benchmarked = PeerExec & { result: NonNullable<PeerExec['result']> }

function standingChart(rows: Benchmarked[], selected: Benchmarked | undefined, high: number, color: string, width: number, pick: (e: Benchmarked) => void) {
  const r = width < 600 ? 3.5 : 4.5
  const axis = ratioAxis(rows.map((e) => e.result.ratio), width)
  const plot = Plot.plot({
    ...base(width, Math.max(150, swarmHeight(ratioPositions(rows.map((e) => e.result.ratio)), width - 32, r))),
    marginLeft: 16,
    x: axis,
    y: { axis: null },
    marks: [
      ...verdictZones(high, axis),
      Plot.dot(
        rows,
        Plot.dodgeY('middle', {
          x: (e: Benchmarked) => e.result.ratio,
          r: (e: Benchmarked) => (e === selected ? r + 2.5 : r),
          fill: color,
          fillOpacity: (e: Benchmarked) => (e === selected ? 1 : 0.7),
          stroke: (e: Benchmarked) => (e === selected ? 'var(--ink)' : 'var(--surface)'),
          strokeWidth: (e: Benchmarked) => (e === selected ? 2 : 1),
          tip: true,
          title: (e: Benchmarked) =>
            `${e.name}, ${e.firm}\n${multiple(e.result.ratio)} the peer median (${meur(e.total, 2)} vs ${meur(e.result.peer_median, 2)})\npaid more than ${pct(e.result.percentile)} of ${e.result.n_peers} peers · ${e.result.n_firms} firms`,
        }),
      ),
    ],
  })
  onPick<Benchmarked>(plot, pick, false)
  return plot
}

function tableColumns(onPick: (e: Benchmarked) => void): Column<Benchmarked>[] {
  return [
    {
      key: 'name',
      label: 'Name',
      value: (e) => e.name,
      render: (e) => (
        <button type="button" className="link" onClick={() => onPick(e)}>
          {e.name}
        </button>
      ),
    },
    { key: 'firm', label: 'Company', value: (e) => e.firm, render: (e) => <a href={`#/companies/${e.firm_id}`}>{e.firm}</a> },
    { key: 'total', label: 'Pay', numeric: true, value: (e) => e.total, render: (e) => keur(e.total) },
    { key: 'median', label: 'Peer median', numeric: true, value: (e) => e.result.peer_median, render: (e) => keur(e.result.peer_median) },
    { key: 'ratio', label: 'Pay ÷ median', numeric: true, value: (e) => e.result.ratio, render: (e) => <strong>{multiple(e.result.ratio)}</strong> },
    { key: 'pct', label: 'Percentile', numeric: true, value: (e) => e.result.percentile, render: (e) => pct(e.result.percentile) },
    { key: 'firms', label: 'Peer firms', numeric: true, value: (e) => e.result.n_firms },
    { key: 'group', label: 'Peer group', value: (e) => e.result.label },
  ]
}

function PeerDetail({ v, selected }: { v: PeerMethodView; selected: Benchmarked }) {
  const firms = new Map(v.links.filter((l) => l.firm_id === selected.firm_id).map((l) => [l.peer_firm, l.score]))
  const peers: Peer[] = v.executives.filter((e) => firms.has(e.firm_id)).map((e) => ({ ...e, score: firms.get(e.firm_id) ?? null }))
  const r = selected.result
  const scored = v.method.score != null
  const reach = selected.total / Math.max(selected.total, ...peers.map((e) => e.total))
  return (
    <Panel
      title={`Peers of ${selected.name} (${selected.firm}), ${v.year}`}
      caption={`${r.n_peers} executives at ${r.n_firms} firms · ${r.label}. Pay ${meur(selected.total, 2)} against a peer median of ${meur(r.peer_median, 2)}: ${multiple(r.ratio)}, more than ${pct(r.percentile)} of the peers.`}
    >
      <Legend
        items={[
          { label: selected.name, color: 'var(--ink)', shape: 'circle' },
          { label: 'Peers', color: FAMILY_COLOR[v.method.family], shape: 'circle' },
          { label: 'Middle 50 % of peers', color: 'color-mix(in srgb, var(--c-band) 18%, transparent)' },
          { label: 'Peer median', color: 'var(--muted)', shape: 'line' },
        ]}
      />
      <Chart
        label={`${selected.name} is paid ${multiple(r.ratio)} the median of ${r.n_peers} peers.`}
        render={(width) =>
          Plot.plot({
            ...base(width, 150),
            marginLeft: 16,
            x: { ...meurAxis('Total pay, € million'), zero: true, nice: true },
            y: { axis: null },
            marks: [
              Plot.rectX([r], { x1: 'p25', x2: 'p75', fill: 'var(--c-band)', fillOpacity: 0.12 }),
              Plot.ruleX([r.peer_median], { stroke: 'var(--muted)', strokeWidth: 2 }),
              Plot.dot(
                peers,
                Plot.dodgeY('middle', {
                  x: 'total',
                  r: 5,
                  fill: FAMILY_COLOR[v.method.family],
                  fillOpacity: 0.75,
                  stroke: 'var(--surface)',
                  tip: true,
                  title: (e: PeerExec) => `${e.name}, ${e.firm}\n${meur(e.total, 2)}`,
                }),
              ),
              Plot.dot([selected], { x: 'total', r: 7, fill: 'var(--ink)', stroke: 'var(--surface)', strokeWidth: 2, frameAnchor: 'middle' }),
              Plot.text([selected], { x: 'total', text: () => selected.firm, dy: -16, frameAnchor: 'middle', textAnchor: reach > 0.85 ? 'end' : reach < 0.15 ? 'start' : 'middle', fill: 'var(--ink)', fontSize: 11 }),
            ],
          })
        }
      />
      <Table
        caption={`Peers of ${selected.name}`}
        rows={peers}
        rowKey={(e) => `${e.person_id}|${e.firm_id}`}
        sort={scored ? { key: 'score', desc: true } : { key: 'total', desc: true }}
        columns={[
          { key: 'firm', label: 'Company', value: (e) => e.firm, render: (e) => <a href={`#/companies/${e.firm_id}`}>{e.firm}</a> },
          { key: 'name', label: 'Name', value: (e) => e.name, render: (e) => <a href={`#/people/${e.person_id}`}>{e.name}</a> },
          ...(scored ? [scoreColumn(v.method.score!)] : []),
          { key: 'total', label: 'Pay (k€)', numeric: true, value: (e) => e.total, render: (e) => keur(e.total) },
          { key: 'index', label: 'Index', value: (e) => e.index ?? 'none' },
          { key: 'board', label: 'Board', numeric: true, value: (e) => e.n_execs },
          { key: 'employees', label: 'Employees', numeric: true, value: (e) => e.employees, render: (e) => keur(e.employees) },
          { key: 'naics', label: 'Industry (NAICS)', value: (e) => `${e.naics} ${e.naics_title}` },
        ]}
      />
    </Panel>
  )
}

type Peer = PeerExec & { score: number | null }

/** The definition's similarity score of a peer firm (integer for shared NAICS levels). */
function scoreColumn(label: string): Column<Peer> {
  return {
    key: 'score',
    label,
    numeric: true,
    value: (e) => e.score,
    render: (e) => (e.score == null ? '–' : Number.isInteger(e.score) ? e.score : e.score.toFixed(2)),
  }
}

// ------------------------------------------------------------------ method-specific panels

/** Group definitions: the groups of this year with their median pay. */
function Groups({ v }: { v: PeerMethodView }) {
  const groups = [...v.groups].sort((a, b) => b.median - a.median)
  if (!groups.length) return null
  const names = groups.map((g) => g.label)
  return (
    <Panel
      title={`Peer groups, ${v.year}`}
      caption={`Median pay of the benchmarked ${MANY[v.role]} in each group, € million; the label gives the number of firms. Each executive is compared with the other firms of their group.`}
    >
      <Chart
        label={`${groups.length} peer groups in ${v.year}; the highest median pay is in ${groups[0].label}.`}
        render={(width) => {
          const labels = labelAxis(names, width, 0.45)
          return Plot.plot({
            ...base(width, groups.length * 24 + 50),
            marginLeft: labels.marginLeft,
            marginRight: narrow(width) ? 64 : 80,
            x: { ...meurAxis(), zero: true, ticks: narrow(width) ? 3 : undefined },
            y: { label: null, domain: names, tickFormat: labels.tickFormat },
            marks: [
              Plot.barX(groups, {
                x: 'median',
                y: 'label',
                fill: FAMILY_COLOR[v.method.family],
                fillOpacity: 0.85,
                tip: true,
                title: (g) => `${g.label}\n${g.n_firms} firms, ${g.n_execs} executives\nmedian ${meur(g.median, 2)}`,
              }),
              Plot.text(groups, { x: 'median', y: 'label', text: (g) => `${g.n_firms} firms`, dx: 6, textAnchor: 'start', fill: 'var(--muted)', fontSize: 11 }),
              Plot.ruleX([0]),
            ],
          })
        }}
      />
    </Panel>
  )
}

/** Nearest-neighbour definitions: how many of the chosen peer firms share the sector. */
function SectorShare({ v }: { v: PeerMethodView }) {
  const rows = v.groups
    .map((g) => ({ ...g, same: Number(g.label.split(' ')[0]), of: Number(g.label.split(' ')[2]) }))
    .sort((a, b) => a.same / a.of - b.same / b.of)
  if (!rows.length) return null
  return (
    <Panel
      title={`How many peers share the executive's sector, ${v.year}`}
      caption="Number of executives by how many of their peer firms are in the same NAICS sector. The definition trades industry against size; this shows how the trade came out."
    >
      <Chart
        label={`Peer firms in the same sector, ${v.year}`}
        render={(width) => {
          const short = new Map(rows.map((r) => [r.label, `${r.same} of ${r.of} peers`]))
          const labels = narrow(width) ? { ...labelAxis([...short.values()], width), tickFormat: (l: string) => short.get(l) ?? l } : labelAxis(rows.map((r) => r.label), width)
          return Plot.plot({
            ...base(width, rows.length * 24 + 50),
            marginLeft: labels.marginLeft,
            marginRight: 40,
            x: { label: 'Executives', grid: true, ticks: narrow(width) ? 4 : undefined },
            y: { label: null, domain: rows.map((r) => r.label), tickFormat: labels.tickFormat },
            marks: [
              Plot.barX(rows, { x: 'n_execs', y: 'label', fill: FAMILY_COLOR[v.method.family], fillOpacity: 0.85, tip: true, title: (r) => `${r.label}: ${r.n_execs} executives` }),
              Plot.text(rows, { x: 'n_execs', y: 'label', text: 'n_execs', dx: 6, textAnchor: 'start', fill: 'var(--muted)', fontSize: 11 }),
              Plot.ruleX([0]),
            ],
          })
        }}
      />
    </Panel>
  )
}

function Clusters({ v, minPeers }: { v: PeerMethodView; minPeers: number }) {
  const clusters = v.clusters!
  const choice = v.cluster_choice!
  const chosen = choice.find((c) => c.chosen)
  const next = choice.find((c) => chosen && c.k === chosen.k + 1)
  return (
    <>
      <Panel
        title="The clusters"
        caption="K-means groups firm-years by index, board size and NAICS sector, pooled over all years so that a cluster means the same thing every year. Median CEO pay over all years, € million."
      >
        <Table
          caption="Cluster profiles"
          rows={clusters}
          rowKey={(c) => String(c.cluster)}
          sort={{ key: 'cluster', desc: false }}
          columns={[
            { key: 'cluster', label: 'Cluster', value: (c) => c.cluster, render: (c) => <strong>{c.name}</strong> },
            { key: 'fy', label: 'Firm-years', numeric: true, value: (c) => c.firm_years },
            { key: 'dax', label: 'In DAX', numeric: true, value: (c) => c.dax_share, render: (c) => pct(c.dax_share) },
            { key: 'board', label: 'Board', numeric: true, value: (c) => c.board_median },
            { key: 'ceo', label: 'CEO median', numeric: true, value: (c) => c.ceo_median, render: (c) => meur(c.ceo_median) },
            { key: 'sectors', label: 'Main sectors', wrap: true, value: (c) => c.sectors[0]?.share, render: (c) => c.sectors.map((s) => `${s.sector} ${pct(s.share)}`).join(' · ') },
            { key: 'examples', label: 'Examples', wrap: true, value: (c) => c.examples.join(', ') },
          ]}
        />
      </Panel>
      <Panel
        title={`Why ${chosen?.k} clusters`}
        caption={`More clusters separate the firms better (silhouette, left) but leave more CEOs without enough peer firms in their cluster (right). With ${chosen?.k} clusters ${pct(chosen?.coverage)} of CEO-years have enough peers${next ? `, with ${next.k} only ${pct(next.coverage)}` : ''}.`}
      >
        <div className="grid-2">
          {(['silhouette', 'coverage'] as const).map((measure) => (
            <Chart
              key={measure}
              label={`${measure} by number of clusters; ${chosen?.k} chosen`}
              render={(width) =>
                Plot.plot({
                  ...base(width, 220),
                  x: { label: narrow(width) ? 'Clusters (K)' : 'Number of clusters (K)', ticks: choice.map((c) => c.k), tickFormat: 'd' },
                  y: { label: measure === 'silhouette' ? '↑ Silhouette' : `↑ CEO-years with ${minPeers}+ peer firms`, grid: true, tickFormat: measure === 'silhouette' ? '.2f' : '.0%' },
                  marks: [
                    Plot.lineY(choice, { x: 'k', y: measure, stroke: 'var(--c-groups)', strokeWidth: 2 }),
                    Plot.dot(choice, {
                      x: 'k',
                      y: measure,
                      r: (c) => (c.chosen ? 6 : 3.5),
                      fill: (c) => (c.chosen ? 'var(--ink)' : 'var(--c-groups)'),
                      stroke: 'var(--surface)',
                      tip: true,
                      title: (c) => `K = ${c.k}: silhouette ${c.silhouette.toFixed(3)}, coverage ${pct(c.coverage)}`,
                    }),
                  ],
                })
              }
            />
          ))}
        </div>
      </Panel>
    </>
  )
}

function Forest({ v }: { v: PeerMethodView }) {
  const fit = v.forest_fit!
  const rows = [...v.importance!].sort((a, b) => b.importance - a.importance)
  if (!rows.length) return null
  return (
    <Panel
      title="What the forest has learned"
      caption={`The forest predicts how far an executive's pay lies from the median of their year and role. Trained without the executive's firm, it explains ${pct(fit.r2)} of these differences (out-of-firm R²; typical error ${logPct(fit.mdae)} against ${logPct(fit.mdae_baseline)} for the median alone). Bars: how much worse its predictions get when a feature is shuffled among the firms of the same year.`}
      note="Correlated features share credit: index and board size both measure size, so shuffling one alone costs less than removing both. The forest's notion of similarity follows these features: firms it predicts alike count as peers."
    >
      <Chart
        label={`The forest relies mostly on ${rows[0].feature}.`}
        render={(width) => {
          const labels = labelAxis(rows.map((r) => r.feature), width)
          return Plot.plot({
            ...base(width, rows.length * 30 + 50),
            marginLeft: labels.marginLeft,
            marginRight: 60,
            x: { label: narrow(width) ? 'Error increase when shuffled' : 'Increase in squared error when shuffled', grid: true, tickFormat: '.0%', ticks: narrow(width) ? 4 : undefined },
            y: { label: null, domain: rows.map((r) => r.feature), tickFormat: labels.tickFormat },
            marks: [
              Plot.barX(rows, { x: 'importance', y: 'feature', fill: 'var(--c-neighbours)', fillOpacity: 0.85, tip: true, title: (r) => `${r.feature}: +${pct(r.importance, 1)}` }),
              Plot.text(rows, { x: 'importance', y: 'feature', text: (r) => pct(r.importance, 1), dx: 6, textAnchor: 'start', fill: 'var(--muted)', fontSize: 11 }),
              Plot.ruleX([0]),
            ],
          })
        }}
      />
    </Panel>
  )
}

// ------------------------------------------------------------------ company page

/** The firm's highest-paid full-year CEO against peers, under every definition and year. */
export function CeoPeers({ firmId, firmName }: { firmId: string; firmName: string }) {
  const overview = useApi<PeerOverview>('/peers')
  const state = useApi<FirmPeerRow[]>(`/firms/${encodeURIComponent(firmId)}/peers`)
  if (state.data && !state.data.length) return null // no full-year CEO
  const both: Loadable<{ o: PeerOverview; rows: FirmPeerRow[] }> = {
    data: overview.data && state.data ? { o: overview.data, rows: state.data } : undefined,
    error: overview.error ?? state.error,
    reload: overview.error ? overview.reload : state.reload,
  }
  return (
    <Async state={both} height={450}>
      {({ o, rows }) => {
        const top = new Map<number, string>()
        for (const r of [...rows].sort((a, b) => b.total - a.total)) if (!top.has(r.year)) top.set(r.year, r.person_id)
        const shown = rows.filter((r) => top.get(r.year) === r.person_id)
        return (
          <Panel
            title="CEO pay against peers"
            caption={`Pay ÷ peer median of the highest-paid full-year CEO under each peer definition. Shaded: at least ${o.high}× the peer median, or at most 1 / ${o.high} of it. The wider a year's spread, the more the verdict depends on who counts as a peer.`}
            note={
              <>
                How each definition picks peers: <a href="#/peers">Peer benchmark</a>.
              </>
            }
          >
            <Legend items={methodLegend(o.methods)} />
            <Chart label={`${firmName} CEO pay relative to peers under ${o.methods.length} definitions, by year`} render={(width) => ceoPeersChart(shown, o, width)} />
          </Panel>
        )
      }}
    </Async>
  )
}

function ceoPeersChart(rows: FirmPeerRow[], o: PeerOverview, width: number) {
  const { color, symbol } = methodStyle(o.methods)
  const names = new Map(o.methods.map((m) => [m.id, m.name]))
  const points = rows.map((r) => ({ ...r, ...r.result, method: names.get(r.result.method) ?? r.result.method }))
  const years = points.map((p) => p.year)
  const [first, last] = [Math.min(...years), Math.max(...years)]
  const axis = ratioAxis(points.map((p) => p.ratio), width)
  return Plot.plot({
    ...base(width, 300),
    x: { ...yearAxis, domain: [first - 0.5, last + 0.5], ticks: Math.min(last - first + 1, narrow(width) ? 5 : 10) },
    y: axis,
    color,
    symbol,
    marks: [
      ...verdictZones(o.high, axis, 'y'),
      Plot.ruleX(points, Plot.groupX({ y1: 'min', y2: 'max' }, { x: 'year', y1: 'ratio', y2: 'ratio', stroke: 'var(--rule)', strokeWidth: 2 })),
      Plot.dot(points, {
        x: 'year',
        y: 'ratio',
        fill: 'method',
        symbol: 'method',
        r: 4.5,
        stroke: 'var(--surface)',
        strokeWidth: 1,
        tip: true,
        title: (p) => `${p.year} · ${p.name}\n${p.method}: ${multiple(p.ratio)} the peer median\n${meur(p.total, 2)} vs ${meur(p.peer_median, 2)} · ${p.n_firms} peer firms\n${p.label}`,
      }),
      ...(first < REGIME_BREAK && last > REGIME_BREAK ? regimeBreak(width) : []),
    ],
  })
}
