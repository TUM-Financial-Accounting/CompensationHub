import * as Plot from '@observablehq/plot'
import { useState } from 'react'

import { usePrevious } from '../previous'
import { useApi, type FirmForecast, type PersonPrediction, type PredictionModel, type PredictionModelView, type PredictionOverview, type Role, type WhatIf, type ModelFamily } from '../api'
import { MODEL_FAMILY_COLOR, MODEL_FAMILY_LABEL, base, labelAxis, narrow, yearAxis } from '../charts'
import { ROLE_LABEL, keur, logPct, meur, multiple, pct, signed, spell } from '../format'
import { Async, Chart, Legend, PageHead, PageSkeleton, Panel, PanelsSkeleton, Segmented, Skeleton, Stat, Table } from '../ui'

// Every number on these pages comes from backend/app/forecast.py; see docs/prediction.md.

const REGIME_LABEL: Record<string, string> = { '§162': '§162 AktG', legacy: 'Before §162 (DCGK tables)' }
const regimeOptions = (regimes: string[]) => regimes.map((r) => ({ value: r, label: REGIME_LABEL[r] ?? r }))

const familyColor = (d: { family: ModelFamily }) => MODEL_FAMILY_COLOR[d.family]

function familyLegend(models: PredictionModel[]) {
  const families = [...new Set(models.map((m) => m.family))]
  return families.map((f) => ({ label: MODEL_FAMILY_LABEL[f], color: MODEL_FAMILY_COLOR[f], shape: 'circle' as const }))
}

/** Horizons with fewer test pairs than this are too noisy to show. */
const MIN_PAIRS = 30

// ------------------------------------------------------------------ overview

export function PredictionView() {
  const state = useApi<PredictionOverview>('/prediction')
  const o = state.data
  return (
    <>
      <PageHead title="Pay prediction">
        {o &&
          `${spell(o.models.length, true)} models forecast each pay item one to ${spell(Math.max(1, ...o.by_horizon.map((r) => r.h)))} years ahead, from “same as last year” to a neural network. Each model is trained only on years before the one it predicts and scored against what was actually paid.`}
      </PageHead>
      <Async state={state} skeleton={<PanelsSkeleton heights={[420, 520, 520]} />}>
        {(o) => <Overview o={o} />}
      </Async>
    </>
  )
}

function Overview({ o }: { o: PredictionOverview }) {
  const regimes = [...new Set(o.scorecard.map((s) => s.regime))]
  const [target, setTarget] = useState('total')
  const [regime, setRegime] = useState(o.latest_regime)
  const names = new Map(o.models.map((m) => [m.id, m]))
  const label = new Map(o.targets.map((t) => [t.id, t.label]))
  const latest = o.scorecard.filter((s) => s.regime === o.latest_regime)
  const bestTotal = latest.find((s) => s.target === 'total' && s.model === o.best.total)
  const naiveWins = Object.values(o.best).filter((m) => names.get(m)?.family === 'own').length
  const seeds = o.mlp_seeds.map((s) => s.mae)
  return (
    <>
      <div className="stats">
        <Stat
          label="Best model, total pay"
          value={names.get(o.best.total)?.name}
          sub={bestTotal && `typical miss ${logPct(bestTotal.mae)} on ${REGIME_LABEL[o.latest_regime]} test years`}
        />
        <Stat
          label="Simple models that win"
          value={`${naiveWins} of ${o.targets.length}`}
          sub="pay items where a model that only looks at the executive's own past is the most accurate"
        />
        <Stat
          label="Neural network, seed to seed"
          value={seeds.length ? `${logPct(Math.min(...seeds))}–${logPct(Math.max(...seeds))}` : '–'}
          sub="typical miss on total pay: same data, only the random starting point differs"
        />
        <Stat
          label="Pay gap after characteristics"
          value={signed(o.gap_woman)}
          sub={`women vs. men with the same role, firm size, tenure and age (German nationality: ${signed(o.gap_german)}); never used for predictions`}
        />
      </div>

      <nav aria-label="Prediction models" className="views methods">
        {o.models.map((m) => {
          const s = latest.find((x) => x.target === 'total' && x.model === m.id)
          return (
            <a key={m.id} href={`#/prediction/${m.id}`}>
              <strong>
                <i className="swatch circle" style={{ background: MODEL_FAMILY_COLOR[m.family] }} aria-hidden="true" /> {m.name}
              </strong>
              <span>{m.idea}</span>
              {s && (
                <span className="card-stats">
                  total pay: miss {logPct(s.mae)} · {s.skill >= 0 ? 'beats' : 'trails'} the drift baseline by {pct(Math.abs(s.skill))}
                </span>
              )}
            </a>
          )
        })}
      </nav>

      <div className="controls">
        <Segmented label="Pay item" value={target} onChange={setTarget} options={o.targets.map((t) => ({ value: t.id, label: t.label }))} />
        <Segmented label="Test years" value={regime} onChange={setRegime} options={regimeOptions(regimes)} />
      </div>

      <Scorecard o={o} regime={regime} />
      <ErrorByModel o={o} target={target} regime={regime} label={label.get(target)!} />
      <Horizon o={o} target={target} regime={regime} label={label.get(target)!} />
      <Paid o={o} label={label} />
    </>
  )
}

