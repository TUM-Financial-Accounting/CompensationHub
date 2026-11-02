import * as Plot from '@observablehq/plot'
import { useState } from 'react'

import { COMPONENTS, useApi, type ExecYear, type Person, type Role, type Summary } from '../api'
import { base, type Bar, componentScale, meurAxis, narrow, onPick, roleScale, swarmHeight, yearAxis, yearBar } from '../charts'
import { COMPONENT_COLOR, COMPONENT_LABEL, ROLE_COLOR, ROLE_LABEL, keur, meur } from '../format'
import { Async, Chart, Legend, PageHead, PageSkeleton, Panel, PanelsSkeleton, Segmented, Table, type Column } from '../ui'
import { execColumns } from './columns'
import { PersonForecast } from './Prediction'

type RoleFilter = Role | 'all'

export function Executives() {
  const summary = useApi<Summary>('/summary')
  const [picked, setYear] = useState<number>()
  const [role, setRole] = useState<RoleFilter>('all')
  const [index, setIndex] = useState('all')
  const [query, setQuery] = useState('')
  const year = picked ?? summary.data?.last_year
  const years = summary.data ? range(summary.data.first_year, summary.data.last_year) : []
  const state = useApi<ExecYear[]>(year ? `/executives?year=${year}` : null)
  const indexes = [...new Set(state.data?.map((e) => e.index).filter((i): i is string => !!i))].sort()

  return (
    <>
      <PageHead title="Executives">
        Every management-board member in a year. Hover or tap a dot for details, click or tap it again to open the career.
      </PageHead>
      <div className="controls">
        <label className="field">
          <span>Year</span>
          <select value={year ?? ''} onChange={(e) => setYear(Number(e.target.value))}>
            {years.map((y) => (
              <option key={y}>{y}</option>
            ))}
          </select>
        </label>
        <Segmented
          label="Role"
          value={role}
          onChange={setRole}
          options={[{ value: 'all', label: 'All' }, ...(['CEO', 'CFO', 'Member'] as Role[]).map((r) => ({ value: r, label: ROLE_LABEL[r] }))]}
        />
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
          <input type="search" value={query} onChange={(e) => setQuery(e.target.value)} placeholder="Name or company" />
        </label>
      </div>
      <Async state={state} skeleton={<PanelsSkeleton heights={[250, 560]} />}>
        {(all) => {
          const q = query.trim().toLowerCase()
          const rows = all.filter(
            (e) =>
              (role === 'all' || e.role === role) &&
              (index === 'all' || !indexes.includes(index) || e.index === index) &&
              (!q || e.name.toLowerCase().includes(q) || e.firm.toLowerCase().includes(q)),
          )
          if (!rows.length) return <p className="muted">No executives match these filters.</p>
          return (
            <>
              <Panel
                title={`Total pay, ${year}`}
                caption={`${rows.length} executives. Each dot is one person at one firm; hollow dots served part of the year.`}
              >
                <Legend items={(['CEO', 'CFO', 'Member'] as Role[]).map((r) => ({ label: ROLE_LABEL[r], color: ROLE_COLOR[r] }))} />
                <Chart label={`Distribution of executive pay in ${year}`} render={(width) => swarm(rows, width)} />
              </Panel>
              <Panel title="All executives" caption="Amounts in k€.">
                <Table
                  caption={`Executives ${year}`}
                  tall
                  rows={rows}
                  rowKey={(e) => `${e.person_id}-${e.firm_id}`}
                  sort={{ key: 'total', desc: true }}
                  columns={explorerColumns}
                />
              </Panel>
            </>
          )
        }}
      </Async>
    </>
  )
}

const range = (from: number, to: number) => Array.from({ length: to - from + 1 }, (_, i) => to - i)

const explorerColumns: Column<ExecYear>[] = [
  execColumns[0],
  { key: 'firm', label: 'Company', value: (e) => e.firm, render: (e) => <a href={`#/companies/${e.firm_id}`}>{e.firm}</a> },
  ...execColumns.slice(1),
]

