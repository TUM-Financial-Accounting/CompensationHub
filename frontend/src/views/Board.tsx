import * as Plot from '@observablehq/plot'
import { useState } from 'react'

import { useApi, type Board as BoardData, type Scope, type YearValue } from '../api'
import { base, labelAxis, narrow, regimeBreak, yearAxis } from '../charts'
import { keur, meur, pct, signed, times } from '../format'
import { Async, Chart, Legend, PageHead, Panel, PanelsSkeleton, Segmented, Stat } from '../ui'

export function Board() {
  const state = useApi<BoardData>('/board')
  const [scope, setScope] = useState<Scope>('dax')
  const [picked, setYear] = useState<number>()

  return (
    <>
      <PageHead title="Board & workforce">
        Who sits on management boards, and how CEO pay compares with the firm's own staff and with the return its
        shareholders earned.
      </PageHead>
      <Async state={state} skeleton={<PanelsSkeleton heights={[380, 700, 480]} />}>
        {(b) => {
          const years = [...new Set(b.ceos.map((c) => c.year))].sort()
          if (!years.length) return <p className="muted">No board data.</p>
          const year = picked ?? years[years.length - 1]
          const diversity = b.diversity.filter((d) => d.scope === scope)
          const ceos = b.ceos.filter((c) => c.year === year)
          const hiring = (role: 'Board' | 'CEO') => b.hiring.filter((h) => h.role === role).at(-1)
          const latest = diversity.at(-1)
          return (
            <>
              <Panel
                title="Board composition"
                caption="Share of management-board members, all members including part-year."
                controls={
                  <Segmented
                    label="Firms"
                    options={[
                      { value: 'dax' as Scope, label: 'DAX' },
                      { value: 'all' as Scope, label: 'All firms' },
                    ]}
                    value={scope}
                    onChange={setScope}
                  />
                }
              >
                <Legend
                  items={[
                    { label: 'Women', color: 'var(--c-mti)', shape: 'line' },
                    { label: 'Non-German nationality', color: 'var(--c-fixed)', shape: 'line' },
                  ]}
                />
                <Chart
                  label="Share of women and non-German board members over time"
                  render={(width) => {
                    const long = diversity.flatMap((d) => [
                      { year: d.year, metric: 'Women', value: d.female_share, n: d.n },
                      { year: d.year, metric: 'Non-German nationality', value: d.non_german_share, n: d.n },
                    ])
                    return Plot.plot({
                      ...base(width, 300),
                      x: yearAxis,
                      y: { label: narrow(width) ? 'Share of members' : 'Share of board members', grid: true, tickFormat: '%', domain: [0, Math.max(0.5, ...long.map((d) => d.value))] },
                      color: { domain: ['Women', 'Non-German nationality'], range: ['var(--c-mti)', 'var(--c-fixed)'] },
                      marks: [
                        Plot.lineY(long, { x: 'year', y: 'value', stroke: 'metric', strokeWidth: 2, curve: 'monotone-x' }),
                        Plot.dot(long, {
                          x: 'year',
                          y: 'value',
                          fill: 'metric',
                          r: 2.5,
                          tip: true,
                          title: (d) => `${d.year} · ${d.metric}: ${pct(d.value, 1)} of ${d.n}`,
                        }),
                        ...regimeBreak(width),
                      ],
                    })
                  }}
                />
              </Panel>

              <div className="stats">
                {latest && (
                  <Stat label={`Median board age ${latest.year}`} value={`${latest.median_age ?? '–'}`} sub={`${diversity[0].median_age ?? '–'} in ${diversity[0].year}`} />
                )}
                {hiring('CEO') && (
                  <Stat
                    label={`CEOs hired externally ${hiring('CEO')!.year}`}
                    value={pct(hiring('CEO')!.external_share)}
                    sub={`${hiring('CEO')!.n} DAX CEOs with known origin`}
                  />
                )}
                {hiring('Board') && (
                  <Stat
                    label={`Members hired externally ${hiring('Board')!.year}`}
                    value={pct(hiring('Board')!.external_share)}
                    sub={`${hiring('Board')!.n} DAX board members`}
                  />
                )}
              </div>

              <div className="controls">
                <Segmented label="Year" options={years.map((y) => ({ value: y, label: String(y) }))} value={year} onChange={setYear} />
              </div>

              <Panel
                title="CEO pay against average staff cost"
                caption="Full-year CEO total pay divided by personnel expenses per employee. Personnel expenses include social security and pension cost, so the ratio is conservative."
              >
                <Chart label={`CEO to employee pay ratio ${year}`} render={(width) => ratioChart(ceos, b.pay_ratio_median.find((m) => m.year === year)?.value, width)} />
              </Panel>

              <Panel
                title="Pay change against shareholder return"
                caption="Change in CEO total pay against the prior year (same CEO, both years full-year) and total shareholder return of the year."
                note="TSR from the DSW workbooks (share price change plus dividend). Pay figures are granted amounts, which often reflect earlier performance periods."
              >
                <Chart label={`CEO pay change against TSR ${year}`} render={(width) => tsrChart(ceos, b.tsr_pay_corr.find((m) => m.year === year), width)} />
              </Panel>
            </>
          )
        }}
      </Async>
    </>
  )
}