function Scorecard({ o, regime }: { o: PredictionOverview; regime: string }) {
  const names = new Map(o.models.map((m) => [m.id, m.name]))
  const targets = new Map(o.targets.map((t) => [t.id, t.label]))
  const cells = o.scorecard
    .filter((s) => s.regime === regime)
    .map((s) => ({ ...s, modelName: names.get(s.model)!, targetName: targets.get(s.target)!, best: o.best[s.target] === s.model }))
  const wins = cells.filter((c) => c.skill > 0.005).length
  return (
    <Panel
      title="Who beats “last year + market drift”?"
      caption={`Skill per model and pay item: how much smaller the model's error is than the drift baseline's on the same executive-years (${REGIME_LABEL[regime]} test years). Blue beats the baseline, orange is worse; a ring marks the model shown on executive pages.`}
      note={
        <>
          {o.best_rule}
          {o.coherence != null && ` The best component forecasts for next year add up to ${multiple(o.coherence)} the best total-pay forecast (median over executives; 1× means the parts and the whole agree).`}
        </>
      }
    >
      <Chart
        minWidth={620}
        label={`Skill heatmap: ${wins} of ${cells.length} model and pay-item combinations beat the drift baseline.`}
        render={(width) => {
          const names = o.models.map((m) => m.name)
          const labels = labelAxis(names, width, 0.32)
          const tilted = width < 900 // column labels would overlap
          return Plot.plot({
            ...base(Math.min(width, 1100), o.models.length * 30 + (tilted ? 100 : 70)),
            marginLeft: labels.marginLeft,
            marginRight: tilted ? 48 : 16,
            marginTop: tilted ? 70 : 40,
            x: { label: null, axis: 'top', domain: o.targets.map((t) => t.label), tickRotate: tilted ? -35 : 0 },
            y: { label: null, domain: names, tickFormat: labels.tickFormat },
            marks: [
              Plot.cell(cells, { x: 'targetName', y: 'modelName', fill: 'var(--grid)', inset: 1 }),
              Plot.cell(cells, {
                x: 'targetName',
                y: 'modelName',
                fill: (d) => (d.skill > 0 ? 'var(--accent)' : 'var(--warn)'),
                fillOpacity: (d) => Math.min(0.9, 0.08 + Math.abs(d.skill) * 1.6),
                inset: 1,
                tip: true,
                title: (d) =>
                  `${d.modelName} · ${d.targetName}\nmiss ${logPct(d.mae)} vs. ${logPct(d.mae_ref)} for the baseline\nskill ${signed(d.skill)} · predicts ${pct(d.coverage)} of pairs`,
              }),
              Plot.cell(cells.filter((c) => c.best), { x: 'targetName', y: 'modelName', stroke: 'var(--ink)', strokeWidth: 2, inset: 2.5, fill: 'none' }),
              Plot.text(cells, {
                x: 'targetName',
                y: 'modelName',
                text: (d) => signed(d.skill),
                fill: (d) => (Math.abs(d.skill) > 0.45 ? 'var(--on-accent)' : 'var(--ink)'),
                fontSize: 11,
              }),
            ],
          })
        }}
      />
    </Panel>
  )
}

function ErrorByModel({ o, target, regime, label }: { o: PredictionOverview; target: string; regime: string; label: string }) {
  const models = new Map(o.models.map((m) => [m.id, m]))
  const rows = o.scorecard
    .filter((s) => s.target === target && s.regime === regime)
    .map((s) => ({ ...s, name: models.get(s.model)!.name, family: models.get(s.model)!.family }))
    .sort((a, b) => a.mae - b.mae)
  const drift = rows.find((r) => r.model === 'drift')
  if (!rows.length) return null
  const names = rows.map((r) => r.name)
  return (
    <Panel
      title={`${label}: how far off, and how honest the range`}
      caption={`Left: typical miss (mean absolute error of the log value, shown as %). Right: share of actual values inside the stated ${pct(o.band)} range — the line marks ${pct(o.band)}, the promise. Models are scored on the pairs they can predict; the tooltip says how many.`}
    >
      <Legend items={familyLegend(o.models)} />
      <div className="grid-2">
        <div className="subchart">
          <h3>Typical miss</h3>
          <Chart
            label={`${label}: ${rows[0].name} misses least, by ${logPct(rows[0].mae)}; ${rows[rows.length - 1].name} misses most, by ${logPct(rows[rows.length - 1].mae)}.`}
            render={(width) => {
              const labels = labelAxis(names, width)
              return Plot.plot({
                ...base(width, rows.length * 26 + 40),
                marginLeft: labels.marginLeft,
                marginRight: 48,
                x: { label: null, grid: true, tickFormat: (v: number) => logPct(v), ticks: narrow(width) ? 3 : undefined },
                y: { label: null, domain: names, tickFormat: labels.tickFormat },
                marks: [
                  drift ? Plot.ruleX([drift.mae], { stroke: 'var(--muted)', strokeDasharray: '3,3' }) : null,
                  Plot.ruleY(rows, { y: 'name', x1: 0, x2: 'mae', stroke: familyColor, strokeOpacity: 0.35, strokeWidth: 3 }),
                  Plot.dot(rows, {
                    x: 'mae',
                    y: 'name',
                    r: 5.5,
                    fill: familyColor,
                    stroke: 'var(--surface)',
                    tip: true,
                    title: (d) => `${d.name}\nmiss ${logPct(d.mae)} (median ${logPct(d.mdae)})\n${d.n.toLocaleString('en-GB')} test pairs (${pct(d.coverage)})`,
                  }),
                  Plot.text(rows, { x: 'mae', y: 'name', text: (d) => logPct(d.mae), dx: 10, textAnchor: 'start', fill: 'var(--muted)', fontSize: 11 }),
                ],
              })
            }}
          />
        </div>
        <div className="subchart">
          <h3>Range coverage</h3>
          <Chart
            label={`${label}: coverage of the ${pct(o.band)} range by model, against the promised ${pct(o.band)}.`}
            render={(width) => {
              const labels = labelAxis(names, width)
              return Plot.plot({
                ...base(width, rows.length * 26 + 40),
                marginLeft: labels.marginLeft,
                marginRight: 48,
                x: { label: null, grid: true, tickFormat: '.0%', domain: [0.4, 1], ticks: narrow(width) ? 3 : undefined },
                y: { label: null, domain: names, tickFormat: labels.tickFormat },
                marks: [
                  Plot.ruleX([o.band], { stroke: 'var(--ink)', strokeOpacity: 0.6 }),
                  Plot.dot(
                    rows.filter((r) => r.band_cover != null),
                    {
                      x: 'band_cover',
                      y: 'name',
                      r: 5.5,
                      fill: familyColor,
                      stroke: 'var(--surface)',
                      tip: true,
                      title: (d) => `${d.name}\n${pct(d.band_cover, 1)} inside the ${pct(o.band)} range\nrange width ×${Math.exp(d.band_width ?? 0).toFixed(1)}`,
                    },
                  ),
                  Plot.text(
                    rows.filter((r) => r.band_cover != null),
                    { x: 'band_cover', y: 'name', text: (d) => pct(d.band_cover), dx: 10, textAnchor: 'start', fill: 'var(--muted)', fontSize: 11 },
                  ),
                ],
              })
            }}
          />
        </div>
      </div>
    </Panel>
  )
}

