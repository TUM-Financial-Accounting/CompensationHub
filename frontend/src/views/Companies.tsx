import * as Plot from '@observablehq/plot'
import { Fragment, useMemo, useState } from 'react'

import { COMPONENTS, useApi, type ExecYear, type Extra, type FirmDetail, type FirmListItem, type Kpi, type EsgKind } from '../api'
import { OPT_OUT_FILL, REGIME_BREAK, base, type Bar, componentScale, meurAxis, onPick, regimeBreak, swarmHeight, yearAxis, yearBar } from '../charts'
import { COMPONENT_COLOR, COMPONENT_LABEL, keur, meur, pct, times } from '../format'
import { Async, Chart, Legend, PageHead, PageSkeleton, Panel, PanelsSkeleton, Segmented, Stat, Table, type Column } from '../ui'
import { execColumns } from './columns'
import { CeoPeers } from './Peers'
import { FirmForecastPanel } from './Prediction'

export function Companies() {
  const state = useApi<FirmListItem[]>('/firms')
  const [query, setQuery] = useState('')
  const [current, setCurrent] = useState(true)
  const [index, setIndex] = useState('all')
  const firms = state.data ?? []
  const last = Math.max(...firms.map((f) => f.last_year))
  const first = Math.min(...firms.map((f) => f.first_year))
  const shown = firms.filter((f) => !current || f.last_year === last)
  const indexes = [...new Set(shown.map((f) => f.index).filter((i): i is string => !!i))].sort()

  return (
    <>
      <PageHead title="Companies">
        Every firm in the panel with its latest reported year. Hover or tap a dot for details, click or tap it again to open the company.
      </PageHead>
      <div className="controls">
        {firms.length > 0 && (
          <Segmented
            label="Show"
            options={[
              { value: 1, label: `In ${last}` },
              { value: 0, label: 'All firms' },
            ]}
            value={current ? 1 : 0}
            onChange={(v) => setCurrent(v === 1)}
          />
        )}
        {indexes.length > 1 && (
          <Segmented
            label="Index"
            value={indexes.includes(index) ? index : 'all'}
            onChange={setIndex}
            options={[{ value: 'all', label: 'All' }, ...indexes.map((i) => ({ value: i, label: i }))]}
          />
        )}
        <label className="field">
          <span>Search</span>
          <input type="search" value={query} onChange={(e) => setQuery(e.target.value)} placeholder="Company or CEO" />
        </label>
      </div>
      <Async state={state} skeleton={<PanelsSkeleton heights={[250, 1400]} />}>
        {() => {
          const q = query.trim().toLowerCase()
          const rows = shown.filter(
            (f) => (index === 'all' || !indexes.includes(index) || f.index === index) && (!q || f.name.toLowerCase().includes(q) || !!f.ceo_name?.toLowerCase().includes(q)),
          )
          if (!rows.length) return <p className="muted">No firms match these filters.</p>
          const period = current ? String(last) : `latest year, ${first}–${last}`
          return (
            <>
              <Panel title={`Board total, ${period}`} caption={`${rows.length} firms. Each dot is one firm: the pay of all its management-board members together.`}>
                <Chart label={`Distribution of board totals across ${rows.length} firms, ${period}`} render={(width) => swarm(rows, width)} />
              </Panel>
              <Panel title={current ? `Firms in ${last}` : 'All firms'} caption="Board total = all management-board members; CEO = highest-paid full-year CEO.">
                <Table caption="Companies" tall rows={rows} rowKey={(f) => f.id} sort={{ key: 'name', desc: false }} columns={firmColumns} />
              </Panel>
            </>
          )
        }}
      </Async>
    </>
  )
}

