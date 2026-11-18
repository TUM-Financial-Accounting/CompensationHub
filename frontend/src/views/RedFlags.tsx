import * as Plot from '@observablehq/plot'
import { useState } from 'react'

import { useApi, type FirmFlag, type FlagDetector, type FlaggedExec, type FlagKind, type FlagList, type FlagOverview, type Loadable, type Role } from '../api'
import { FLAG_FAMILY_COLOR, FLAG_FAMILY_LABEL, base, labelAxis, methodStyle, narrow } from '../charts'
import { ROLE_LABEL, keur, pct, spell } from '../format'
import { Async, Chart, Legend, Mark, PageHead, Panel, PanelsSkeleton, Segmented, Skeleton, Stat, Table } from '../ui'

// Every number on this page comes from backend/app/redflags.py; see docs/redflags.md for the method.

/** Colour carries the family (rules, context, structure), the symbol the detector within it. Rules get a plain
 *  square: they are never drawn as dots. */
function styles(o: FlagOverview) {
  const stats = o.detectors.filter((d) => d.family !== 'rule')
  const { style, color, symbol } = methodStyle(stats, FLAG_FAMILY_COLOR)
  const byId = new Map<string, { name: string; color: string; symbol?: (typeof style)[number]['symbol'] }>([
    ...o.detectors.filter((d) => d.family === 'rule').map((d) => [d.id, { name: d.name, color: FLAG_FAMILY_COLOR.rule }] as const),
    ...stats.map((d, i) => [d.id, style[i]] as const),
  ])
  const mark = (id: string, className?: string) => {
    const s = byId.get(id)
    return s ? <Mark key={id} color={s.color} symbol={s.symbol} className={className} /> : null
  }
  return { byId, mark, color, symbol, stats, legend: style.map((s) => ({ label: s.name, color: s.color, shape: s.symbol })) }
}

/** Value of a planted anomaly's size: "2×" or "100%". */
const sizeText = (k: FlagKind, v: number) => (k.unit === 'share' ? pct(v) : `${v}×`)
/** The detector that finds the most planted cases of a kind at its main size. */
const winner = (o: FlagOverview, k: FlagKind) =>
  o.planted.filter((p) => p.kind === k.id && p.size === k.main).sort((a, b) => b.detected - a.detected)[0] as FlagOverview['planted'][number] | undefined
const nameOf = (o: FlagOverview, id: string) => o.detectors.find((d) => d.id === id)?.name ?? id
const firmRules = (o: FlagOverview) => o.detectors.filter((d) => d.level === 'firm')

const isRule = (o: FlagOverview, id: string) => o.detectors.find((d) => d.id === id)?.family === 'rule'
const statFlags = (o: FlagOverview, r: FlaggedExec) => r.flags.filter((f) => !isRule(o, f.detector))
/** Raised by a rule, or by at least half of the statistical detectors that could judge it. */
const strong = (o: FlagOverview, r: FlaggedExec) => r.flags.length > statFlags(o, r).length || statFlags(o, r).length * 2 >= Math.max(1, r.checked.length)
const roleText = (r: Role) => (r === 'Member' ? 'board member' : r)

// ------------------------------------------------------------------ page

export function FlagsView() {
  const state = useApi<FlagOverview>('/flags')
  const d = state.data
  return (
    <>
      <PageHead title="Red flags">
        {d &&
          `What should a supervisory board or an investor look at? ${spell(d.detectors.filter((x) => x.family === 'rule').length, true)} rules from the law and the governance code and ${spell(d.detectors.filter((x) => x.family !== 'rule').length)} statistical detectors, applied to the same executive-years side by side. Every flag shows its evidence: it is a reason to look, not a verdict.`}
      </PageHead>
      <Async state={state} skeleton={<PanelsSkeleton heights={[160, 520, 420]} />}>
        {(o) => <Overview o={o} />}
      </Async>
    </>
  )
}