function Horizon({ o, target, regime, label }: { o: PredictionOverview; target: string; regime: string; label: string }) {
  const models = new Map(o.models.map((m) => [m.id, m]))
  const rows = o.by_horizon
    .filter((s) => s.target === target && s.regime === regime && s.n >= MIN_PAIRS)
    .map((s) => ({ ...s, name: models.get(s.model)!.name, family: models.get(s.model)!.family }))
  const highlight = new Set([o.best[target], 'drift'])
  if (new Set(rows.map((r) => r.h)).size < 2) return null
  return (
    <Panel
      title="Error grows with the horizon"
      caption={`${label}: typical miss by years ahead, ${REGIME_LABEL[regime]} test years. Bold: the drift baseline and the model shown on executive pages. Horizons with fewer than ${MIN_PAIRS} test pairs are left out.`}
    >
      <Chart
        label={`${label}: forecast error rises with each year ahead for every model.`}
        render={(width) =>
          Plot.plot({
            ...base(width, 340),
            marginRight: narrow(width) ? 16 : 160,
            x: { label: 'Years ahead', ticks: [...new Set(rows.map((r) => r.h))], tickFormat: 'd' },
            y: { label: 'Typical miss', grid: true, tickFormat: (v: number) => logPct(v) },
            marks: [
              Plot.line(rows, { x: 'h', y: 'mae', z: 'name', stroke: familyColor, strokeOpacity: (d) => (highlight.has(d.model) ? 1 : 0.3), strokeWidth: (d) => (highlight.has(d.model) ? 2.5 : 1.2) }),
              Plot.dot(rows, { x: 'h', y: 'mae', fill: familyColor, r: 3, tip: true, title: (d) => `${d.name}, ${d.h} year${d.h > 1 ? 's' : ''} ahead\nmiss ${logPct(d.mae)} · ${d.n} pairs` }),
              Plot.text(
                rows.filter((r) => highlight.has(r.model)),
                Plot.selectLast({
                  x: 'h',
                  y: 'mae',
                  z: 'name',
                  text: 'name',
                  ...(narrow(width) ? { dy: -9, textAnchor: 'end', stroke: 'var(--surface)', strokeWidth: 3 } : { dx: 8, textAnchor: 'start' }),
                  fill: 'var(--ink)',
                  fontSize: 11,
                }),
              ),
            ],
          })
        }
      />
    </Panel>
  )
}

function Paid({ o, label }: { o: PredictionOverview; label: Map<string, string> }) {
  return (
    <Panel
      title="Is the item paid at all?"
      caption="Bonuses, share plans and pensions are zero for some executives in some years, so each is predicted in two parts: whether it is paid (logistic regression), then how much. Accuracy of the first part against the rule “paid then if paid now”."
    >
      <Table
        caption="Accuracy of the paid-or-not models"
        rows={o.paid}
        rowKey={(r) => `${r.target}-${r.regime}`}
        sort={{ key: 'target', desc: false }}
        columns={[
          { key: 'target', label: 'Pay item', value: (r) => label.get(r.target) },
          { key: 'regime', label: 'Test years', value: (r) => REGIME_LABEL[r.regime] ?? r.regime },
          { key: 'n', label: 'Pairs', numeric: true, value: (r) => r.n, render: (r) => r.n.toLocaleString('en-GB') },
          { key: 'share', label: 'Paid', numeric: true, value: (r) => r.share_paid, render: (r) => pct(r.share_paid) },
          { key: 'acc', label: 'Model right', numeric: true, value: (r) => r.accuracy, render: (r) => pct(r.accuracy, 1) },
          { key: 'same', label: '“Same as now” right', numeric: true, value: (r) => r.accuracy_same, render: (r) => pct(r.accuracy_same, 1) },
        ]}
      />
    </Panel>
  )
}

// ------------------------------------------------------------------ one model

export function PredictionModelPage({ id }: { id: string }) {
  const [target, setTarget] = useState('total')
  const state = usePrevious(useApi<PredictionModelView>(`/prediction/${id}?target=${target}`))
  const overview = useApi<PredictionOverview>('/prediction')
  return (
    <Async state={state} skeleton={<PageSkeleton />}>
      {(v) => (
        <div className={state.stale ? 'page-body stale' : 'page-body'} aria-busy={state.stale}>
          <ModelPage v={v} target={target} setTarget={setTarget} band={overview.data?.band} />
        </div>
      )}
    </Async>
  )
}