function swarm(rows: FirmListItem[], width: number) {
  const data = rows.filter((f) => f.board_total != null) as (FirmListItem & { board_total: number })[]
  const r = width < 600 ? 3 : 4
  const max = Math.max(...data.map((d) => d.board_total), 1)
  const plot = Plot.plot({
    ...base(width, Math.max(200, swarmHeight(data.map((d) => d.board_total / max), width - 32, r))),
    marginLeft: 16,
    x: { ...meurAxis('Board total, € million'), zero: true },
    y: { axis: null },
    marks: [
      Plot.dot(
        data,
        Plot.dodgeY('middle', {
          x: 'board_total',
          r,
          fill: 'var(--c-ceo)',
          fillOpacity: 0.85,
          tip: true,
          title: (d) => `${d.name}\n${[d.index, d.last_year].filter(Boolean).join(' · ')}\nBoard ${meur(d.board_total, 2)}${d.ceo_name ? `\nCEO ${d.ceo_name}: ${meur(d.ceo_total, 2)}` : ''}`,
        }),
      ),
    ],
  })
  onPick<FirmListItem>(plot, (d) => (location.hash = `#/companies/${d.id}`))
  return plot
}

const firmColumns: Column<FirmListItem>[] = [
  { key: 'name', label: 'Company', value: (f) => f.name, render: (f) => <a href={`#/companies/${f.id}`}>{f.name}</a> },
  { key: 'years', label: 'Covered', value: (f) => f.first_year, render: (f) => `${f.first_year}–${f.last_year}` },
  { key: 'index', label: 'Index', value: (f) => f.index },
  { key: 'board', label: 'Board total', numeric: true, value: (f) => f.board_total, render: (f) => meur(f.board_total) },
  { key: 'ceo', label: 'CEO', value: (f) => f.ceo_name },
  { key: 'ceo_total', label: 'CEO pay', numeric: true, value: (f) => f.ceo_total, render: (f) => meur(f.ceo_total) },
]

// ------------------------------------------------------------------ company page

export function Company({ id }: { id: string }) {
  const state = useApi<FirmDetail>(`/firms/${encodeURIComponent(id)}`)
  return (
    <Async state={state} skeleton={<PageSkeleton />}>
      {(d) => (d.years.length ? <CompanyPage d={d} /> : <p className="muted">No pay data for {d.firm.name}.</p>)}
    </Async>
  )
}