function Overview({ o }: { o: FlagOverview }) {
  const [year, setYear] = useState(o.years[o.years.length - 1])
  const list = useApi<FlagList>(`/flags/executives?year=${year}`)
  return (
    <>
      <Headline o={o} year={year} list={list} />
      <Explorer o={o} year={year} setYear={setYear} list={list} />
      <Planted o={o} />
      <PerYear o={o} />
      <Agreement o={o} />
      <Checks o={o} />
    </>
  )
}

function Headline({ o, year, list }: { o: FlagOverview; year: number; list: Loadable<FlagList> }) {
  const l = list.data
  const count = (n?: number) => n ?? (list.error ? '–' : <Skeleton width={40} height={28} />)
  return (
    <div className="stats">
      <Stat
        label={`Executives with a rule flag, ${year}`}
        value={count(l?.rows.filter((r) => r.flags.length > statFlags(o, r).length).length)}
        sub={l ? `plus ${l.firms.length} firm-year flag${l.firms.length === 1 ? '' : 's'} (${firmRules(o).map((d) => d.name.toLowerCase()).join(', ')})` : undefined}
      />
      <Stat
        label={`Flagged by most detectors, ${year}`}
        value={count(l?.rows.filter((r) => statFlags(o, r).length > 0 && statFlags(o, r).length * 2 >= r.checked.length).length)}
        sub={l ? `at least half of the detectors that could judge them; ${l.rows.filter((r) => statFlags(o, r).length > 0).length} flagged by at least one` : undefined}
      />
      {o.kinds.map((k) => {
        const top = winner(o, k)
        return top ? (
          <Stat key={k.id} label={`Planted: ${k.name.toLowerCase()}`} value={pct(top.detected)} sub={`found at ${sizeText(k, k.main)} by the best detector, ${nameOf(o, top.detector)}`} />
        ) : null
      })}
    </div>
  )
}

// ------------------------------------------------------------------ flagged executive-years

const ROLES: { value: Role | 'all'; label: string }[] = [{ value: 'all', label: 'All' }, ...(['CEO', 'CFO', 'Member'] as Role[]).map((r) => ({ value: r, label: ROLE_LABEL[r] }))]
const PAGE = 25

function Explorer({ o, year, setYear, list }: { o: FlagOverview; year: number; setYear: (y: number) => void; list: Loadable<FlagList> }) {
  const [role, setRole] = useState<Role | 'all'>('all')
  const [show, setShow] = useState<'strong' | 'all'>('strong')
  return (
    <Panel
      title={`Flagged executive-years, ${year}`}
      caption="Open a row for the evidence. The symbols are the statistical detectors: solid where the detector flags the executive-year, faint where it checked and found nothing, missing where it could not judge (no peers, no forecast, components not reported)."
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
          <Segmented label="Role" value={role} onChange={setRole} options={ROLES} />
          <Segmented
            label="Show"
            value={show}
            onChange={setShow}
            options={[
              { value: 'strong', label: 'Rules or most detectors' },
              { value: 'all', label: 'Any flag' },
            ]}
          />
        </>
      }
    >
      <DetectorLegend o={o} />
      <Async state={list} skeleton={<Skeleton height={320} />}>
        {(l) => {
          const rows = sortRows(o, l.rows.filter((r) => (role === 'all' || r.role === role) && (show === 'all' || strong(o, r))))
          return (
            <>
              <FirmFlags o={o} firms={l.firms} />
              {rows.length ? <FlagRows key={`${year}-${role}-${show}`} o={o} rows={rows} /> : <p className="muted">No executive-year matches.</p>}
            </>
          )
        }}
      </Async>
    </Panel>
  )
}

function DetectorLegend({ o }: { o: FlagOverview }) {
  return <Legend items={styles(o).legend} />
}

/** Most rule flags first, then most detectors, then the highest pay. */
function sortRows(o: FlagOverview, rows: FlaggedExec[]) {
  const key = (r: FlaggedExec) => [r.flags.length - statFlags(o, r).length, statFlags(o, r).length, r.total]
  return [...rows].sort((a, b) => {
    const [x, y] = [key(a), key(b)]
    return y[0] - x[0] || y[1] - x[1] || y[2] - x[2]
  })
}