function ModelPage({ v, target, setTarget, band }: { v: PredictionModelView; target: string; setTarget: (t: string) => void; band?: number }) {
  const label = v.targets.find((t) => t.id === target)?.label ?? target
  const regimes = [...new Set(v.scores.map((s) => s.regime))]
  const [regime, setRegime] = useState(regimes.includes('§162') ? '§162' : regimes[0])
  const s = v.scores.find((x) => x.target === target && x.regime === regime)
  const shown = Object.entries(v.best).filter(([, m]) => m === v.model.id).map(([t]) => v.targets.find((x) => x.id === t)?.label ?? t)
  return (
    <>
      <PageHead crumb={<a href="#/prediction">Pay prediction</a>} title={v.model.name}>
        {v.model.idea}
      </PageHead>
      <dl className="facts">
        <dt>Formula</dt>
        <dd>
          <code>{v.model.formula}</code>
        </dd>
        <dt>Why it is here</dt>
        <dd>{v.model.why}</dd>
        <dt>Family</dt>
        <dd>
          <i className="swatch circle" style={{ background: MODEL_FAMILY_COLOR[v.model.family], display: 'inline-block' }} aria-hidden="true" />{' '}
          {MODEL_FAMILY_LABEL[v.model.family]}
        </dd>
        <dt>Shown on executive pages for</dt>
        <dd>{shown.length ? shown.join(', ') : 'no pay item: another model is more accurate'}</dd>
      </dl>
      <div className="controls">
        <Segmented label="Pay item" value={target} onChange={setTarget} options={v.targets.map((t) => ({ value: t.id, label: t.label }))} />
        <Segmented label="Test years" value={regime} onChange={setRegime} options={regimeOptions(regimes)} />
      </div>
      {s ? (
        <div className="stats">
          <Stat label="Typical miss" value={logPct(s.mae)} sub={`median ${logPct(s.mdae)}; drift baseline ${logPct(s.mae_ref)} on the same pairs`} />
          <Stat label="Against the baseline" value={signed(s.skill)} sub={s.skill > 0 ? 'smaller error than “last year + drift”' : 'larger error than “last year + drift”'} />
          <Stat label="Range coverage" value={s.band_cover == null ? '–' : pct(s.band_cover)} sub={`of actual values inside the stated ${band == null ? '' : `${pct(band)} `}range`} />
          <Stat label="Pairs predicted" value={pct(s.coverage)} sub={`${s.n.toLocaleString('en-GB')} test pairs`} />
        </div>
      ) : (
        <p className="callout">This model makes no {label.toLowerCase()} predictions in these test years.</p>
      )}
      <div className="grid-2">
        <Scatter v={v} regime={regime} label={label} />
        <ModelHorizon v={v} regime={regime} label={label} />
      </div>
      <div className="grid-2">
        <Calibration v={v} regime={regime} />
        <ByRole v={v} regime={regime} />
      </div>
      <Specific v={v} />
      <Misses v={v} label={label} />
    </>
  )
}

function Scatter({ v, regime, label }: { v: PredictionModelView; regime: string; label: string }) {
  const points = v.points.filter((p) => p.regime === regime)
  if (!points.length) return null
  const all = points.flatMap((p) => [p.actual, p.predicted])
  const domain = [Math.min(...all) * 0.9, Math.max(...all) * 1.1]
  return (
    <Panel title="Predicted against paid" caption={`${label} one year ahead, k€, log scales. On the diagonal the forecast was exact; ${points.length.toLocaleString('en-GB')} executive-years.`}>
      <Chart
        label={`${label}: predicted against actual one year ahead for ${v.model.name}.`}
        render={(width) =>
          Plot.plot({
            ...base(width, Math.min(width, 420)),
            x: { type: 'log', domain, label: 'Predicted (k€)', grid: true, ticks: 5, tickFormat: '~s' },
            y: { type: 'log', domain, label: 'Paid (k€)', grid: true, ticks: 5, tickFormat: '~s' },
            marks: [
              Plot.line(domain.map((d) => ({ d })), { x: 'd', y: 'd', stroke: 'var(--muted)', strokeDasharray: '3,3' }),
              Plot.dot(points, { x: 'predicted', y: 'actual', r: 2.2, fill: MODEL_FAMILY_COLOR[v.model.family], fillOpacity: 0.45, tip: true, title: (d) => `predicted ${keur(d.predicted)} k€\npaid ${keur(d.actual)} k€` }),
            ],
          })
        }
      />
    </Panel>
  )
}

function ModelHorizon({ v, regime, label }: { v: PredictionModelView; regime: string; label: string }) {
  const rows = v.by_horizon.filter((r) => r.regime === regime && r.n >= MIN_PAIRS).map((r) => ({ ...r, who: r.model === 'drift' ? 'Last year + drift' : v.model.name }))
  if (!rows.length) return null
  return (
    <Panel title="Error by years ahead" caption={`${label}: typical miss of this model and of the drift baseline, by horizon.`}>
      <Legend
        items={[
          { label: v.model.name, color: MODEL_FAMILY_COLOR[v.model.family], shape: 'line' },
          { label: 'Last year + drift', color: 'var(--muted)', shape: 'dash' },
        ]}
      />
      <Chart
        label={`${label}: error of ${v.model.name} and of the drift baseline by horizon.`}
        render={(width) =>
          Plot.plot({
            ...base(width, 300),
            x: { label: 'Years ahead', ticks: [...new Set(rows.map((r) => r.h))], tickFormat: 'd' },
            y: { label: 'Typical miss', grid: true, tickFormat: (x: number) => logPct(x), zero: true },
            marks: [
              Plot.line(rows.filter((r) => r.model === 'drift'), { x: 'h', y: 'mae', stroke: 'var(--muted)', strokeDasharray: '4,3', strokeWidth: 2 }),
              Plot.line(rows.filter((r) => r.model !== 'drift'), { x: 'h', y: 'mae', stroke: MODEL_FAMILY_COLOR[v.model.family], strokeWidth: 2 }),
              Plot.dot(rows, { x: 'h', y: 'mae', fill: (d) => (d.model === 'drift' ? 'var(--muted)' : MODEL_FAMILY_COLOR[v.model.family]), tip: true, title: (d) => `${d.who}, ${d.h} y ahead: ${logPct(d.mae)} (${d.n} pairs)` }),
            ],
          })
        }
      />
    </Panel>
  )
}

