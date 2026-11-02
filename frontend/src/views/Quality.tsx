import * as Plot from '@observablehq/plot'

import { useApi, type Issue, type Quality } from '../api'
import { base, labelAxis, regimeBreak, yearAxis, yearBar } from '../charts'
import { pct } from '../format'
import { Async, Chart, Legend, PageHead, Panel, PanelsSkeleton, Table } from '../ui'

const PALETTE = ['var(--c-ceo)', 'var(--c-sti)', 'var(--c-lti)', 'var(--c-mti)', 'var(--c-cfo)', 'var(--c-fixed)']

const KINDS: { kind: Issue['kind']; title: string; caption: string }[] = [
  { kind: 'decide', title: 'Needs a decision', caption: 'Open curation questions. The dashboard shows the data as-is until they are settled.' },
  { kind: 'fixed', title: 'Handled in the pipeline', caption: 'Corrected automatically when the panel is built (backend/app/panel.py).' },
  { kind: 'note', title: 'Worth knowing', caption: 'Real properties of the data that affect interpretation.' },
]

export function QualityView() {
  const state = useApi<Quality>('/quality')
  return (
    <>
      <PageHead title="Data quality">
        What was loaded, how complete each field is per year, and every problem found while merging the sources.
      </PageHead>
      <Async state={state} skeleton={<PanelsSkeleton heights={[220, 340, 440, 500]} />}>
        {(q) => {
          // Alphabetical keeps colours stable as indices are added; no listing ('Other') last.
          const size = (i: string) => q.universe.filter((u) => u.index === i).reduce((s, u) => s + u.firms, 0)
          const indexes = [...new Set(q.universe.map((u) => u.index))].sort(
            (a, b) => Number(a === 'Other') - Number(b === 'Other') || a.localeCompare(b),
          )
          const colors = indexes.map((i, n) => (i === 'Other' ? 'var(--c-member)' : PALETTE[n % PALETTE.length]))
          return (
            <>
              <Panel title="Sources loaded" caption="Every file set found under data/raw/, in load order.">
                <Table
                  caption="Sources"
                  rows={q.sources}
                  rowKey={(r) => r.label}
                  sort={{ key: 'order', desc: false }}
                  columns={[
                    { key: 'order', label: 'Source', value: (r) => q.sources.indexOf(r), render: (r) => r.label },
                    { key: 'regime', label: 'Disclosure regime', value: (r) => r.regime },
                    { key: 'execs', label: 'Executive-years', numeric: true, value: (r) => r.execs, render: (r) => r.execs.toLocaleString('en-GB') },
                    { key: 'firm_years', label: 'Firm-years', numeric: true, value: (r) => r.firm_years, render: (r) => r.firm_years.toLocaleString('en-GB') },
                  ]}
                />
              </Panel>

              <Panel
                title="Firms per year"
                caption="Firm-years by index listing. Tap or hover a bar for executives and opt-outs."
                note={size('Other') ? `'Other' = firm-years with no index listing in the source (${size('Other')} in total).` : undefined}
              >
                <Legend items={indexes.map((label, i) => ({ label, color: colors[i] }))} />
                <Chart
                  label="Number of firms per year by index"
                  render={(width) =>
                    Plot.plot({
                      ...base(width, 260),
                      x: yearAxis,
                      y: { label: 'Firms', grid: true },
                      color: { domain: indexes, range: colors },
                      marks: [
                        Plot.rectY(
                          q.universe,
                          Plot.stackY({
                            ...yearBar,
                            y: 'firms',
                            fill: 'index',
                            order: indexes,
                            tip: true,
                            title: (u: Quality['universe'][number]) => `${u.year} · ${u.index}\n${u.firms} firms, ${u.opt_out} opted out\n${u.execs} executives`,
                          }),
                        ),
                        Plot.ruleY([0]),
                        ...regimeBreak(width),
                      ],
                    })
                  }
                />
              </Panel>

              <Panel
                title="Field coverage"
                caption="Share of rows with a value, per field and year. Pay fields: executive-years; firm fields: firm-years."
              >
                <Chart
                  minWidth={640}
                  label="Coverage of each field per year"
                  render={(width) => {
                    const fields = [...new Set(q.coverage.map((c) => c.field))]
                    const labels = labelAxis(fields, width, 0.3)
                    const showText = width > 600
                    return Plot.plot({
                      ...base(width, fields.length * 30 + 40),
                      marginLeft: labels.marginLeft,
                      x: { ...yearAxis, type: 'band', axis: 'top', tickFormat: (y: number) => (width > 700 || y % 2 === 0 ? String(y) : '') },
                      y: { label: null, domain: fields, tickFormat: labels.tickFormat },
                      marks: [
                        Plot.cell(q.coverage, { x: 'year', y: 'field', fill: 'var(--grid)', inset: 0.5 }),
                        Plot.cell(q.coverage, {
                          x: 'year',
                          y: 'field',
                          fill: 'var(--c-ceo)',
                          fillOpacity: 'share',
                          inset: 0.5,
                          tip: true,
                          title: (c) => `${c.field}, ${c.year}: ${pct(c.share)}`,
                        }),
                        showText
                          ? Plot.text(q.coverage, {
                              x: 'year',
                              y: 'field',
                              text: (c) => (c.share === 0 ? '' : Math.round(c.share * 100)),
                              fill: (c) => (c.share > 0.55 ? 'var(--on-accent)' : 'var(--ink)'),
                              fontSize: 10,
                            })
                          : null,
                      ],
                    })
                  }}
                />
              </Panel>

              {KINDS.map(({ kind, title, caption }) => (
                <Panel key={kind} title={title} caption={caption}>
                  <ul className="issues">
                    {q.issues
                      .filter((i) => i.kind === kind)
                      .map((i) => (
                        <li key={i.id}>
                          <h3>
                            {i.title}
                            {i.count != null && <span className="badge">{i.count.toLocaleString('en-GB')} rows</span>}
                          </h3>
                          <p>{i.detail}</p>
                        </li>
                      ))}
                  </ul>
                </Panel>
              ))}
            </>
          )
        }}
      </Async>
    </>
  )
}