function CompanyPage({ d }: { d: FirmDetail }) {
  const years = d.years.map((y) => y.year)
  const latest = d.years[d.years.length - 1]
  const [year, setYear] = useState(latest.year)
  const ceoByYear = useMemo(() => topCeoByYear(d.execs), [d.execs])
  const ceo = ceoByYear.get(latest.year)
  const design = d.design[d.design.length - 1]
  const indexSpans = spans(d.years.map((y) => [y.year, y.index ?? 'no index'] as const))
  const more = moreData(d)

  return (
    <>
      <PageHead crumb={<a href="#/companies">Companies</a>} title={d.firm.name}>
        {[d.firm.naics && `NAICS ${d.firm.naics} ${d.firm.naics_title}`, d.firm.industry, d.firm.isin && `ISIN ${d.firm.isin}`, indexSpans]
          .filter(Boolean)
          .join(' · ')}
      </PageHead>

      <div className="stats">
        <Stat label={`Board total ${latest.year}`} value={meur(latest.board_total)} sub={`${latest.n_execs} members`} />
        <Stat label={`CEO ${latest.year}`} value={meur(ceo?.total)} sub={ceo?.name ?? 'not disclosed'} />
        {latest.avg_staff_cost != null && ceo && (
          <Stat
            label="CEO vs. average employee"
            value={times(ceo.total / latest.avg_staff_cost)}
            sub={`${keur(latest.avg_staff_cost)} k€ average staff cost, ${keur(latest.employees)} employees`}
          />
        )}
        {latest.tsr != null && <Stat label={`Shareholder return ${latest.year}`} value={pct(latest.tsr)} sub="share price change plus dividend" />}
      </div>

      <Panel
        title="Board pay by component"
        caption="Sum over all management-board members, € million. Grey bars: the firm opted out of individual disclosure and reported only a board total."
      >
        <Legend
          items={[
            ...COMPONENTS.map((c) => ({ label: COMPONENT_LABEL[c], color: COMPONENT_COLOR[c] })),
            ...(d.years.some((y) => y.opt_out) ? [{ label: 'Total only (opt-out)', color: OPT_OUT_FILL }] : []),
          ]}
        />
        <Chart label={`${d.firm.name} board pay by year`} render={(width) => boardChart(d, width)} />
      </Panel>

      {ceoByYear.size > 0 && (
        <Panel title="CEO pay against the DAX" caption="Total pay of the firm's CEO against the median full-year DAX CEO, € million.">
          <Legend
            items={[
              { label: d.firm.name, color: 'var(--c-ceo)', shape: 'line' },
              { label: 'DAX CEO median', color: 'var(--muted)', shape: 'dash' },
            ]}
          />
          <Chart
            label={`${d.firm.name} CEO pay against the DAX median`}
            render={(width) => {
              const own = [...ceoByYear.values()]
              const span = [d.firm.first_year, d.firm.last_year]
              const dax = d.dax_ceo_median.filter((m) => m.year >= span[0] && m.year <= span[1])
              return Plot.plot({
                ...base(width, 280),
                x: yearAxis,
                y: { ...meurAxis(), zero: true },
                marks: [
                  Plot.lineY(dax, { x: 'year', y: 'value', stroke: 'var(--muted)', strokeDasharray: '4,3' }),
                  Plot.lineY(own, { x: 'year', y: 'total', stroke: 'var(--c-ceo)', strokeWidth: 2 }),
                  Plot.dot(own, {
                    x: 'year',
                    y: 'total',
                    fill: 'var(--c-ceo)',
                    r: 3,
                    tip: true,
                    title: (c: ExecYear) => `${c.year} · ${c.name}\n${meur(c.total, 2)}${c.full_year ? '' : ' (part year)'}`,
                  }),
                  ...regimeBreak(width),
                ],
              })
            }}
          />
        </Panel>
      )}

      <CeoPeers firmId={d.firm.id} firmName={d.firm.name} />

      <FirmForecastPanel id={d.firm.id} />

      <Panel
        title={`Board members, ${year}`}
        caption="Amounts in k€. Part-year members are marked by their days in office."
        controls={
          <label className="field">
            <span>Year</span>
            <select value={year} onChange={(e) => setYear(Number(e.target.value))}>
              {[...years].reverse().map((y) => (
                <option key={y}>{y}</option>
              ))}
            </select>
          </label>
        }
      >
        {d.years.find((y) => y.year === year)?.opt_out ? (
          <p className="callout">
            {d.firm.name} opted out of individual disclosure in {year}; only the board total of {meur(d.years.find((y) => y.year === year)!.board_total)} is known.
          </p>
        ) : (
          <Table
            caption={`${d.firm.name} board members ${year}`}
            rows={d.execs.filter((e) => e.year === year)}
            rowKey={(e) => e.person_id}
            sort={{ key: 'total', desc: true }}
            columns={execColumns}
          />
        )}
      </Panel>

      {design && (
        <Panel
          title={`Plan design, ${design.year}`}
          caption="The CEO's named performance criteria. Only the first three criteria per plan are recorded in the source."
        >
          <dl className="facts">
            <dt>Annual bonus (STI)</dt>
            <dd>
              <Kpis kpis={design.sti_kpis} />
            </dd>
            <dt>Long-term plans</dt>
            <dd>
              <Kpis kpis={design.lt_kpis} />
            </dd>
            <dt>STI cap</dt>
            <dd>{design.sti_cap_pct != null ? `${design.sti_cap_pct.toFixed(0)} % of target` : 'none recorded'}</dd>
            <dt>LTI cap</dt>
            <dd>{design.lti_cap ? 'yes' : 'none recorded'}</dd>
            {(latest.sti_esg_kind || latest.lti_esg_kind) && (
              <>
                <dt>ESG in pay</dt>
                <dd>
                  STI: {esgText(latest.sti_esg_share, latest.sti_esg_kind)} · LTI: {esgText(latest.lti_esg_share, latest.lti_esg_kind)}
                </dd>
              </>
            )}
          </dl>
        </Panel>
      )}

      {more.length > 0 && (
        <Panel title="More data" caption="From additional tables in data/raw/tables/ and data/reference/tables/.">
          <dl className="facts">
            {more.map(([k, v]) => (
              <Fragment key={k}>
                <dt>{k}</dt>
                <dd>{v}</dd>
              </Fragment>
            ))}
          </dl>
        </Panel>
      )}
    </>
  )
}

