import * as Plot from '@observablehq/plot'
import { useState } from 'react'

import { useApi, type Design as DesignData, type Plan } from '../api'
import { base, labelAxis, narrow, swarmHeight } from '../charts'
import { meur, pct } from '../format'
import { Async, Chart, Legend, PageHead, Panel, PanelsSkeleton, Segmented, Stat } from '../ui'

const PLANS: Plan[] = ['STI', 'Long-term']
const PLAN_LABEL: Record<Plan, string> = { STI: 'Annual bonus (STI)', 'Long-term': 'Long-term (MTI + LTI)' }
const PLAN_COLOR: Record<Plan, string> = { STI: 'var(--c-sti)', 'Long-term': 'var(--c-lti)' }

export function Design() {
  const state = useApi<DesignData>('/design')
  const [picked, setYear] = useState<number>()
  const [plan, setPlan] = useState<Plan>('STI')

  return (
    <>
      <PageHead title="Pay design under §162 AktG">
        Since 2022 firms disclose what variable pay depends on, how it is capped and how much of it is tied to ESG
        targets. DAX firms.
      </PageHead>
      <Async state={state} skeleton={<PanelsSkeleton heights={[500, 600, 600]} />}>
        {(d) => {
          const years = [...new Set(d.kpi_usage.map((u) => u.year))].sort()
          if (!years.length) return <p className="muted">No design data.</p>
          const year = picked ?? years[years.length - 1]
          const usage = d.kpi_usage.filter((u) => u.year === year)
          const ceos = d.ceos.filter((c) => c.year === year)
          const categories = [...new Set(d.kpi_usage.map((u) => u.category))]
          const byShare = categories.sort(
            (a, b) => share(usage, 'STI', b) + share(usage, 'Long-term', b) - share(usage, 'STI', a) - share(usage, 'Long-term', a),
          )
          const caps = d.caps.find((c) => c.year === year)
          const capValues = ceos.flatMap((c) => (c.sti_cap_pct == null ? [] : [c.sti_cap_pct]))
          const hasEsg = ceos.some((c) => weight(c, 'STI') != null || weight(c, 'Long-term') != null)
          const multipliers = ceos.flatMap((c) =>
            PLANS.filter((p) => kind(c, p) === 'multiplier').map((p) => `${c.firm} (${p === 'STI' ? 'bonus' : 'LTI'})`),
          )
          return (
            <>
              <div className="controls">
                <Segmented label="Year" options={years.map((y) => ({ value: y, label: String(y) }))} value={year} onChange={setYear} />
              </div>
              {caps && (
                <div className="stats">
                  <Stat label="CEOs with a capped bonus" value={pct(caps.sti_capped / caps.n)} sub={`${caps.sti_capped} of ${caps.n} DAX CEOs, ${year}`} />
                  <Stat label="CEOs with a capped LTI" value={pct(caps.lti_capped / caps.n)} sub={`${caps.lti_capped} of ${caps.n}`} />
                  <Stat label="Median bonus cap" value={`${caps.sti_cap_median?.toFixed(0) ?? '–'} %`} sub="of the target bonus" />
                </div>
              )}

              <Panel
                title="What variable pay is tied to"
                caption="Share of DAX firms whose CEO plan names at least one criterion of the category. The firms' free-text criteria are mapped to categories by an AI-assisted list, not yet checked by hand; composite criteria count in each of their categories. Only the first three criteria per plan are recorded."
              >
                <Legend items={PLANS.map((p) => ({ label: PLAN_LABEL[p], color: PLAN_COLOR[p] }))} />
                <Chart
                  label={`KPI categories used in ${year}`}
                  render={(width) => {
                    const labels = labelAxis(byShare, width, 0.4)
                    return Plot.plot({
                      ...base(width, byShare.length * 46 + 40),
                      marginLeft: labels.marginLeft,
                      marginRight: 48,
                      x: { label: 'Share of firms', grid: true, tickFormat: '%', domain: [0, 1], ticks: narrow(width) ? 3 : undefined },
                      y: { axis: null, domain: PLANS },
                      fy: { label: null, domain: byShare, padding: 0.25, axis: 'left', tickFormat: labels.tickFormat },
                      color: { domain: PLANS, range: PLANS.map((p) => PLAN_COLOR[p]) },
                      marks: [
                        Plot.barX(usage, {
                          x: 'share',
                          y: 'plan',
                          fy: 'category',
                          fill: 'plan',
                          tip: true,
                          title: (u) => `${PLAN_LABEL[u.plan as Plan]} · ${u.category}\n${u.n} firms (${pct(u.share)})`,
                        }),
                        Plot.text(usage, {
                          x: 'share',
                          y: 'plan',
                          fy: 'category',
                          text: (u) => pct(u.share),
                          dx: 4,
                          textAnchor: 'start',
                          fill: 'var(--muted)',
                        }),
                        Plot.ruleX([0]),
                      ],
                    })
                  }}
                />
              </Panel>

              <Panel
                title="Criteria by firm"
                caption="Tap or hover a cell for the criteria as the firm names them."
                controls={
                  <Segmented label="Plan" options={PLANS.map((p) => ({ value: p, label: PLAN_LABEL[p] }))} value={plan} onChange={setPlan} />
                }
              >
                <Chart minWidth={560} label={`KPI categories by firm, ${plan}, ${year}`} render={(width) => matrix(d, year, plan, byShare, width)} />
              </Panel>

              <div className="grid-2">
                <Panel title="Bonus caps" caption="Maximum annual bonus as a share of the target bonus, CEO plans. Each dot is one firm.">
                  <Chart
                    label={`Bonus caps ${year}`}
                    render={(width) =>
                      Plot.plot({
                        ...base(width, Math.max(200, swarmHeight(capValues.map((c) => c / Math.max(...capValues)), width - 32, 5))),
                        marginLeft: 16,
                        x: { label: 'Cap, % of target bonus', grid: true, ticks: narrow(width) ? 4 : undefined },
                        y: { axis: null },
                        marks: [
                          Plot.dot(
                            ceos.filter((c) => c.sti_cap_pct != null),
                            Plot.dodgeY('middle', {
                              x: 'sti_cap_pct',
                              r: 5,
                              fill: 'var(--c-sti)',
                              fillOpacity: 0.85,
                              tip: true,
                              title: (c) => `${c.firm}: ${c.sti_cap_pct} %`,
                            }),
                          ),
                        ],
                      })
                    }
                  />
                </Panel>
                <Panel
                  title="ESG weight in variable pay"
                  caption="Weight of ESG targets in the annual bonus and in the LTI. Plans where ESG only works as a multiplier on the payout have no ESG weight; they are listed below."
                  note={multipliers.length ? `ESG as a multiplier only: ${multipliers.join(', ')}.` : undefined}
                >
                  {!hasEsg ? (
                    <p className="callout">No comparable ESG weights are recorded for {year} (see Data quality).</p>
                  ) : (
                    <>
                      <Legend items={PLANS.map((p) => ({ label: p === 'STI' ? 'Annual bonus' : 'LTI', color: PLAN_COLOR[p] }))} />
                      <Chart label={`ESG share of variable pay ${year}`} render={(width) => esg(ceos, width)} />
                    </>
                  )}
                </Panel>
              </div>

              <Panel
                title="CEO pay against the maximum"
                caption="Total pay plus pension cost as a share of the maximum remuneration set in the remuneration system (§87a AktG)."
              >
                {ceos.some((c) => c.max_comp) ? (
                  <Chart label={`CEO pay as share of maximum ${year}`} render={(width) => maxChart(ceos, width)} />
                ) : (
                  <p className="callout">Maximum remuneration is not recorded for {year}.</p>
                )}
              </Panel>
            </>
          )
        }}
      </Async>
    </>
  )
}

