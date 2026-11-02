import * as Plot from '@observablehq/plot'

import { COMPONENTS, type ModelFamily, type PeerFamily } from './api'
import { COMPONENT_COLOR, COMPONENT_LABEL, ROLE_COLOR, ROLE_LABEL } from './format'

/** Phone-sized chart: ~320 px of room, so axes thin out and labels are shortened. */
export const narrow = (width: number) => width < 520

/** Shared look: muted axes, light grid, body font, tips on the page surface. */
export const base = (width: number, height = 320): Plot.PlotOptions => ({
  width,
  height,
  marginTop: 28,
  marginLeft: narrow(width) ? 46 : 52,
  marginRight: 16,
  marginBottom: 40, // room for a long axis label under the last tick
  style: { fontSize: '12px', color: 'var(--muted)', background: 'transparent' },
})

const GLYPH = 6.5 // average glyph width in px at the 12 px chart font

/** Left margin and tick format for category labels on a y axis: as wide as the longest label, but at most
 *  `share` of the chart; longer labels are cut with an ellipsis (the tip carries the full text). */
export function labelAxis(labels: string[], width: number, share = 0.42) {
  const longest = labels.reduce((m, l) => Math.max(m, l.length), 0)
  const fit = Math.max(4, Math.min(longest, Math.floor((width * share - 16) / GLYPH)))
  return {
    marginLeft: Math.round(fit * GLYPH + 16),
    tickFormat: (l: string) => (l.length > fit ? `${l.slice(0, fit - 1)}…` : l),
  }
}

/** Click handler for a chart's highlighted mark. With `confirmTap`, a touch screen's first tap only shows the
 *  mark's tip and tapping the same mark again acts (for actions that leave the page). */
export function onPick<T>(plot: Element & ElementCSSInlineStyle, act: (d: T) => void, confirmTap = true) {
  let armed: T | undefined
  plot.addEventListener('click', () => {
    const d = (plot as unknown as { value?: T }).value
    if (!d) return
    if (confirmTap && matchMedia('(hover: none)').matches && d !== armed) {
      armed = d
      return
    }
    act(d)
  })
  plot.style.cursor = 'pointer'
}

export const yearAxis: Plot.ScaleOptions = { label: null, tickFormat: 'd', nice: false }

/** §162 AktG (ARUG II) reporting starts with financial year 2022: a legal fact, not a data property. */
export const REGIME_BREAK = 2021.5

/** Vertical marker for the disclosure-regime break on a linear year axis; the label is shortened on narrow charts,
 *  where the break sits too close to the right edge for the full text. */
export const regimeBreak = (width: number, label = narrow(width) ? '§162 →' : '§162 AktG →') => [
  Plot.ruleX([REGIME_BREAK], { stroke: 'var(--muted)', strokeDasharray: '3,3', strokeOpacity: 0.7 }),
  Plot.text([REGIME_BREAK], { x: (d: number) => d, frameAnchor: 'top', dx: 4, dy: -12, text: () => label, textAnchor: 'start', fill: 'var(--muted)', fontSize: 11 }),
]

export const componentScale: Plot.ScaleOptions = {
  domain: COMPONENTS.map((c) => COMPONENT_LABEL[c]),
  range: COMPONENTS.map((c) => COMPONENT_COLOR[c]),
}

export const roleScale: Plot.ScaleOptions = {
  domain: Object.values(ROLE_LABEL),
  range: Object.values(ROLE_COLOR),
}

/** Year bars on a linear axis, so the regime-break rule can sit between 2021 and 2022. */
export const yearBar = { x1: (d: { year: number }) => d.year - 0.38, x2: (d: { year: number }) => d.year + 0.38 }

/** Fill for years where only a board total is known (opt-out). */
export const OPT_OUT_FILL = 'color-mix(in srgb, var(--muted) 35%, transparent)'

/** One stacked segment of a year bar. */
export type Bar = { year: number; label: string; value: number }

/** k€ axis labelled in millions. */
export const meurAxis = (label = '€ million'): Plot.ScaleOptions => ({
  label,
  grid: true,
  tickFormat: (v: number) => (v / 1000).toLocaleString('en-GB'),
})

// ------------------------------------------------------------------ peer benchmark