/** Firm attributes plus the latest value of each firm-year column from dropped-in tables. */
function moreData(d: FirmDetail): [string, string][] {
  const fmt = (v: Extra[string]) => (typeof v === 'number' ? v.toLocaleString('en-GB') : String(v))
  const rows: [string, string][] = Object.entries(d.firm.attributes)
    .filter(([, v]) => v != null)
    .map(([k, v]) => [k, fmt(v)])
  const keys = new Set(d.years.flatMap((y) => Object.keys(y.extra)))
  for (const key of keys) {
    const latest = [...d.years].reverse().find((y) => y.extra[key] != null)
    if (latest) rows.push([key, `${fmt(latest.extra[key])} (${latest.year})`])
  }
  return rows
}

function Kpis({ kpis }: { kpis: Kpi[] }) {
  if (!kpis.length) return <span className="muted">none recorded</span>
  return (
    <div className="tags">
      {kpis.map((k) => (
        <span key={k.name} className="tag" title={`Category: ${k.categories.join(', ')}`}>
          {k.name}
        </span>
      ))}
    </div>
  )
}

function boardChart(d: FirmDetail, width: number) {
  const disclosed = d.years
    .filter((y) => !y.opt_out)
    .flatMap((y) =>
      COMPONENTS.map((c) => ({
        year: y.year,
        label: COMPONENT_LABEL[c],
        value: d.execs.filter((e) => e.year === y.year).reduce((s, e) => s + (e[c] ?? 0), 0),
      })),
    )
  const optOut = d.years.filter((y) => y.opt_out)
  return Plot.plot({
    ...base(width, 300),
    x: yearAxis,
    y: { ...meurAxis() },
    color: componentScale,
    marks: [
      Plot.rectY(optOut, { ...yearBar, y: 'board_total', fill: OPT_OUT_FILL, tip: true, title: (y) => `${y.year} · opt-out\nBoard total ${meur(y.board_total, 2)}` }),
      Plot.rectY(
        disclosed,
        Plot.stackY({
          ...yearBar,
          y: 'value',
          fill: 'label',
          order: componentScale.domain as string[],
          tip: true,
          title: (r: Bar) => `${r.year} · ${r.label}\n${meur(r.value, 2)}`,
        }),
      ),
      Plot.ruleY([0]),
      ...(d.firm.first_year < REGIME_BREAK && d.firm.last_year > REGIME_BREAK ? regimeBreak(width) : []),
    ],
  })
}

/** Highest-paid CEO per year, preferring full-year CEOs (hand-overs list two). */
function topCeoByYear(execs: ExecYear[]) {
  const byYear = new Map<number, ExecYear>()
  for (const e of execs) {
    if (e.role !== 'CEO') continue
    const cur = byYear.get(e.year)
    if (!cur || (e.full_year && !cur.full_year) || (e.full_year === cur.full_year && e.total > cur.total)) byYear.set(e.year, e)
  }
  return new Map([...byYear].sort(([a], [b]) => a - b))
}

/** [[2006,'DAX'],[2007,'DAX'],[2008,'MDAX']] → "DAX 2006–2007, MDAX 2008" */
function spans(pairs: (readonly [number, string])[]) {
  const out: string[] = []
  let start = 0
  pairs.forEach(([year, label], i) => {
    const next = pairs[i + 1]
    if (next && next[1] === label && next[0] === year + 1) return
    const [from] = pairs[start]
    out.push(`${label} ${from === year ? from : `${from}–${year}`}`)
    start = i + 1
  })
  return out.join(', ')
}

/** ESG in one plan: a target weight, a multiplier on the payout, or both. */
function esgText(share: number | null, kind: EsgKind | null) {
  if (kind === 'multiplier') return 'multiplier on the payout'
  if (!kind) return share ? `${share.toFixed(0)} %` : 'none'
  if (share == null) return kind
  return `${share.toFixed(0)} % target weight${kind === 'target + multiplier' ? ' + multiplier' : ''}`
}