function FlagRows({ o, rows, withYear }: { o: FlagOverview; rows: FlaggedExec[]; withYear?: boolean }) {
  const [all, setAll] = useState(false)
  const { mark, stats } = styles(o)
  const names = new Map(o.detectors.map((d) => [d.id, d.name]))
  const shown = all ? rows : rows.slice(0, PAGE)
  return (
    <>
      <ul className="flag-list">
        {shown.map((r) => {
          const mine = new Set(r.flags.map((f) => f.detector))
          const checked = new Set(r.checked)
          // Detectors that flag for the same reason (the package detectors) share one line.
          const reasons = new Map<string, string[]>()
          for (const f of r.flags) reasons.set(f.evidence, [...(reasons.get(f.evidence) ?? []), f.detector])
          return (
            <li key={`${r.person_id}-${r.firm_id}-${r.year}`}>
              <details>
                <summary>
                  <span className="flag-who">
                    <a href={`#/people/${r.person_id}`}>{r.name}</a>
                    <span>
                      {r.firm} · {roleText(r.role)}
                      {withYear ? ` · ${r.year}` : ''}
                      {r.full_year ? '' : ' · part of the year'}
                    </span>
                    {r.flags.some((f) => isRule(o, f.detector)) && (
                      <span className="flag-rules">
                        {r.flags
                          .filter((f) => isRule(o, f.detector))
                          .map((f) => (
                            <span key={f.detector} className="tag">
                              {names.get(f.detector)}
                            </span>
                          ))}
                      </span>
                    )}
                  </span>
                  {r.checked.length > 0 && (
                    <span
                      className="flag-dots"
                      role="img"
                      aria-label={`${statFlags(o, r).length} of the ${r.checked.length} detectors that could judge flag this${statFlags(o, r).length ? `: ${statFlags(o, r).map((f) => names.get(f.detector)).join(', ')}` : ''}`}
                    >
                      {stats.map((d) => mark(d.id, mine.has(d.id) ? undefined : checked.has(d.id) ? 'off' : 'none'))}
                      {` ${statFlags(o, r).length}/${r.checked.length}`}
                    </span>
                  )}
                  <span className="flag-pay">{keur(r.total)} k€</span>
                </summary>
                <ul className="flag-evidence">
                  {[...reasons].map(([evidence, ids]) => (
                    <li key={ids.join()}>
                      <strong>
                        {ids.map((id) => mark(id))}
                        {ids.map((id) => names.get(id)).join(', ')}
                      </strong>
                      <span>{evidence}</span>
                    </li>
                  ))}
                </ul>
              </details>
            </li>
          )
        })}
      </ul>
      {rows.length > PAGE && (
        <button type="button" className="link" onClick={() => setAll(!all)}>
          {all ? 'Show fewer' : `Show all ${rows.length}`}
        </button>
      )}
    </>
  )
}

/** Firm-year flags (the whole board), such as no individual disclosure. */
function FirmFlags({ o, firms, withYear }: { o: FlagOverview; firms: FirmFlag[]; withYear?: boolean }) {
  if (!firms.length) return null
  const { mark } = styles(o)
  const names = new Map(o.detectors.map((d) => [d.id, d.name]))
  return (
    <Table
      caption="Firm-year flags"
      rows={firms}
      rowKey={(f) => `${f.firm_id}-${f.year}-${f.detector}`}
      sort={withYear ? { key: 'year', desc: true } : { key: 'firm', desc: false }}
      columns={[
        { key: 'firm', label: 'Company', value: (f) => f.firm, render: (f) => <a href={`#/companies/${f.firm_id}`}>{f.firm}</a> },
        ...(withYear ? [{ key: 'year', label: 'Year', numeric: true, value: (f: FirmFlag) => f.year }] : []),
        {
          key: 'check',
          label: 'Firm-year flag',
          value: (f) => names.get(f.detector),
          render: (f) => (
            <span className="flag-name">
              {mark(f.detector)} {names.get(f.detector)}
            </span>
          ),
        },
        { key: 'evidence', label: 'Evidence', wrap: true, value: (f) => f.evidence },
      ]}
    />
  )
}