function Calibration({ v, regime }: { v: PredictionModelView; regime: string }) {
  const rows = v.calibration.filter((c) => c.regime === regime && c.achieved != null)
  if (!rows.length) return null
  return (
    <Panel title="Are the ranges honest?" caption="Stated coverage of a range against the share of actual values that fell inside it. On the diagonal a range keeps its promise; below it, the model is overconfident.">
      <Chart
        label={`Range calibration of ${v.model.name}: ${rows.map((r) => `${pct(r.level)} stated, ${pct(r.achieved)} achieved`).join('; ')}.`}
        render={(width) =>
          Plot.plot({
            ...base(Math.min(width, 420), 300),
            x: { label: 'Stated', domain: [0.4, 1], tickFormat: '.0%', grid: true },
            y: { label: 'Achieved', domain: [0.4, 1], tickFormat: '.0%', grid: true },
            marks: [
              Plot.line([0.4, 1].map((d) => ({ d })), { x: 'd', y: 'd', stroke: 'var(--muted)', strokeDasharray: '3,3' }),
              Plot.line(rows, { x: 'level', y: 'achieved', stroke: MODEL_FAMILY_COLOR[v.model.family], strokeWidth: 2 }),
              Plot.dot(rows, { x: 'level', y: 'achieved', r: 5, fill: MODEL_FAMILY_COLOR[v.model.family], tip: true, title: (d) => `${pct(d.level)} range: ${pct(d.achieved, 1)} inside` }),
            ],
          })
        }
      />
    </Panel>
  )
}

function ByRole({ v, regime }: { v: PredictionModelView; regime: string }) {
  const rows = v.by_role.filter((r) => r.regime === regime)
  return (
    <Panel title="By role" caption="Typical miss for CEOs, CFOs and other members, against the drift baseline on the same executive-years.">
      <Table
        caption="Error by role"
        rows={rows}
        rowKey={(r) => r.role}
        sort={{ key: 'role', desc: false }}
        columns={[
          { key: 'role', label: 'Role', value: (r) => ROLE_LABEL[r.role] },
          { key: 'n', label: 'Pairs', numeric: true, value: (r) => r.n, render: (r) => r.n.toLocaleString('en-GB') },
          { key: 'mae', label: 'Miss', numeric: true, value: (r) => r.mae, render: (r) => logPct(r.mae) },
          { key: 'ref', label: 'Baseline', numeric: true, value: (r) => r.mae_ref, render: (r) => logPct(r.mae_ref) },
        ]}
      />
    </Panel>
  )
}

function Specific({ v }: { v: PredictionModelView }) {
  if (v.coefficients) {
    const rows = v.coefficients.map((c) => ({ ...c, effect: Math.expm1(c.coef) }))
    return (
      <Panel title="What the model learned" caption="Effect of one unit of each input on the predicted value (total pay, fitted on every pair): +10 % means 10 % more pay, all else equal. Log inputs: effect of doubling ≈ coefficient × 0.69.">
        <Chart
          label={`Coefficients of ${v.model.name}.`}
          render={(width) => {
            const labels = labelAxis(rows.map((r) => r.feature), width)
            return Plot.plot({
              ...base(width, rows.length * 24 + 40),
              marginLeft: labels.marginLeft,
              x: { label: null, grid: true, tickFormat: '+.0%', ticks: narrow(width) ? 4 : undefined },
              y: { label: null, domain: rows.map((r) => r.feature), tickFormat: labels.tickFormat },
              marks: [
                Plot.ruleX([0], { stroke: 'var(--muted)' }),
                Plot.barX(rows, { x: 'effect', y: 'feature', fill: (d) => (d.effect >= 0 ? 'var(--accent)' : 'var(--warn)'), tip: true, title: (d) => `${d.feature}: ${signed(d.effect)}` }),
              ],
            })
          }}
        />
      </Panel>
    )
  }
  if (v.importance?.length) {
    const features = v.importance.map((r) => r.feature)
    return (
      <Panel title="What the model looks at" caption="Permutation importance (total pay): how much the error grows when one input is shuffled. The last value and the horizon carry almost everything.">
        <Chart
          label={`Feature importance of ${v.model.name}; the most important input is ${features[0]}.`}
          render={(width) => {
            const labels = labelAxis(features, width)
            return Plot.plot({
              ...base(width, features.length * 24 + 40),
              marginLeft: labels.marginLeft,
              x: { label: null, grid: true, ticks: narrow(width) ? 4 : undefined },
              y: { label: null, domain: features, tickFormat: labels.tickFormat },
              marks: [Plot.barX(v.importance!, { x: 'importance', y: 'feature', fill: MODEL_FAMILY_COLOR[v.model.family], tip: true })],
            })
          }}
        />
      </Panel>
    )
  }
  if (v.firms) {
    return (
      <Panel title="Firm effects and their weight" caption="Each firm's average deviation from the linear model and the weight it gets: firms with few executive-years are pulled toward zero. Largest firms by observations.">
        <Table
          caption="Firm effects"
          rows={v.firms}
          rowKey={(r) => r.firm_id}
          sort={{ key: 'n', desc: true }}
          tall
          columns={[
            { key: 'firm', label: 'Company', value: (r) => r.firm, render: (r) => <a href={`#/companies/${r.firm_id}`}>{r.firm}</a> },
            { key: 'n', label: 'Pairs', numeric: true, value: (r) => r.n },
            { key: 'effect', label: 'Raw effect', numeric: true, value: (r) => r.effect, render: (r) => logPct(r.effect) },
            { key: 'weight', label: 'Weight', numeric: true, value: (r) => r.weight, render: (r) => pct(r.weight) },
            { key: 'used', label: 'Used', numeric: true, value: (r) => r.effect * r.weight, render: (r) => logPct(r.effect * r.weight) },
          ]}
        />
      </Panel>
    )
  }
  if (v.seeds?.length) {
    return (
      <Panel title="Same data, different luck" caption={`Typical miss on total pay for ${spell(v.seeds.length)} runs that differ only in the random starting weights. A model whose accuracy depends on the seed is hard to defend in a remuneration report.`}>
        <div className="stats">
          {v.seeds.map((s) => (
            <Stat key={s.seed} label={`Seed ${s.seed}`} value={logPct(s.mae)} />
          ))}
        </div>
      </Panel>
    )
  }
  return null
}

