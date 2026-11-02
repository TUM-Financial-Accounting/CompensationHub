import type { Component, Role } from './api'

const int = new Intl.NumberFormat('en-GB', { maximumFractionDigits: 0 })

type N = number | null | undefined

/** k€ as a plain grouped number, for tables headed "k€". */
export const keur = (v: N) => (v == null ? '–' : int.format(v))
/** k€ as "€5.5M". */
export const meur = (v: N, digits = 1) => (v == null ? '–' : `€${(v / 1000).toFixed(digits)}M`)
export const pct = (v: N, digits = 0) => (v == null ? '–' : `${(v * 100).toFixed(digits)}%`)
export const signed = (v: N) => (v == null ? '–' : `${v > 0 ? '+' : ''}${(v * 100).toFixed(0)}%`)
export const times = (v: N) => (v == null ? '–' : `${v.toFixed(0)}×`)
/** A ratio such as pay ÷ peer median: "1.66×". */
export const multiple = (v: N, digits = 2) => (v == null ? '–' : `${v.toFixed(digits)}×`)
/** A log difference as the percentage it stands for: 0.31 → "36%". */
export const logPct = (v: N, digits = 0) => (v == null ? '–' : pct(Math.exp(v) - 1, digits))

const WORDS = ['no', 'one', 'two', 'three', 'four', 'five', 'six', 'seven', 'eight', 'nine', 'ten', 'eleven', 'twelve', 'thirteen', 'fourteen', 'fifteen', 'sixteen', 'seventeen', 'eighteen', 'nineteen', 'twenty']
/** A count in prose: "six", or digits above twenty; `start` capitalises it for the beginning of a sentence. */
export const spell = (n: number, start = false) => {
  const w = WORDS[n] ?? String(n)
  return start ? w.charAt(0).toUpperCase() + w.slice(1) : w
}

export const COMPONENT_LABEL: Record<Component, string> = {
  fixed: 'Fixed salary',
  sti: 'Annual bonus',
  mti: 'Multi-year bonus',
  lti: 'Share-based pay',
  other: 'Other benefits',
}
export const COMPONENT_COLOR: Record<Component, string> = {
  fixed: 'var(--c-fixed)',
  sti: 'var(--c-sti)',
  mti: 'var(--c-mti)',
  lti: 'var(--c-lti)',
  other: 'var(--c-other)',
}

export const ROLE_LABEL: Record<Role, string> = { CEO: 'CEO', CFO: 'CFO', Member: 'Other members' }
export const ROLE_COLOR: Record<Role, string> = { CEO: 'var(--c-ceo)', CFO: 'var(--c-cfo)', Member: 'var(--c-member)' }