/** The flags of one firm or one executive, every year: for the company and executive pages. */
export function FlagsPanel({ query, empty }: { query: string; empty: string }) {
  const overview = useApi<FlagOverview>('/flags')
  const list = useApi<FlagList>(`/flags/executives?${query}`)
  return (
    <Panel
      title="Red flags"
      caption="Rules from the law and the governance code and statistical detectors, every year. Open a row for the evidence: a flag is a reason to look, not a verdict."
      note={<a href="#/flags">How the checks work</a>}
    >
      <Async state={overview} skeleton={<Skeleton height={120} />}>
        {(o) => (
          <Async state={list} skeleton={<Skeleton height={120} />}>
            {(l) =>
              l.rows.length + l.firms.length ? (
                <>
                  <DetectorLegend o={o} />
                  <FirmFlags o={o} firms={l.firms} withYear />
                  <FlagRows key={query} o={o} rows={[...l.rows].sort((a, b) => b.year - a.year || b.total - a.total)} withYear />
                </>
              ) : (
                <p className="muted">{empty}</p>
              )
            }
          </Async>
        )}
      </Async>
    </Panel>
  )
}

// ------------------------------------------------------------------ planted anomalies

function Planted({ o }: { o: FlagOverview }) {
  const { mark, stats, color, symbol } = styles(o)
  // The first size of a kind leaves the data unchanged: its detection rate is the false-alarm rate.
  const plain = o.kinds[0]
  const falseAlarm = (id: string) => (plain ? o.planted.find((p) => p.detector === id && p.kind === plain.id && p.size === plain.sizes[0])?.detected : undefined)
  const auc = (id: string, kind: string) => o.auc.find((a) => a.detector === id && a.kind === kind)?.auc
  return (
    <Panel
      title="Which detector finds which anomaly"
      caption={`Known anomalies planted, one at a time, in the ${o.n_common.toLocaleString('en-GB')} real executive-years that every detector can judge (the bonus anomaly in those with a bonus); the planted row is scored by models that never saw its firm. The first point of each line is the data as it is: the share flagged without any anomaly.`}
      note={`AUC: the chance that the planted version scores above a real executive-year of the same disclosure regime (${o.kinds.map((k) => `${k.short.toLowerCase()} at ${sizeText(k, k.main)}`).join(', ')}); 0.5 means the detector cannot see the anomaly. Model-based detectors flag ${pct(o.flag_share)} of each regime; the other thresholds are under "The checks".`}
    >
      <DetectorLegend o={o} />
      <div className="grid-3">
        {o.kinds.map((k) => {
          const rows = o.planted.filter((p) => p.kind === k.id).map((p) => ({ ...p, name: nameOf(o, p.detector) }))
          const top = winner(o, k)
          return (
            <div key={k.id} className="subchart">
              <h3>{k.name}</h3>
              <p className="caption">{k.idea}</p>
              <Chart
                label={`${k.name}: share of planted cases each detector flags, by size of the anomaly${top ? `; at ${sizeText(k, k.main)} ${nameOf(o, top.detector)} finds the most, ${pct(top.detected)}` : ''}.`}
                render={(width) =>
                  Plot.plot({
                    ...base(width, 260),
                    x: { label: k.size_label, ticks: k.sizes, tickFormat: (v: number) => sizeText(k, v) },
                    y: { label: 'Flagged', domain: [0, 1], tickFormat: (v: number) => pct(v), grid: true },
                    color,
                    symbol,
                    marks: [
                      Plot.line(rows, { x: 'size', y: 'detected', stroke: 'name', z: 'name', strokeOpacity: 0.8 }),
                      Plot.dot(rows, {
                        x: 'size',
                        y: 'detected',
                        fill: 'name',
                        symbol: 'name',
                        r: 3.5,
                        tip: true,
                        title: (d) => `${d.name}\n${k.size_label} ${sizeText(k, d.size)}: ${pct(d.detected)} flagged`,
                      }),
                    ],
                  })
                }
              />
            </div>
          )
        })}
      </div>
      <Table
        caption="Planted-anomaly test per detector"
        rows={stats}
        rowKey={(d) => d.id}
        sort={{ key: 'name', desc: false }}
        columns={[
          {
            key: 'name',
            label: 'Detector',
            value: (d) => d.name,
            render: (d) => (
              <span className="flag-name">
                {mark(d.id)} {d.name}
              </span>
            ),
          },
          { key: 'false', label: 'No anomaly', numeric: true, value: (d) => falseAlarm(d.id), render: (d) => pct(falseAlarm(d.id)) },
          ...o.kinds.map((k) => ({ key: k.id, label: `AUC ${k.short.toLowerCase()}`, numeric: true, value: (d: FlagDetector) => auc(d.id, k.id), render: (d: FlagDetector) => auc(d.id, k.id)?.toFixed(2) ?? '–' })),
        ]}
      />
    </Panel>
  )
}