function Misses({ v, label }: { v: PredictionModelView; label: string }) {
  return (
    <Panel title="Largest misses" caption={`${label}: the executive-years this model got most wrong, over all test years. A one-off grant or a new contract explains some; others are the model itself going astray.`}>
      <Table
        caption="Largest misses"
        rows={v.misses}
        rowKey={(r) => `${r.person_id}-${r.year}-${r.h}`}
        sort={{ key: 'error', desc: true }}
        columns={[
          { key: 'name', label: 'Executive', value: (r) => r.name, render: (r) => <a href={`#/people/${r.person_id}`}>{r.name}</a> },
          { key: 'firm', label: 'Company', value: (r) => r.firm },
          { key: 'year', label: 'From', numeric: true, value: (r) => r.year },
          { key: 'h', label: 'Years ahead', numeric: true, value: (r) => r.h },
          { key: 'pred', label: 'Predicted k€', numeric: true, value: (r) => r.predicted, render: (r) => keur(r.predicted) },
          { key: 'act', label: 'Paid k€', numeric: true, value: (r) => r.actual, render: (r) => keur(r.actual) },
          { key: 'error', label: 'Off by', numeric: true, value: (r) => Math.abs(r.error), render: (r) => `×${Math.exp(Math.abs(r.error)).toFixed(1)}` },
        ]}
      />
    </Panel>
  )
}

// ------------------------------------------------------------------ executive page

export function PersonForecast({ id }: { id: string }) {
  const [method, setMethod] = useState<string>()
  const state = usePrevious(useApi<PersonPrediction>(`/people/${encodeURIComponent(id)}/prediction${method ? `?peer_method=${method}` : ''}`))
  const overview = useApi<PredictionOverview>('/prediction')
  if (state.error?.startsWith('404')) return null
  return (
    <Async state={state} height={1400}>
      {(p) => (
        <div className={state.stale ? 'page-body stale' : 'page-body'} aria-busy={state.stale}>
          <Forecast p={p} o={overview.data} setMethod={setMethod} />
        </div>
      )}
    </Async>
  )
}

function Forecast({ p, o, setMethod }: { p: PersonPrediction; o?: PredictionOverview; setMethod: (m: string) => void }) {
  const targets = o?.targets ?? p.history.map((h) => ({ id: h.target, label: h.target }))
  const has = new Set(p.forecasts.map((f) => f.target))
  const [target, setTarget] = useState('total')
  const [picked, setModel] = useState<string>()
  const model = picked ?? p.best[target]
  const label = targets.find((t) => t.id === target)?.label ?? target
  const modelName = (m: string) => o?.models.find((x) => x.id === m)?.name ?? m
  const history = (p.history.find((h) => h.target === target)?.years ?? []).filter((y): y is { year: number; value: number } => y.value != null)
  const fan = p.forecasts.filter((f) => f.target === target && f.model === model).sort((a, b) => a.h - b.h)
  const last = history.filter((h) => h.year === p.year)
  const path = [...last.map((h) => ({ year: h.year, value: h.value, lo: h.value, hi: h.value })), ...fan.map((f) => ({ year: f.year, value: f.value, lo: f.lo ?? f.value, hi: f.hi ?? f.value }))]
  const next = fan[0]
  const paid = p.paid.find((x) => x.target === target && x.year === p.year + 1)
  const peer = p.peers.find((x) => x.target === target)
  const models = [...new Set(p.forecasts.filter((f) => f.target === target).map((f) => f.model))]
  return (
    <Panel
      title="Forecast and comparison"
      caption={`${label} from ${p.year}, k€: history, the forecast median and its ${pct(p.band)} range. Assumes ${p.name} stays ${ROLE_LABEL[p.role]} at ${p.firm}.`}
      controls={
        <label className="field">
          <span>Model</span>
          <select value={model} onChange={(e) => setModel(e.target.value)}>
            {models.map((m) => (
              <option key={m} value={m}>
                {modelName(m)}
                {m === p.best[target] ? ' (best)' : ''}
              </option>
            ))}
          </select>
        </label>
      }
      note={fan.some((f) => f.source && f.source !== p.regime) ? `Ranges for horizons that ${REGIME_LABEL[p.regime] ?? p.regime} reporting cannot test yet come from the errors of all test years, so they are wider.` : undefined}
    >
      <Segmented label="Pay item" value={target} onChange={(t) => (setTarget(t), setModel(undefined))} options={targets.filter((t) => has.has(t.id) || t.id === target).map((t) => ({ value: t.id, label: t.label }))} />
      <div className="stats">
        <Stat label={`${label} ${p.year + 1}`} value={next ? meur(next.value) : '–'} sub={next?.lo != null ? `${pct(p.band)} range ${meur(next.lo)}–${meur(next.hi)}` : 'no forecast: not paid now'} />
        {paid && <Stat label={`Paid in ${paid.year}`} value={pct(paid.p)} sub="chance the item is paid at all" />}
        {peer && peer.percentile != null && (
          <Stat label="Among peers" value={pct(peer.percentile)} sub={`of ${peer.n} peer ${ROLE_LABEL[p.role]}s earn less; median ${meur(peer.median)}`} />
        )}
        {p.staff_ratio != null && <Stat label="Against staff" value={`${p.staff_ratio.toFixed(0)}×`} sub={`total pay vs. average staff cost (${keur(p.avg_staff_cost)} k€)`} />}
      </div>
      <Chart
        label={`${label} of ${p.name}: history and ${modelName(model)} forecast${next ? `, ${meur(next.value)} next year` : ''}.`}
        render={(width) =>
          Plot.plot({
            ...base(width, 300),
            marginLeft: 58,
            x: { ...yearAxis, label: null },
            y: { label: 'k€', grid: true, zero: true },
            marks: [
              Plot.areaY(path, { x: 'year', y1: 'lo', y2: 'hi', fill: 'var(--c-band)', fillOpacity: 0.15 }),
              Plot.line(history, { x: 'year', y: 'value', stroke: 'var(--ink)', strokeWidth: 2 }),
              Plot.dot(history, { x: 'year', y: 'value', fill: 'var(--ink)', r: 3, tip: true, title: (d) => `${d.year}: ${keur(d.value)} k€` }),
              Plot.line(path, { x: 'year', y: 'value', stroke: 'var(--c-band)', strokeWidth: 2, strokeDasharray: '5,4' }),
              Plot.dot(fan, { x: 'year', y: 'value', fill: 'var(--c-band)', r: 3, tip: true, title: (d) => `${d.year}: ${keur(d.value)} k€\nrange ${keur(d.lo)}–${keur(d.hi)} k€` }),
            ],
          })
        }
      />
      <div className="grid-2">
        <Board p={p} />
        <Peers p={p} target={target} label={label} setMethod={setMethod} />
      </div>
      <WhatIfPanel p={p} labels={new Map(targets.map((t) => [t.id, t.label]))} />
    </Panel>
  )
}

