import { Component, useEffect, useLayoutEffect, useMemo, useRef, useState, type ReactNode } from 'react'

import type { Loadable } from './api'
import { ChevronRight } from './icons'

/** Charts already drawn this session: they appear without the draw-in when shown again. */
const seen = new Set<string>()
const DRAW_MS = 600
const MARKS = ':scope > g:not([aria-label*="axis"], [aria-label*="grid"], [aria-label="tip"], [aria-label="frame"])'
const still = matchMedia('(prefers-reduced-motion: reduce)')

/** First sight of a chart: its marks sweep in from the left while axes stay put. The page re-renders
 *  charts as it settles, so each new node continues the sweep from where the last one was. */
function drawIn(node: Element, since: number) {
  const t = performance.now() - since
  if (t >= DRAW_MS || still.matches) return
  const plots = node.tagName === 'svg' ? [node] : [...node.querySelectorAll(':scope > svg')]
  for (const g of plots.flatMap((p) => [...p.querySelectorAll(MARKS)]))
    g.animate([{ clipPath: 'inset(0 100% 0 0)' }, { clipPath: 'inset(0)' }], { duration: DRAW_MS, easing: 'cubic-bezier(0.23, 1, 0.32, 1)' }).currentTime = t
}

/** Renders an Observable Plot figure at the container's width; redraws on resize and re-render.
 *  With `minWidth`, a narrower screen scrolls the chart sideways instead of squeezing it (wide heatmaps). */
export function Chart({ render, label, minWidth }: { render: (width: number) => Element; label: string; minWidth?: number }) {
  const ref = useRef<HTMLDivElement>(null)
  const [width, setWidth] = useState(0)
  const since = useRef<number>(null)

  useLayoutEffect(() => {
    const observer = new ResizeObserver(([entry]) => setWidth(Math.floor(entry.contentRect.width)))
    observer.observe(ref.current!)
    return () => observer.disconnect()
  }, [])

  useEffect(() => {
    if (width < 200) return // ignore transient layouts (e.g. mid-resize); charts need room for axes
    const node = render(width)
    since.current ??= seen.has(label) ? 0 : performance.now()
    seen.add(label)
    drawIn(node, since.current)
    ref.current!.replaceChildren(node)
    return () => node.remove()
  })

  const chart = <div ref={ref} className="chart" role="img" aria-label={label} style={minWidth ? { minWidth } : undefined} />
  return minWidth ? (
    <div className="chart-scroll" tabIndex={0}>
      {chart}
    </div>
  ) : (
    chart
  )
}

export function Panel(props: {
  title: string
  caption?: ReactNode
  controls?: ReactNode
  note?: ReactNode
  children: ReactNode
}) {
  return (
    <section className="panel">
      <div className="panel-head">
        <div className="panel-title">
          <h2>{props.title}</h2>
          {props.caption && <p className="caption">{props.caption}</p>}
        </div>
        {props.controls && <div className="controls">{props.controls}</div>}
      </div>
      {props.children}
      {props.note && <p className="note">{props.note}</p>}
    </section>
  )
}

export function PageHead({ crumb, title, children }: { crumb?: ReactNode; title: string; children?: ReactNode }) {
  return (
    <header className="page-head">
      {crumb && (
        <p className="crumb">
          {crumb}
          <ChevronRight size={14} />
        </p>
      )}
      <h1 tabIndex={-1}>{title}</h1>
      {children && <p>{children}</p>}
    </header>
  )
}

export function Stat({ label, value, sub }: { label: string; value: ReactNode; sub?: ReactNode }) {
  return (
    <div className="stat">
      <span className="stat-label">{label}</span>
      <span className="stat-value">{value}</span>
      {sub && <span className="stat-sub">{sub}</span>}
    </div>
  )
}

export function Legend({ items }: { items: { label: string; color: string; shape?: 'box' | 'line' | 'dash' | 'circle' | 'triangle' | 'square' | 'diamond' }[] }) {
  return (
    <div className="legend">
      {items.map((i) => (
        <span key={i.label}>
          <i className={`swatch ${i.shape ?? 'box'}`} style={{ background: i.color, borderColor: i.color }} />
          {i.label}
        </span>
      ))}
    </div>
  )
}

/** Segmented control; the highlight slides to the picked option (`title` names icon-only options). */
export function Segmented<T extends string | number>(props: {
  label: string
  options: { value: T; label: ReactNode; title?: string }[]
  value: T
  onChange: (v: T) => void
}) {
  const track = useRef<HTMLDivElement>(null)

  useLayoutEffect(() => {
    const el = track.current!
    const place = () => {
      const on = el.querySelector<HTMLElement>('[aria-pressed="true"]')
      if (!on) {
        delete el.dataset.thumb
        return
      }
      el.style.setProperty('--thumb-x', `${on.offsetLeft}px`)
      el.style.setProperty('--thumb-w', `${on.offsetWidth}px`)
      el.dataset.thumb = ''
    }
    place()
    // Option widths change when the web font arrives or the labels change.
    const observer = new ResizeObserver(place)
    el.querySelectorAll('button').forEach((b) => observer.observe(b))
    return () => observer.disconnect()
  }, [props.value, props.options.length])

  return (
    <div className="field" role="group" aria-label={props.label}>
      <span className="seg-label">{props.label}</span>
      <div className="seg" ref={track}>
        {props.options.map((o) => (
          <button key={o.value} type="button" aria-pressed={o.value === props.value} aria-label={o.title} title={o.title} onClick={() => props.onChange(o.value)}>
            {o.label}
          </button>
        ))}
      </div>
    </div>
  )
}