// ------------------------------------------------------------------ flags per year

function PerYear({ o }: { o: FlagOverview }) {
  const names = new Map(o.detectors.map((d) => [d.id, d.name]))
  const family = new Map(o.detectors.map((d) => [d.id, d.family]))
  const cells = o.by_year.map((c) => ({ ...c, name: names.get(c.detector)!, share: c.checked ? c.flagged / c.checked : 0, color: FLAG_FAMILY_COLOR[family.get(c.detector)!] }))
  const top = Math.max(0, ...cells.map((c) => c.share))
  const peak = cells.find((c) => c.share === top)
  const domain = o.detectors.map((d) => d.name)
  if (!peak || !top) return null
  return (
    <Panel
      title="Flags per year"
      caption={`Share of the executive-years (firm-years for ${firmRules(o).map((d) => d.name.toLowerCase()).join(', ')}) each check flags, by year; the number is the count. A check runs only where its data exists: an empty cell means it could not run that year (no TSR recorded, opt-out abolished, no forecast across the 2021/22 break).`}
    >
      <Legend items={(['rule', 'context', 'structure'] as const).map((f) => ({ label: FLAG_FAMILY_LABEL[f], color: FLAG_FAMILY_COLOR[f] }))} />
      <Chart
        minWidth={640}
        label={`Share of executive-years each red-flag check raises, ${o.years[0]}–${o.years[o.years.length - 1]}; the highest is ${peak.name} in ${peak.year} at ${pct(peak.share)}.`}
        render={(width) => {
          const labels = labelAxis(domain, width, 0.3)
          return Plot.plot({
            ...base(width, domain.length * 30 + 60),
            marginLeft: labels.marginLeft,
            x: { label: null, type: 'band', axis: 'top', tickFormat: (y: number) => (width > 760 || y % 2 === 0 ? String(y) : '') },
            y: { label: null, domain, tickFormat: labels.tickFormat },
            marks: [
              Plot.cell(cells, { x: 'year', y: 'name', fill: 'var(--grid)', inset: 0.5 }),
              Plot.cell(cells, {
                x: 'year',
                y: 'name',
                fill: 'color',
                fillOpacity: (d) => (d.flagged ? 0.12 + 0.88 * Math.sqrt(d.share / top) : 0),
                inset: 0.5,
                tip: true,
                title: (d) => `${d.name}, ${d.year}\n${d.flagged} of ${d.checked} flagged (${pct(d.share, 1)})`,
              }),
              width > 760 ? Plot.text(cells, { x: 'year', y: 'name', text: (d) => (d.flagged ? String(d.flagged) : ''), fill: (d) => (Math.sqrt(d.share / top) > 0.6 ? 'var(--surface)' : 'var(--ink)'), fontSize: 10 }) : null,
            ],
          })
        }}
      />
    </Panel>
  )
}

// ------------------------------------------------------------------ agreement