function Board({ p }: { p: PersonPrediction }) {
  return (
    <div className="subchart">
      <h3>Same board, {p.year}</h3>
      <p className="caption">Total pay of each full-year board member, k€, with the multiple of the CEO's pay.</p>
      <Chart
        label={`Board of ${p.firm} in ${p.year}; ${p.name} is highlighted.`}
        render={(width) => {
          const labels = labelAxis(p.board.map((b) => b.name), width)
          return Plot.plot({
            ...base(width, p.board.length * 26 + 40),
            marginLeft: labels.marginLeft,
            marginRight: 60,
            x: { label: null, grid: true, ticks: narrow(width) ? 3 : undefined },
            y: { label: null, domain: p.board.map((b) => b.name), tickFormat: labels.tickFormat },
            marks: [
              Plot.barX(p.board, { x: 'total', y: 'name', fill: (d) => (d.is_self ? 'var(--accent)' : 'var(--c-member)'), fillOpacity: (d) => (d.is_self ? 1 : 0.5), tip: true, title: (d: PersonPrediction['board'][number]) => `${d.name} (${ROLE_LABEL[d.role]})\n${keur(d.total)} k€` }),
              Plot.text(p.board, { x: 'total', y: 'name', text: (d) => (d.ratio_to_ceo == null ? '' : multiple(d.ratio_to_ceo)), dx: 6, textAnchor: 'start', fill: 'var(--muted)', fontSize: 11 }),
            ],
          })
        }}
      />
    </div>
  )
}

function Peers({ p, target, label, setMethod }: { p: PersonPrediction; target: string; label: string; setMethod: (m: string) => void }) {
  const q = p.peers.find((x) => x.target === target)
  return (
    <div className="subchart">
      <h3>Peers, {p.year}</h3>
      <label className="field">
        <span>Peer definition</span>
        <select value={p.method} onChange={(e) => setMethod(e.target.value)}>
          {p.methods.map((m) => (
            <option key={m.id} value={m.id}>
              {m.name}
            </option>
          ))}
        </select>
      </label>
      {q ? (
        <>
          <p className="caption">
            {label} of {q.n} peer {ROLE_LABEL[p.role]}s: middle half and 10–90 % range, the line is the median, the dot is {p.name}.
          </p>
          <Chart
            label={`${p.name}'s ${label.toLowerCase()} against peers: median ${meur(q.median)}, own ${meur(q.value)}.`}
            render={(width) =>
              Plot.plot({
                ...base(width, 120),
                marginLeft: 16,
                marginBottom: 40,
                x: { label: 'k€', grid: true, ticks: narrow(width) ? 4 : undefined },
                marks: [
                  Plot.ruleY([0], { x1: q.p10, x2: q.p90, stroke: 'var(--c-member)', strokeWidth: 2 }),
                  Plot.rectX([q], { x1: 'p25', x2: 'p75', y1: -0.4, y2: 0.4, fill: 'var(--c-member)', fillOpacity: 0.35 }),
                  Plot.ruleX([q.median], { y1: -0.5, y2: 0.5, stroke: 'var(--ink)', strokeWidth: 2 }),
                  q.value == null ? null : Plot.dot([q.value], { x: (d) => d, y: 0, r: 7, fill: 'var(--accent)', stroke: 'var(--surface)', strokeWidth: 2 }),
                ],
                y: { domain: [-1, 1], axis: null },
              })
            }
          />
          <p className="caption">Peer firms: {p.peer_firms.map((f) => f.firm).join(', ')}</p>
        </>
      ) : (
        <p className="caption">Too few peers with this item under this definition.</p>
      )}
    </div>
  )
}

