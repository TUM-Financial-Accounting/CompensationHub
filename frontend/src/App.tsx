import { useEffect, useRef, useState, type ReactNode, type RefObject } from 'react'

import { useApi, type PeerOverview, type PredictionOverview } from './api'
import { MODEL_FAMILY_COLOR } from './charts'
import { ChatProvider } from './ChatProvider'
import { BarChart, Briefcase, Building2, Home, LineChart, Menu, MessageSquare, Monitor, Moon, Plus, Scale, ShieldCheck, SlidersHorizontal, Sun, TrendingUp, Users, X } from './icons'
import { useScrollLock } from './lock'
import { useTheme, type Theme } from './theme'
import { ErrorBoundary, Segmented } from './ui'

import { AddDataSheet } from './views/AddData'
import { AssistantPanel, AssistantView } from './views/Assistant'
import { Board } from './views/Board'
import { Companies, Company } from './views/Companies'
import { Design } from './views/Design'
import { Executives, PersonView } from './views/Executives'
import { Overview } from './views/Overview'
import { MethodMark, PeerMethodPage, PeersView } from './views/Peers'
import { PredictionModelPage, PredictionView } from './views/Prediction'
import { QualityView } from './views/Quality'
import { TrendsView } from './views/Trends'

const NAV = [
  ['', 'Overview', Home],
  ['assistant', 'Assistant', MessageSquare],
  ['trends', 'Pay trends', TrendingUp],
  ['companies', 'Companies', Building2],
  ['executives', 'Executives', Users],
  ['peers', 'Peer benchmark', Scale],
  ['prediction', 'Pay prediction', LineChart],
  ['design', 'Pay design', SlidersHorizontal],
  ['board', 'Board & workforce', Briefcase],
  ['data', 'Data quality', ShieldCheck],
] as const