const share = (usage: DesignData['kpi_usage'], plan: Plan, category: string) =>
  usage.find((u) => u.plan === plan && u.category === category)?.share ?? 0

function matrix(d: DesignData, year: number, plan: Plan, categories: string[], width: number) {
  const cells = d.kpi_cells.filter((c) => c.year === year && c.plan === plan)
  const firms = [...new Set(d.ceos.filter((c) => c.year === year).map((c) => c.firm))].sort((a, b) => a.localeCompare(b))
  const upright = width < 700
  const labels = labelAxis(firms, width, 0.3)
  return Plot.plot({
    ...base(width, firms.length * 18 + (upright ? 170 : 110)),
    marginLeft: labels.marginLeft,
    marginRight: upright ? 16 : 90, // tilted labels run on past the last column
    marginTop: upright ? 150 : 90,
    x: { label: null, domain: categories, axis: 'top', tickRotate: upright ? -90 : -30, padding: 0.12, tickFormat: upright ? (c: string) => (c.length > 22 ? `${c.slice(0, 21)}…` : c) : undefined },
    y: { label: null, domain: firms, tickFormat: labels.tickFormat },
    marks: [
      Plot.cell(firms.flatMap((firm) => categories.map((category) => ({ firm, category }))), {
        x: 'category',
        y: 'firm',
        fill: 'var(--grid)',
        inset: 1,
      }),
      Plot.cell(cells, {
        x: 'category',
        y: 'firm',
        fill: PLAN_COLOR[plan],
        inset: 1,
        tip: true,
        title: (c) => `${c.firm} · ${c.category}\n${c.names.join('\n')}`,
      }),
    ],
  })
}