function swarm(rows: ExecYear[], width: number) {
  const data = rows.map((e) => ({ ...e, roleLabel: ROLE_LABEL[e.role] }))
  const r = width < 600 ? 2.6 : 3.4
  const max = Math.max(...data.map((d) => d.total), 1)
  const plot = Plot.plot({
    ...base(width, Math.max(200, swarmHeight(data.map((d) => d.total / max), width - 32, r))),
    marginLeft: 16,
    x: { ...meurAxis('Total pay, € million'), zero: true },
    y: { axis: null },
    color: roleScale,
    marks: [
      Plot.dot(
        data,
        Plot.dodgeY('middle', {
          x: 'total',
          r,
          stroke: 'roleLabel',
          fill: 'roleLabel',
          fillOpacity: (d) => (d.full_year ? 0.85 : 0),
          tip: true,
          title: (d) => `${d.name}\n${d.firm} · ${d.roleLabel}\n${meur(d.total, 2)}${d.full_year ? '' : ` (${d.days} days)`}`,
        }),
      ),
    ],
  })
  onPick<ExecYear>(plot, (d) => (location.hash = `#/people/${d.person_id}`))
  return plot
}

// ------------------------------------------------------------------ person page

export function PersonView({ id }: { id: string }) {
  const state = useApi<Person>(`/people/${encodeURIComponent(id)}`)
  return (
    <Async state={state} skeleton={<PageSkeleton />}>
      {(p) => {
        if (!p.years.length) return <PageHead crumb={<a href="#/executives">Executives</a>} title={p.name}>No pay data for this person.</PageHead>
        const firms = [...new Map(p.years.map((y) => [y.firm_id, y.firm])).entries()]
        const first = p.years[0].year
        const last = p.years[p.years.length - 1].year
        const bars = p.years.flatMap((y) =>
          COMPONENTS.map((c) => ({ year: y.year, firm: y.firm, label: COMPONENT_LABEL[c], value: y[c] ?? 0 })),
        )
        return (
          <>
            <PageHead crumb={<a href="#/executives">Executives</a>} title={p.name}>
              {[
                p.female ? 'Woman' : 'Man',
                p.birth_year && `born ${p.birth_year}`,
                p.german ? 'German' : 'non-German',
                `on the board ${first === last ? first : `${first}–${last}`}`,
              ]
                .filter(Boolean)
                .join(' · ')}
            </PageHead>
            <p>
              {firms.map(([fid, name], i) => (
                <span key={fid}>
                  {i > 0 && ', '}
                  <a href={`#/companies/${fid}`}>{name}</a>
                </span>
              ))}
            </p>
            <Panel title="Pay by year" caption="Total compensation by component, € million. Pension cost and one-time payments excluded.">
              <Legend items={COMPONENTS.map((c) => ({ label: COMPONENT_LABEL[c], color: COMPONENT_COLOR[c] }))} />
              <Chart
                label={`${p.name} pay by year`}
                render={(width) =>
                  Plot.plot({
                    ...base(width, 300),
                    x: { ...yearAxis, ticks: Math.min(p.years.length, narrow(width) ? 5 : 10) },
                    y: meurAxis(),
                    color: componentScale,
                    marks: [
                      Plot.rectY(
                        bars,
                        Plot.stackY({
                          ...yearBar,
                          y: 'value',
                          fill: 'label',
                          order: componentScale.domain as string[],
                          tip: true,
                          title: (b: Bar & { firm: string }) => `${b.year} · ${b.firm}\n${b.label}: ${keur(b.value)} k€`,
                        }),
                      ),
                      Plot.ruleY([0]),
                    ],
                  })
                }
              />
            </Panel>
            <PersonForecast id={p.id} />
            <Panel title="Year by year" caption="Amounts in k€.">
              <Table
                caption={`${p.name} by year`}
                rows={p.years}
                rowKey={(y) => `${y.year}-${y.firm_id}`}
                sort={{ key: 'year', desc: true }}
                columns={[
                  { key: 'year', label: 'Year', value: (y) => y.year },
                  { key: 'firm', label: 'Company', value: (y) => y.firm, render: (y) => <a href={`#/companies/${y.firm_id}`}>{y.firm}</a> },
                  ...execColumns.slice(1),
                ]}
              />
            </Panel>
          </>
        )
      }}
    </Async>
  )
}