function WhatIfPanel({ p, labels }: { p: PersonPrediction; labels: Map<string, string> }) {
  const [role, setRole] = useState<Role>(p.role)
  const [index, setIndex] = useState('')
  const [board, setBoard] = useState('')
  const [growth, setGrowth] = useState('')
  const [years, setYears] = useState(1)
  const horizon = Math.max(1, ...p.forecasts.map((f) => f.h))
  const query = new URLSearchParams({ person_id: p.person_id, years: String(years) })
  if (role !== p.role) query.set('role', role)
  if (index) query.set('index', index)
  if (board) query.set('board', board)
  if (growth) query.set('growth', String(Number(growth) / 100))
  const state = useApi<WhatIf>(`/whatif?${query}`)
  return (
    <div className="subchart">
      <h3>What if?</h3>
      <p className="caption">Change a characteristic and keep what is specific to {p.name}: the effect comes from a regression within each year, so it is an association, not a cause.</p>
      <div className="controls">
        <label className="field">
          <span>Role</span>
          <select value={role} onChange={(e) => setRole(e.target.value as Role)}>
            {(['CEO', 'CFO', 'Member'] as Role[]).map((r) => (
              <option key={r} value={r}>
                {ROLE_LABEL[r]}
              </option>
            ))}
          </select>
        </label>
        <label className="field">
          <span>Index</span>
          <select value={index} onChange={(e) => setIndex(e.target.value)}>
            <option value="">as now</option>
            <option value="DAX">DAX</option>
            <option value="MDAX">MDAX</option>
            <option value="none">none</option>
          </select>
        </label>
        <label className="field">
          <span>Board size</span>
          <input type="number" min={2} max={20} value={board} placeholder="as now" onChange={(e) => setBoard(e.target.value)} />
        </label>
        <label className="field">
          <span>Growth % a year</span>
          <input type="number" step={0.5} value={growth} placeholder="market drift" onChange={(e) => setGrowth(e.target.value)} />
        </label>
        <Segmented label="Years ahead" value={years} onChange={setYears} options={Array.from({ length: horizon }, (_, i) => ({ value: i + 1, label: String(p.year + i + 1) }))} />
      </div>
      <Async state={state} skeleton={<Skeleton height={280} />}>
        {(w) => (
          <>
            <Table
              caption="What-if result"
              rows={w.rows}
              rowKey={(r) => r.target}
              sort={{ key: 'now', desc: true }}
              columns={[
                { key: 'target', label: 'Pay item', value: (r) => labels.get(r.target) ?? r.target },
                { key: 'now', label: `${w.year} k€`, numeric: true, value: (r) => r.now, render: (r) => keur(r.now) },
                { key: 'expected', label: `${w.year + w.years}, as now`, numeric: true, value: (r) => r.expected, render: (r) => keur(r.expected) },
                { key: 'changed', label: `${w.year + w.years}, changed`, numeric: true, value: (r) => r.changed, render: (r) => <strong>{keur(r.changed)}</strong> },
                { key: 'change', label: 'Difference', numeric: true, value: (r) => r.change, render: (r) => signed(r.change) },
              ]}
            />
            {w.promotion && (
              <p className="caption">
                Observed in the data: {w.promotion.n} executives who moved from {ROLE_LABEL[w.role]} to {ROLE_LABEL[role]} at the same firm got a median {signed(Math.expm1(w.promotion.change))} the next year.
              </p>
            )}
          </>
        )}
      </Async>
    </div>
  )
}

// ------------------------------------------------------------------ company page

export function FirmForecastPanel({ id }: { id: string }) {
  const state = useApi<FirmForecast[]>(`/firms/${encodeURIComponent(id)}/prediction`)
  const overview = useApi<PredictionOverview>('/prediction')
  if (state.error?.startsWith('404') || (state.data && !state.data.length)) return null
  const range = overview.data ? `${pct(overview.data.band)} range` : 'range'
  return (
    <Async state={state} height={340}>
      {(rows) => {
        const year = rows[0].year
        const names = [...rows].sort((a, b) => b.value - a.value).map((r) => r.name)
        return (
          <Panel title={`Board pay forecast for ${year}`} caption={`Total pay of each current full-year board member next year, k€: forecast median, ${range}, and the tick for ${year - 1}. Model: the most accurate for total pay.`}>
            <Chart
              label={`Forecast total pay for ${year} of ${rows.length} board members.`}
              render={(width) => {
                const labels = labelAxis(names, width)
                return Plot.plot({
                  ...base(width, rows.length * 30 + 50),
                  marginLeft: labels.marginLeft,
                  x: { label: 'k€', grid: true, ticks: narrow(width) ? 4 : undefined },
                  y: { label: null, domain: names, tickFormat: labels.tickFormat },
                  marks: [
                    Plot.ruleY(rows, { y: 'name', x1: 'lo', x2: 'hi', stroke: 'var(--c-band)', strokeOpacity: 0.4, strokeWidth: 8 }),
                    Plot.tickX(rows, { y: 'name', x: 'total', stroke: 'var(--muted)', strokeWidth: 2 }),
                    Plot.dot(rows, { y: 'name', x: 'value', r: 5, fill: 'var(--c-band)', tip: true, title: (d: FirmForecast) => `${d.name} (${ROLE_LABEL[d.role]})\n${year - 1}: ${keur(d.total)} k€\n${year}: ${keur(d.value)} k€ (${keur(d.lo)}–${keur(d.hi)})` }),
                  ],
                })
              }}
            />
            <p className="caption">
              Per executive:{' '}
              {rows.map((r, i) => (
                <span key={r.person_id}>
                  {i > 0 && ', '}
                  <a href={`#/people/${r.person_id}`}>{r.name}</a>
                </span>
              ))}{' '}
              — each pay item, board and peer comparison, what-if.
            </p>
          </Panel>
        )
      }}
    </Async>
  )
}