/** One hue per family of peer definitions (validated colour-blind safe for any pair, light and dark). */
export const FAMILY_COLOR: Record<PeerFamily, string> = {
  groups: 'var(--c-groups)',
  industry: 'var(--c-industry)',
  neighbours: 'var(--c-neighbours)',
  baseline: 'var(--c-member)',
}
export const FAMILY_LABEL: Record<PeerFamily, string> = {
  groups: 'Fixed groups',
  industry: 'Industry first',
  neighbours: 'Nearest neighbours',
  baseline: 'No selection',
}

/** A hue per definition would be too many for dots that sit side by side, so colour carries the family
 *  and the symbol the definition within it (first circle, second triangle, …). */
const SYMBOLS = ['circle', 'triangle', 'square', 'diamond'] as const

export function methodStyle(methods: { name: string; family: PeerFamily }[]) {
  const seen = new Map<PeerFamily, number>()
  const style = methods.map((m) => {
    const n = seen.get(m.family) ?? 0
    seen.set(m.family, n + 1)
    return { name: m.name, color: FAMILY_COLOR[m.family], symbol: SYMBOLS[n % SYMBOLS.length] }
  })
  return {
    style,
    color: { domain: style.map((s) => s.name), range: style.map((s) => s.color) } as Plot.ScaleOptions,
    symbol: { domain: style.map((s) => s.name), range: style.map((s) => s.symbol) } as Plot.ScaleOptions,
  }
}

/** Height a centred beeswarm needs: the dots of its fullest 2r-wide stretch, stacked (plus the margins of `base`).
 *  `positions` are the dots' x positions as fractions (0–1) of the inner width. */
export function swarmHeight(positions: number[], innerWidth: number, r: number) {
  const xs = positions.map((p) => p * innerWidth).sort((a, b) => a - b)
  let tallest = 0
  for (let i = 0, j = 0; i < xs.length; i++) {
    while (xs[i] - xs[j] >= 2 * r) j++
    tallest = Math.max(tallest, i - j + 1)
  }
  return Math.min(900, tallest * (2 * r + 1) + 70)
}

/** Domain of a pay ÷ peer median axis: at least 0.5×–2×, with some air. */
const ratioDomain = (values: number[]) => [Math.min(0.5, ...values) * 0.9, Math.max(2, ...values) * 1.1]

/** Where each ratio falls on ratioAxis, as a fraction of the axis (for swarmHeight). */
export function ratioPositions(values: number[]) {
  const [lo, hi] = ratioDomain(values).map(Math.log)
  return values.map((v) => (Math.log(v) - lo) / (hi - lo))
}

/** Log axis for pay ÷ peer median, labelled as multiples; fewer ticks when `width` is narrow. */
export function ratioAxis(values: number[], width: number, label = 'Pay ÷ peer median'): Plot.ScaleOptions {
  const [lo, hi] = ratioDomain(values)
  const all = narrow(width) ? [0.2, 0.5, 1, 2, 5, 10] : [0.1, 0.2, 0.33, 0.5, 0.67, 1, 1.5, 2, 3, 5, 10, 20]
  const ticks = all.filter((t) => t >= lo && t <= hi)
  return { type: 'log', domain: [lo, hi], ticks, tickFormat: (v: number) => `${v}×`, label, grid: true }
}

/** Shaded verdict zones behind a ratio axis: below 1 / high and above high (pay ÷ peer median). The zones end at
 *  the axis domain: a rect reaching past the plot would be clipped, but still counts towards the page's width. */
export const verdictZones = (high: number, axis: Plot.ScaleOptions, dir: 'x' | 'y' = 'x') => {
  const [lo, hi] = axis.domain as [number, number]
  const zone = (from: number, to: number, fill: string) =>
    dir === 'x'
      ? Plot.rectX([0], { x1: from, x2: to, fill, fillOpacity: 0.09 })
      : Plot.rectY([0], { y1: from, y2: to, fill, fillOpacity: 0.09 })
  const rule = dir === 'x' ? Plot.ruleX([1], { stroke: 'var(--muted)' }) : Plot.ruleY([1], { stroke: 'var(--muted)' })
  return [zone(high, hi, 'var(--warn)'), zone(lo, 1 / high, 'var(--accent)'), rule]
}

// ------------------------------------------------------------------ pay prediction

export const MODEL_FAMILY_COLOR: Record<ModelFamily, string> = {
  own: 'var(--c-own)',
  reference: 'var(--c-reference)',
  level: 'var(--c-level)',
  change: 'var(--c-change)',
}
export const MODEL_FAMILY_LABEL: Record<ModelFamily, string> = {
  own: 'Own past',
  reference: 'Comparable executives',
  level: 'Expected pay',
  change: 'Change models',
}