type DesignCeo = DesignData['ceos'][number]

function kind(c: DesignCeo, plan: Plan) {
  return plan === 'STI' ? c.sti_esg_kind : c.lti_esg_kind
}

/** ESG target weight of a plan, in %; null when ESG enters only as a multiplier or not at all. */
function weight(c: DesignCeo, plan: Plan) {
  const k = kind(c, plan)
  return k === 'target' || k === 'target + multiplier' ? (plan === 'STI' ? c.sti_esg_share : c.lti_esg_share) : null
}

function esg(ceos: DesignCeo[], width: number) {
  const total = (c: DesignCeo) => (weight(c, 'STI') ?? 0) + (weight(c, 'Long-term') ?? 0)
  const rows = ceos.filter((c) => total(c) > 0).sort((a, b) => total(b) - total(a))
  const long = rows.flatMap((c) =>
    PLANS.map((plan) => ({ firm: c.firm, plan, value: weight(c, plan), both: kind(c, plan) === 'target + multiplier' })),
  ).filter((r): r is typeof r & { value: number } => r.value != null && r.value > 0)
  const extent = (c: DesignCeo) => PLANS.map((p) => weight(c, p)).filter((v): v is number => v != null && v > 0)
  const labels = labelAxis(rows.map((r) => r.firm), width)
  return Plot.plot({
    ...base(width, rows.length * 16 + 50),
    marginLeft: labels.marginLeft,
    x: { label: 'ESG target weight, %', grid: true, domain: [0, 100], ticks: narrow(width) ? 4 : undefined },
    y: { label: null, domain: rows.map((r) => r.firm), tickFormat: labels.tickFormat },
    color: { domain: PLANS, range: PLANS.map((p) => PLAN_COLOR[p]) },
    marks: [
      Plot.ruleY(rows, { y: 'firm', x1: (c) => Math.min(...extent(c)), x2: (c) => Math.max(...extent(c)), stroke: 'var(--rule)' }),
      Plot.dot(long, {
        x: 'value',
        y: 'firm',
        fill: 'plan',
        r: 4,
        tip: true,
        title: (r) => `${r.firm} · ${r.plan === 'STI' ? 'bonus' : 'LTI'}: ${r.value.toFixed(0)} %${r.both ? '\nplus an ESG multiplier on the payout' : ''}`,
      }),
    ],
  })
}

function maxChart(ceos: DesignData['ceos'], width: number) {
  const rows = ceos
    .filter((c) => c.max_comp)
    .map((c) => ({ ...c, used: (c.total + (c.pension ?? 0)) / c.max_comp! }))
    .sort((a, b) => b.used - a.used)
  const labels = labelAxis(rows.map((r) => r.firm), width)
  return Plot.plot({
    ...base(width, rows.length * 16 + 50),
    marginLeft: labels.marginLeft,
    x: { label: narrow(width) ? 'Share of maximum' : 'Share of maximum remuneration', grid: true, tickFormat: '%', domain: [0, 1], ticks: narrow(width) ? 3 : undefined },
    y: { label: null, domain: rows.map((r) => r.firm), tickFormat: labels.tickFormat },
    marks: [
      Plot.barX(rows, {
        x: 'used',
        y: 'firm',
        fill: 'var(--c-ceo)',
        fillOpacity: 0.85,
        tip: true,
        title: (r) => `${r.firm} · ${r.name}\n${meur(r.total + (r.pension ?? 0), 2)} of ${meur(r.max_comp, 1)} (${pct(r.used)})`,
      }),
      Plot.ruleX([0]),
    ],
  })
}