type Ceo = BoardData['ceos'][number]

function ratioChart(ceos: Ceo[], med: number | undefined, width: number) {
  const rows = ceos.filter((c) => c.pay_ratio != null).sort((a, b) => b.pay_ratio! - a.pay_ratio!)
  const labels = labelAxis(rows.map((r) => r.firm), width)
  return Plot.plot({
    ...base(width, rows.length * 17 + 50),
    marginLeft: labels.marginLeft,
    marginRight: 40,
    x: { label: narrow(width) ? 'CEO pay ÷ staff cost' : 'CEO pay ÷ average staff cost', grid: true, tickFormat: (v: number) => `${v}×`, ticks: narrow(width) ? 2 : undefined },
    y: { label: null, domain: rows.map((r) => r.firm), tickFormat: labels.tickFormat },
    marks: [
      Plot.barX(rows, {
        x: 'pay_ratio',
        y: 'firm',
        fill: 'var(--c-ceo)',
        fillOpacity: 0.85,
        tip: true,
        title: (c) => `${c.firm} · ${c.name}\n${meur(c.total, 2)} vs. ${keur(c.avg_staff_cost)} k€ per employee\n${times(c.pay_ratio)}`,
      }),
      Plot.text(rows, { x: 'pay_ratio', y: 'firm', text: (c) => times(c.pay_ratio), dx: 4, textAnchor: 'start', fill: 'var(--muted)', fontSize: 11 }),
      med != null ? Plot.ruleX([med], { stroke: 'var(--ink)', strokeDasharray: '3,3' }) : null,
      med != null ? Plot.text([med], { x: (v: number) => v, frameAnchor: 'top', dy: -12, text: () => `median ${times(med)}`, fill: 'var(--ink)', fontSize: 11 }) : null,
      Plot.ruleX([0]),
    ],
  })
}

function tsrChart(ceos: Ceo[], corr: YearValue | undefined, width: number) {
  const rows = ceos.filter((c) => c.tsr != null && c.pay_change != null)
  const [lo, hi] = [Math.min(...rows.map((c) => c.tsr!)), Math.max(...rows.map((c) => c.tsr!))]
  const side = (c: Ceo) => ((c.tsr! - lo) / (hi - lo) > 0.85 ? 'end' : (c.tsr! - lo) / (hi - lo) < 0.1 ? 'start' : 'middle') // keeps labels inside the plot
  const outliers = rows.filter((c) => Math.abs(c.pay_change!) > 0.4 || Math.abs(c.tsr!) > 0.5)
  return Plot.plot({
    ...base(width, narrow(width) ? 340 : 380),
    x: { label: 'Total shareholder return →', grid: true, tickFormat: '+.0%', ticks: narrow(width) ? 4 : undefined },
    y: { label: '↑ CEO pay change', grid: true, tickFormat: '+.0%' },
    marks: [
      Plot.ruleX([0], { stroke: 'var(--rule)' }),
      Plot.ruleY([0], { stroke: 'var(--rule)' }),
      Plot.dot(rows, {
        x: 'tsr',
        y: 'pay_change',
        r: 5,
        fill: 'var(--c-ceo)',
        fillOpacity: 0.75,
        tip: true,
        title: (c) => `${c.firm} · ${c.name}\nTSR ${signed(c.tsr)} · pay ${signed(c.pay_change)}`,
      }),
      ...(['start', 'middle', 'end'] as const).map((textAnchor) =>
        Plot.text(
          outliers.filter((c) => side(c) === textAnchor),
          { x: 'tsr', y: 'pay_change', text: 'firm', textAnchor, dy: -9, fontSize: 10, fill: 'var(--muted)' },
        ),
      ),
      corr ? Plot.text([`n = ${corr.n} · Pearson r = ${corr.value.toFixed(2)}`], { frameAnchor: 'top-right', dy: 4, fill: 'var(--muted)' }) : null,
    ],
  })
}