/** Hash routes keep every view deep-linkable without a router dependency: #/companies/sap */
function useRoute(): string[] {
  const read = () => decodeURIComponent(location.hash.replace(/^#\/?/, '')).split('/').filter(Boolean)
  const [route, setRoute] = useState(read)
  useEffect(() => {
    const onChange = () => setRoute(read())
    addEventListener('hashchange', onChange)
    return () => removeEventListener('hashchange', onChange)
  }, [])
  return route
}

function page([section, id]: string[]) {
  switch (section) {
    case undefined:
      return <Overview />
    case 'trends':
      return <TrendsView />
    case 'companies':
      return id ? <Company id={id} /> : <Companies />
    case 'executives':
      return <Executives />
    case 'people':
      return <PersonView id={id} />
    case 'peers':
      return id ? <PeerMethodPage id={id} /> : <PeersView />
    case 'prediction':
      return id ? <PredictionModelPage key={id} id={id} /> : <PredictionView />
    case 'assistant':
      return <AssistantView />
    case 'design':
      return <Design />
    case 'board':
      return <Board />
    case 'data':
      return <QualityView />
    default:
      return <p>Page not found. <a href="#/">Back to the overview</a>.</p>
  }
}

interface PageSection {
  title: string
  el: HTMLElement
}

/** Titles of the panels on the current page, re-read whenever the page's content changes
 *  (panels appear after their data loads), so the sidebar can jump to them. */
function usePageSections(main: RefObject<HTMLElement | null>, key: string) {
  const [sections, setSections] = useState<PageSection[]>([])
  useEffect(() => {
    const root = main.current
    if (!root) return
    let frame = 0
    const scan = () => {
      cancelAnimationFrame(frame)
      frame = requestAnimationFrame(() => {
        const found = [...root.querySelectorAll<HTMLElement>('section.panel')]
          .map((el) => ({ el, title: el.querySelector('h2')?.textContent ?? '' }))
          .filter((s) => s.title)
        setSections((prev) =>
          prev.length === found.length && prev.every((p, i) => p.el === found[i].el && p.title === found[i].title) ? prev : found,
        )
      })
    }
    scan()
    const observer = new MutationObserver(scan)
    observer.observe(root, { childList: true, subtree: true, characterData: true })
    return () => {
      observer.disconnect()
      cancelAnimationFrame(frame)
    }
  }, [main, key])
  return sections
}

const jump = (el: HTMLElement) =>
  el.scrollIntoView({ behavior: matchMedia('(prefers-reduced-motion: reduce)').matches ? 'auto' : 'smooth', block: 'start' })

interface SubView {
  id: string
  name: string
  mark: ReactNode
}

/** Peer definitions and prediction models, listed under their view in the navigation. */
function useSubViews(): Record<string, SubView[] | undefined> {
  const peers = useApi<PeerOverview>('/peers')
  const prediction = useApi<PredictionOverview>('/prediction')
  return {
    peers: peers.data?.methods.map((m) => ({ id: m.id, name: m.name, mark: <MethodMark methods={peers.data!.methods} id={m.id} /> })),
    prediction: prediction.data?.models.map((m) => ({
      id: m.id,
      name: m.name,
      mark: <i className="swatch circle" style={{ background: MODEL_FAMILY_COLOR[m.family] }} aria-hidden="true" />,
    })),
  }
}

interface SidebarProps {
  route: string[]
  active: string
  sections: PageSection[]
  subViews: Record<string, SubView[] | undefined>
  onAdd: () => void
  theme: Theme
  onTheme: (t: Theme) => void
  /** Set when rendered in the drawer: called before a link or button inside it acts. */
  onClose?: () => void
}

/** The views as a tree (sub-items only under the active view), Add data, then the panels of the current page. */
const THEMES = [
  ['system', 'System', Monitor],
  ['light', 'Light', Sun],
  ['dark', 'Dark', Moon],
] as const

function ThemeSwitch({ theme, onTheme }: { theme: Theme; onTheme: (t: Theme) => void }) {
  return (
    <div className="theme-switch">
      <Segmented label="Theme" value={theme} onChange={onTheme} options={THEMES.map(([value, title, Icon]) => ({ value, title, label: <Icon /> }))} />
    </div>
  )
}

function SidebarContent({ route, active, sections, subViews, onAdd, theme, onTheme, onClose }: SidebarProps) {
  return (
    <div className="side">
      <div className="brand">
        <a href="#/" className="brand-link">
          <span className="brand-mark">
            <BarChart size={16} />
          </span>
          <span className="brand-text">
            <span className="brand-name">DAX Executive Pay</span>
            <span className="brand-meta">Board pay · DAX &amp; MDAX</span>
          </span>
        </a>
        {onClose && (
          <button type="button" className="icon-button" aria-label="Close navigation" onClick={onClose}>
            <X size={18} />
          </button>
        )}
      </div>
      <nav aria-label="Views">
        <ul className="tree">
          {NAV.map(([path, label, Icon]) => {
            const sub = active === path ? subViews[path] : undefined
            const child = path in subViews && route[1]
            return (
              <li key={path}>
                <a href={`#/${path}`} aria-current={active === path && !child ? 'page' : undefined} className={active === path && child ? 'parent' : undefined}>
                  <Icon />
                  {label}
                </a>
                {sub && (
                  <ul>
                    {sub.map((v) => (
                      <li key={v.id}>
                        <a href={`#/${path}/${v.id}`} aria-current={route[0] === path && route[1] === v.id ? 'page' : undefined}>
                          {v.mark}
                          {v.name}
                        </a>
                      </li>
                    ))}
                  </ul>
                )}
              </li>
            )
          })}
        </ul>
      </nav>
      <button
        type="button"
        className="button add-data"
        onClick={() => {
          onClose?.()
          onAdd()
        }}
      >
        <Plus /> Add data
      </button>
      <ThemeSwitch theme={theme} onTheme={onTheme} />
      {sections.length > 1 && (
        <nav aria-label="On this page" className="toc">
          <h2>On this page</h2>
          <ul>
            {sections.map((s, i) => (
              <li key={i}>
                <button
                  type="button"
                  onClick={() => {
                    onClose?.()
                    requestAnimationFrame(() => jump(s.el))
                  }}
                >
                  {s.title}
                </button>
              </li>
            ))}
          </ul>
        </nav>
      )}
    </div>
  )
}

export default function App() {
  const route = useRoute()
  const main = useRef<HTMLElement>(null)
  const drawer = useRef<HTMLDialogElement>(null)
  const [menu, setMenu] = useState(false)
  const [adding, setAdding] = useState(false)
  const key = route.join('/')
  const sections = usePageSections(main, key)
  const subViews = useSubViews()
  const [theme, setTheme] = useTheme()
  useScrollLock(menu)

  const closeMenu = () => drawer.current?.close()
  const active = route[0] === 'people' ? 'executives' : (route[0] ?? '')
  const sidebar = { route, active, sections, subViews, onAdd: () => setAdding(true), theme, onTheme: setTheme }
  const label = NAV.find(([path]) => path === active)?.[1] ?? 'DAX Executive Pay'

  // New page: start at the top and move focus to its heading for keyboard and screen-reader users.
  const previous = useRef(key)
  useEffect(() => {
    if (previous.current === key) return
    previous.current = key
    scrollTo(0, 0)
    main.current?.querySelector<HTMLElement>('h1')?.focus()
    closeMenu()
  }, [key])

  useEffect(() => {
    const wide = matchMedia('(min-width: 1024px)')
    wide.addEventListener('change', closeMenu)
    return () => wide.removeEventListener('change', closeMenu)
  }, [])

  return (
    <ChatProvider page={key}>
      <div className="app">
        <a className="skip" href="#main" onClick={(e) => (e.preventDefault(), main.current?.focus())}>
          Skip to content
        </a>
        <aside className="sidebar">
          <SidebarContent {...sidebar} />
        </aside>
        <header className="appbar">
          <button
            type="button"
            className="icon-button menu-button"
            aria-label="Open navigation"
            aria-expanded={menu}
            onClick={() => (drawer.current?.showModal(), setMenu(true))}
          >
            <Menu size={20} />
          </button>
          <a href="#/" className="brand-link" aria-label="DAX Executive Pay, overview">
            <span className="brand-mark">
              <BarChart size={16} />
            </span>
            <span className="appbar-title">{label}</span>
          </a>
        </header>
        <dialog
          ref={drawer}
          className="drawer"
          aria-label="Navigation"
          onClose={() => setMenu(false)}
          onClick={(e) => (e.target === e.currentTarget || (e.target as Element).closest('a')) && closeMenu()}
        >
          <div className="drawer-body">
            <SidebarContent {...sidebar} onClose={closeMenu} />
          </div>
        </dialog>
        <main id="main" ref={main} tabIndex={-1} key={key}>
          <ErrorBoundary>{page(route)}</ErrorBoundary>
        </main>
        <AssistantPanel hidden={route[0] === 'assistant'} />
        <AddDataSheet open={adding} onClose={() => setAdding(false)} />
      </div>
    </ChatProvider>
  )
}