export function Skeleton({ width, height = 14, className }: { width?: number | string; height?: number | string; className?: string }) {
  return <span className={className ? `skeleton ${className}` : 'skeleton'} style={{ width, height }} aria-hidden="true" />
}

const Loading = () => <span className="sr-only">Loading…</span>

function PanelSkeleton({ height }: { height: number }) {
  return (
    <div className="panel" aria-busy="true">
      <Loading />
      <div className="panel-title">
        <Skeleton width="40%" height={20} />
        <Skeleton width="70%" />
      </div>
      <Skeleton height={height} />
    </div>
  )
}

/** Stand-in for a page body made of several panels, one per block height. */
export function PanelsSkeleton({ heights }: { heights: number[] }) {
  return (
    <>
      {heights.map((h, i) => (
        <PanelSkeleton key={i} height={h} />
      ))}
    </>
  )
}

/** Stand-in for a whole page (crumb, title, four stat cards, one panel) while its data loads. */
export function PageSkeleton() {
  return (
    <div className="page-skeleton" aria-busy="true">
      <Loading />
      <Skeleton width={140} height={12} />
      <Skeleton width="min(100%, 360px)" height={32} />
      <div className="stats">
        {[0, 1, 2, 3].map((i) => (
          <div key={i} className="stat">
            <Skeleton width="55%" height={12} />
            <Skeleton width="75%" height={28} />
          </div>
        ))}
      </div>
      <PanelSkeleton height={320} />
    </div>
  )
}

/** Keeps a crash in one page from blanking the app: the shell stays usable and the routed page is
 *  replaced by the error. The page's `main` is keyed by route, so navigating away resets it. */
export class ErrorBoundary extends Component<{ children: ReactNode }, { error?: Error }> {
  state: { error?: Error } = {}

  static getDerivedStateFromError(error: Error) {
    return { error }
  }

  render() {
    const { error } = this.state
    if (!error) return this.props.children
    return (
      <div className="panel error" role="alert">
        <h2>This page could not be shown</h2>
        <code className="error-detail">{error.message}</code>
        <button type="button" className="button" onClick={() => location.reload()}>
          Reload page
        </button>
      </div>
    )
  }
}

/** Loading skeleton / error with retry / content. */
export function Async<T>(props: { state: Loadable<T>; height?: number; skeleton?: ReactNode; children: (data: T) => ReactNode }) {
  const { state } = props
  if (state.error)
    return (
      <div className="panel error" role="alert">
        <p>Could not load this data. Is the backend running on port 8000?</p>
        <code className="error-detail">{state.error}</code>
        <button type="button" className="button" onClick={state.reload}>
          Try again
        </button>
      </div>
    )
  if (state.data === undefined) return props.skeleton ?? <PanelSkeleton height={props.height ?? 320} />
  return <>{props.children(state.data)}</>
}

// ------------------------------------------------------------------ sortable table

export interface Column<T> {
  key: string
  label: string
  value: (row: T) => string | number | null | undefined
  render?: (row: T) => ReactNode
  numeric?: boolean
  wrap?: boolean // long text: wrap instead of widening the table
}

type Sort = { key: string; desc: boolean }

export function Table<T>(props: { rows: T[]; columns: Column<T>[]; sort: Sort; caption: string; tall?: boolean; rowKey: (row: T) => string }) {
  const [sort, setSort] = useState(props.sort)
  const column = props.columns.find((c) => c.key === sort.key) ?? props.columns[0]

  const rows = useMemo(() => {
    const sign = sort.desc ? -1 : 1
    return [...props.rows].sort((a, b) => {
      const x = column.value(a)
      const y = column.value(b)
      if (x == null) return 1 // missing values last in either direction
      if (y == null) return -1
      return (typeof x === 'number' && typeof y === 'number' ? x - y : String(x).localeCompare(String(y))) * sign
    })
  }, [props.rows, column, sort.desc])

  return (
    <div className={`table-wrap${props.tall ? ' tall' : ''}`}>
      <table aria-label={props.caption}>
        <thead>
          <tr>
            {props.columns.map((c) => (
              <th
                key={c.key}
                scope="col"
                className={c.numeric ? 'num' : undefined}
                aria-sort={c.key === sort.key ? (sort.desc ? 'descending' : 'ascending') : 'none'}
              >
                <button type="button" onClick={() => setSort({ key: c.key, desc: c.key === sort.key ? !sort.desc : !!c.numeric })}>
                  {c.label}
                </button>
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((r) => (
            <tr key={props.rowKey(r)}>
              {props.columns.map((c) => (
                <td key={c.key} className={[c.numeric && 'num', c.wrap && 'wrap'].filter(Boolean).join(' ') || undefined}>
                  {c.render ? c.render(r) : (c.value(r) ?? '–')}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}
