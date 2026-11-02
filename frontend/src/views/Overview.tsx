import * as Plot from '@observablehq/plot'

import { useApi, type PeerOverview, type Summary } from '../api'
import { base, meurAxis, narrow, regimeBreak, yearAxis } from '../charts'
import { meur, pct, spell, times } from '../format'
import { Async, Chart, Legend, PageHead, Panel, Stat } from '../ui'

const views = (peerDefinitions: number | undefined) => [
  ['trends', 'Pay trends', 'Level, mix and dispersion of board pay over time, by role and index.'],
  ['companies', 'Companies', 'One page per firm: board pay history, CEO against the DAX, plan design.'],
  ['executives', 'Executives', 'Every board member in a given year, and each career across years.'],
  [
    'peers',
    'Peer benchmark',
    `Pay against comparable firms under ${peerDefinitions ? `${spell(peerDefinitions)} peer definitions` : 'several peer definitions'}, and how much the verdict depends on the choice.`,
  ],
  ['design', 'Pay design', 'What bonuses are tied to, caps and ESG targets under §162 AktG.'],
  ['board', 'Board & workforce', 'Gender and nationality mix, CEO-to-employee pay ratio, pay vs. shareholder return.'],
  ['data', 'Data quality', 'Coverage per field and year, and every issue found while harmonising the sources.'],
]

export function Overview() {
  const state = useApi<Summary>('/summary')
  const peers = useApi<PeerOverview>('/peers')
  return (
    <>
      <PageHead title="How DAX management boards are paid">
        A harmonised panel of management-board compensation, built from the chair's legacy panel (DAX and MDAX) and the
        DSW §162 AktG workbooks (DAX). See Data quality for what each source covers.
      </PageHead>
      <Async state={state} height={700}>
        {(s) => (
          <>
            <div className="stats">
              <Stat
                label={`DAX CEO, median ${s.last_year}`}
                value={meur(s.ceo_median_last)}
                sub={`${meur(s.ceo_median_first)} in ${s.first_year} (+${pct(s.ceo_median_last / s.ceo_median_first - 1)}, not inflation-adjusted)`}
              />
              <Stat
                label={`Women on DAX boards ${s.last_year}`}
                value={pct(s.female_share_last)}
                sub={`${pct(s.female_share_first)} in ${s.first_year}`}
              />
              <Stat
                label="CEO pay vs. average employee"
                value={times(s.pay_ratio_median_last)}
                sub={`median across DAX firms, ${s.last_year}`}
              />
              <Stat
                label="Coverage"
                value={`${s.n_firms} firms`}
                sub={`${s.n_people.toLocaleString('en-GB')} executives · ${s.n_exec_years.toLocaleString('en-GB')} executive-years`}
              />
            </div>
            <Panel
              title={`DAX CEO pay, ${s.first_year}–${s.last_year}`}
              caption="Total compensation of full-year DAX CEOs: fixed salary, annual and multi-year bonus, share-based pay and benefits. Pension cost and one-time payments excluded. Nominal euros."
              note="From 2022 the source switches to §162 AktG 'granted and owed' disclosure; amounts stay in the same unit but definitions of multi-year and share-based pay differ."
            >
              <Legend
                items={[
                  { label: 'Median', color: 'var(--c-ceo)', shape: 'line' },
                  { label: 'Middle 50 %', color: 'color-mix(in srgb, var(--c-band) 28%, transparent)' },
                  { label: 'Middle 80 %', color: 'color-mix(in srgb, var(--c-band) 12%, transparent)' },
                ]}
              />
              <Chart
                label={`Median DAX CEO pay rose from ${meur(s.ceo_median_first)} in ${s.first_year} to ${meur(s.ceo_median_last)} in ${s.last_year}.`}
                render={(width) =>
                  Plot.plot({
                    ...base(width, narrow(width) ? 320 : 380),
                    x: yearAxis,
                    y: { ...meurAxis(), zero: true },
                    marks: [
                      Plot.areaY(s.ceo_pay, { x: 'year', y1: 'p10', y2: 'p90', fill: 'var(--c-band)', fillOpacity: 0.12, curve: 'monotone-x' }),
                      Plot.areaY(s.ceo_pay, { x: 'year', y1: 'p25', y2: 'p75', fill: 'var(--c-band)', fillOpacity: 0.22, curve: 'monotone-x' }),
                      Plot.lineY(s.ceo_pay, { x: 'year', y: 'median', stroke: 'var(--c-ceo)', strokeWidth: 2.25, curve: 'monotone-x' }),
                      Plot.dot(s.ceo_pay, { x: 'year', y: 'median', fill: 'var(--c-ceo)', r: 3 }),
                      ...regimeBreak(width),
                      Plot.tip(
                        s.ceo_pay,
                        Plot.pointerX({
                          x: 'year',
                          y: 'median',
                          title: (d) =>
                            `${d.year} · ${d.n} CEOs\nMedian ${meur(d.median, 2)}\nMiddle 50 %: ${meur(d.p25)}–${meur(d.p75)}\nMiddle 80 %: ${meur(d.p10)}–${meur(d.p90)}`,
                        }),
                      ),
                    ],
                  })
                }
              />
            </Panel>
          </>
        )}
      </Async>
      <nav aria-label="Views" className="views">
        {views(peers.data?.methods.length).map(([path, title, text]) => (
          <a key={path} href={`#/${path}`}>
            <strong>{title}</strong>
            <span>{text}</span>
          </a>
        ))}
      </nav>
    </>
  )
}