function Agreement({ o }: { o: FlagOverview }) {
  const ids = o.detectors.filter((d) => d.level === 'executive').map((d) => d.id)
  const names = new Map(o.detectors.map((d) => [d.id, d.name]))
  const cells = o.agreement
    .filter((c) => ids.indexOf(c.a) > ids.indexOf(c.b) && c.jaccard != null)
    .map((c) => ({ ...c, x: names.get(c.b)!, y: names.get(c.a)!, value: c.jaccard! }))
  const sorted = [...cells].sort((a, b) => b.value - a.value)
  const [closest, median] = [sorted[0], sorted[Math.floor(sorted.length / 2)]]
  const domain = ids.map((id) => names.get(id)!)
  if (!closest) return null
  return (
    <Panel
      title="Do the checks flag the same executives?"
      caption="Overlap of the executive-years two checks flag (Jaccard: flagged by both ÷ flagged by at least one), on the executive-years both can judge. 1 means the same flags, 0 none in common. Empty cells: the two never judge the same executive-year."
    >
      <Chart
        minWidth={560}
        label={`Overlap of red flags between checks; the closest pair is ${closest.y} and ${closest.x} at ${closest.value.toFixed(2)}, the median pair ${median.value.toFixed(2)}.`}
        render={(width) => {
          const labels = labelAxis(domain, width, 0.3)
          const short = labelAxis(domain, width, 0.18) // rotated labels: shorter, so they fit under the chart
          return Plot.plot({
            ...base(Math.min(width, 980), domain.length * 38 + 140),
            marginLeft: labels.marginLeft,
            marginBottom: 140,
            x: { label: null, domain: domain.slice(0, -1), tickRotate: -35, tickFormat: short.tickFormat },
            y: { label: null, domain: domain.slice(1), tickFormat: labels.tickFormat },
            marks: [
              Plot.cell(cells, { x: 'x', y: 'y', fill: 'var(--grid)', inset: 1 }),
              Plot.cell(cells, {
                x: 'x',
                y: 'y',
                fill: 'var(--c-band)',
                fillOpacity: (d) => Math.max(0.04, d.value),
                inset: 1,
                tip: true,
                title: (d) => `${d.y} × ${d.x}\n${d.both} flagged by both, ${d.either} by at least one (Jaccard ${d.value.toFixed(2)})\n${d.n.toLocaleString('en-GB')} executive-years judged by both`,
              }),
              narrow(width)
                ? null
                : Plot.text(cells, { x: 'x', y: 'y', text: (d) => d.value.toFixed(2), fill: (d) => (d.value > 0.55 ? 'var(--on-accent)' : 'var(--ink)'), fontSize: 11 }),
            ],
          })
        }}
      />
    </Panel>
  )
}

// ------------------------------------------------------------------ the checks

function Checks({ o }: { o: FlagOverview }) {
  const { mark } = styles(o)
  return (
    <Panel title="The checks" caption="What each check flags, from which threshold, and where it comes from. Counts over all years.">
      <div className="grid-3">
        {(['rule', 'context', 'structure'] as const).map((f) => (
          <div key={f} className="subchart">
            <h3>{FLAG_FAMILY_LABEL[f]}</h3>
            <ul className="issues">
              {o.detectors
                .filter((d) => d.family === f)
                .map((d) => (
                  <li key={d.id}>
                    <h4>
                      <span className="flag-name">
                        {mark(d.id)} {d.name}
                      </span>
                      {d.level === 'firm' && <span className="badge">firm-year</span>}
                    </h4>
                    <p>{d.rule}</p>
                    <p>
                      <em>{d.origin}</em>
                    </p>
                    <p>
                      {d.flagged.toLocaleString('en-GB')} of {d.checked.toLocaleString('en-GB')} {d.level === 'firm' ? 'firm-years' : 'executive-years'} flagged ({pct(d.checked ? d.flagged / d.checked : 0, 1)})
                    </p>
                  </li>
                ))}
            </ul>
          </div>
        ))}
      </div>
    </Panel>
  )
}
