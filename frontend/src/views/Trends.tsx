import * as Plot from '@observablehq/plot'
import { useState } from 'react'

import { COMPONENTS, useApi, type Role, type Scope, type Trends } from '../api'
import { REGIME_BREAK, base, componentScale, meurAxis, regimeBreak, roleScale, yearAxis, yearBar } from '../charts'
import { COMPONENT_COLOR, COMPONENT_LABEL, ROLE_LABEL, meur, pct, spell } from '../format'
import { Async, Chart, Legend, PageHead, Panel, PanelsSkeleton, Segmented } from '../ui'

const SCOPES = [
  { value: 'dax' as Scope, label: 'DAX' },
  { value: 'all' as Scope, label: 'All firms' },
]
const ROLES = Object.values(ROLE_LABEL)

export function TrendsView() {
  const [scope, setScope] = useState<Scope>('dax')
  const state = useApi<Trends>(`/trends?scope=${scope}`)

  return (
    <>
      <PageHead title="Pay trends">
        How much management boards are paid, how the package is composed and how far the CEO is ahead of the rest of
        the board. Full-year executives only.
      </PageHead>
      <div className="controls">
        <Segmented label="Firms" options={SCOPES} value={scope} onChange={setScope} />
        {scope === 'all' && (
          <p className="callout">The mix of indices changes over time (see Data quality), so level shifts can reflect which firms are covered.</p>
        )}
      </div>
      <Async state={state} skeleton={<PanelsSkeleton heights={[340, 420, 280]} />}>
        {(t) => (
          <>
            <Panel
              title="Pay level by role"
              caption="Median total compensation (line) and the middle 50 % of executives (band), in € million."
            >
              <Chart label="Median pay by role over time" render={(width) => levels(t, width)} />
            </Panel>

            <Panel
              title="What the package is made of"
              caption={`Share of each component in the total pay of full-year executives whose ${spell(COMPONENTS.length)} components are all reported.`}
              note="Blank components mean 'not reported'. Over time many firms stopped reporting some components, so fewer executives count towards the later years. See Data quality."
            >
              <Legend items={COMPONENTS.map((c) => ({ label: COMPONENT_LABEL[c], color: COMPONENT_COLOR[c] }))} />
              <Chart label="Pay mix over time" render={(width) => mix(t, width)} />
            </Panel>

            <div className="grid-2">
              <Panel title="CEO premium" caption="CEO pay divided by the median pay of the other board members, median across firms.">
                <Chart
                  label="CEO premium over time"
                  render={(width) =>
                    Plot.plot({
                      ...base(width, 240),
                      x: yearAxis,
                      y: { label: 'CEO ÷ median member', grid: true, tickFormat: (v: number) => `${v.toFixed(1)}×` },
                      marks: [
                        Plot.ruleY([1], { stroke: 'var(--rule)' }),
                        Plot.lineY(t.ceo_premium, { x: 'year', y: 'value', stroke: 'var(--c-ceo)', strokeWidth: 2, curve: 'monotone-x' }),
                        Plot.dot(t.ceo_premium, {
                          x: 'year',
                          y: 'value',
                          fill: 'var(--c-ceo)',
                          r: 2.5,
                          tip: true,
                          title: (d) => `${d.year}: ${d.value.toFixed(2)}× (${d.n} firms)`,
                        }),
                        ...regimeBreak(width, ''),
                      ],
                    })
                  }
                />
              </Panel>
              <Panel
                title="Opt-outs from individual disclosure"
                caption="Share of firms reporting only a board total (§286(5) HGB). Abolished for listed firms from 2022."
              >
                <Chart
                  label="Opt-out rate over time"
                  render={(width) =>
                    Plot.plot({
                      ...base(width, 240),
                      x: yearAxis,
                      y: { label: 'Share of firms', grid: true, tickFormat: '%' },
                      marks: [
                        Plot.rectY(t.opt_out_rate, {
                          ...yearBar,
                          y: 'value',
                          fill: 'var(--c-member)',
                          tip: true,
                          title: (d) => `${d.year}: ${pct(d.value)} of ${d.n} firms`,
                        }),
                        Plot.ruleY([0]),
                        ...regimeBreak(width, ''),
                      ],
                    })
                  }
                />
              </Panel>
            </div>
          </>
        )}
      </Async>
    </>
  )
}

function levels(t: Trends, width: number) {
  const rows = t.levels.map((d) => ({ ...d, role: ROLE_LABEL[d.group as Role] }))
  const stacked = width < 720
  const facet = stacked ? { fy: 'role' } : { fx: 'role' }
  return Plot.plot({
    ...base(width, stacked ? 780 : 320),
    x: { ...yearAxis, ticks: 4 },
    y: { ...meurAxis(), zero: true },
    fx: { label: null, domain: ROLES },
    fy: { label: null, domain: ROLES, axis: null },
    color: roleScale,
    marks: [
      Plot.frame({ stroke: 'var(--grid)' }),
      Plot.areaY(rows, { ...facet, x: 'year', y1: 'p25', y2: 'p75', fill: 'role', fillOpacity: 0.18, curve: 'monotone-x' }),
      Plot.lineY(rows, { ...facet, x: 'year', y: 'median', stroke: 'role', strokeWidth: 2, curve: 'monotone-x' }),
      Plot.ruleX([REGIME_BREAK], { stroke: 'var(--muted)', strokeDasharray: '3,3', strokeOpacity: 0.7 }),
      ...(stacked ? [Plot.text(ROLES, { fy: (d: string) => d, text: (d: string) => d, frameAnchor: 'top-left', dx: 8, dy: 8, fontWeight: 600, fill: 'var(--ink)' })] : []),
      Plot.tip(
        rows,
        Plot.pointerX({
          ...facet,
          x: 'year',
          y: 'median',
          title: (d) => `${d.role}, ${d.year} (n = ${d.n})\nMedian ${meur(d.median, 2)}\nMiddle 50 %: ${meur(d.p25)}–${meur(d.p75)}`,
        }),
      ),
    ],
  })
}

function mix(t: Trends, width: number) {
  const rows = t.mix.map((d) => ({ ...d, label: COMPONENT_LABEL[d.component] }))
  return Plot.plot({
    ...base(width, 320),
    x: yearAxis,
    y: { label: 'Share of total pay', grid: true, tickFormat: '%', domain: [0, 1] },
    color: componentScale,
    marks: [
      Plot.rectY(
        rows,
        Plot.stackY({
          ...yearBar,
          y: 'share',
          fill: 'label',
          order: componentScale.domain as string[],
          tip: true,
          title: (d: { year: number; label: string; share: number }) => `${d.year} · ${d.label}: ${pct(d.share, 1)}`,
        }),
      ),
      ...regimeBreak(width),
    ],
  })
}
