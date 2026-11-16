import * as Plot from '@observablehq/plot'
import { Fragment, useEffect, useLayoutEffect, useRef, useState, useSyncExternalStore, type ReactNode } from 'react'

import { readDataUrl, send, type ChartSpec, type Extracted } from '../api'
import { base } from '../charts'
import { MAX_UPLOAD, describe, useChat, type AssistantTurn, type Step } from '../chat'
import { ArrowUp, Check, ChevronRight, Maximize2, MessageSquare, Paperclip, Square, X } from '../icons'
import { useScrollLock } from '../lock'
import { Chart, PageHead, Segmented, Skeleton } from '../ui'
import './Assistant.css'

const THINKING_LABEL: Record<string, string> = { off: 'Off', on: 'On', low: 'Low', medium: 'Medium', xhigh: 'Extra high' }
const SERIES = ['var(--c-ceo)', 'var(--c-cfo)', 'var(--c-lti)', 'var(--c-sti)', 'var(--c-mti)', 'var(--c-member)']

const phone = matchMedia('(max-width: 639px)')
const watchPhone = (notify: () => void) => {
  phone.addEventListener('change', notify)
  return () => phone.removeEventListener('change', notify)
}
const usePhone = () => useSyncExternalStore(watchPhone, () => phone.matches)

export function AssistantView() {
  return (
    <>
      <PageHead title="Assistant">
        Ask about pay, peers, forecasts or new data in plain language, or attach a remuneration report to add its numbers. The assistant
        answers by calling the dashboard's own functions and shows every call; numbers it cannot find in those results are marked. It
        is also open on every page from the button at the bottom right.
      </PageHead>
      <ChatBody />
    </>
  )
}

/** The assistant beside every page: same conversation as the Assistant page. */
export function AssistantPanel({ hidden }: { hidden: boolean }) {
  const [open, setOpen] = useState(false)
  const onPhone = usePhone()
  const fab = useRef<HTMLButtonElement>(null)
  const panel = useRef<HTMLElement>(null)
  const restoreFocus = useRef(false)

  if (hidden && open) setOpen(false)
  useScrollLock(open && onPhone)

  // The button steps aside while the reader scrolls down, so it never sits on the content being read.
  const [tucked, setTucked] = useState(false)
  useEffect(() => {
    if (open || hidden) return
    let last = scrollY
    const onScroll = () => {
      if (Math.abs(scrollY - last) < 8) return
      setTucked(scrollY > last && scrollY > 80)
      last = scrollY
    }
    addEventListener('scroll', onScroll, { passive: true })
    return () => removeEventListener('scroll', onScroll)
  }, [open, hidden])

  const close = () => {
    restoreFocus.current = true
    setOpen(false)
  }

  useEffect(() => {
    if (open) panel.current?.focus()
    else if (restoreFocus.current) {
      restoreFocus.current = false
      fab.current?.focus()
    }
  }, [open])

  // The phone panel is full screen: size it to what the iOS keyboard leaves visible
  // (100dvh does not shrink for the keyboard).
  useEffect(() => {
    const vv = window.visualViewport
    if (!open || !onPhone || !vv) return
    const fit = () => {
      panel.current?.style.setProperty('--vvh', `${vv.height}px`)
      panel.current?.style.setProperty('--vvt', `${vv.offsetTop}px`)
    }
    fit()
    vv.addEventListener('resize', fit)
    vv.addEventListener('scroll', fit)
    return () => {
      vv.removeEventListener('resize', fit)
      vv.removeEventListener('scroll', fit)
    }
  }, [open, onPhone])

  if (hidden) return null
  if (!open)
    return (
      <button ref={fab} type="button" className={`ask-fab${tucked ? ' tucked' : ''}`} onClick={() => setOpen(true)} aria-label="Ask the assistant">
        <MessageSquare size={20} />
        <span>Ask the assistant</span>
      </button>
    )
  return (
    <aside ref={panel} className="chat-panel" aria-label="Assistant" tabIndex={-1} onKeyDown={(e) => e.key === 'Escape' && close()}>
      <header className="chat-panel-head">
        <h2>Assistant</h2>
        <a className="icon-button" href="#/assistant" aria-label="Open full page" title="Open full page">
          <Maximize2 size={18} />
        </a>
        <button type="button" className="icon-button" onClick={close} aria-label="Close" title="Close">
          <X size={18} />
        </button>
      </header>
      <ChatBody inPanel />
    </aside>
  )
}

function ChatBody({ inPanel = false }: { inPanel?: boolean }) {
  const chat = useChat()
  const root = useRef<HTMLDivElement>(null)
  const scroller = useRef<HTMLDivElement>(null)
  const ready = !!chat.setup
  // Follow the streamed answer only while the reader is at the bottom; a new question always follows.
  const follow = useRef(true)
  const asked = useRef(chat.turns.length)
  useEffect(() => {
    if (!ready) return
    const target = inPanel ? scroller.current : window
    const onScroll = () => {
      const el = inPanel ? scroller.current : document.documentElement
      if (el) follow.current = el.scrollHeight - el.scrollTop - el.clientHeight < 120
    }
    target?.addEventListener('scroll', onScroll, { passive: true })
    return () => target?.removeEventListener('scroll', onScroll)
  }, [inPanel, ready])
  useEffect(() => {
    if (chat.turns.length > asked.current) follow.current = true
    asked.current = chat.turns.length
    if (!chat.turns.length || !follow.current) return
    if (inPanel) scroller.current?.scrollTo({ top: scroller.current.scrollHeight })
    else root.current?.scrollIntoView({ block: 'end' })
  }, [chat.turns, chat.draft, inPanel])
  if (!chat.setup) return <Skeleton height={240} />
  const current = chat.setup.models.find((m) => m.id === chat.model)
  return (
    <div ref={root} className={`chat${inPanel ? ' in-panel' : ''}`}>
      <div ref={scroller} className="chat-scroll">
        <div className="controls chat-settings">
          <label className="field model">
            <span>Model</span>
            <select value={chat.model} onChange={(e) => chat.setModel(e.target.value)}>
              {chat.setup.models.map((m) => (
                <option key={m.id} value={m.id} disabled={!m.available}>
                  {m.id}
                  {m.available ? '' : ' — no key in backend/.env'}
                </option>
              ))}
            </select>
          </label>
          {current && current.thinking.length > 0 && (
            <Segmented label="Thinking" value={chat.thinking} onChange={chat.setThinking} options={current.thinking.map((t) => ({ value: t, label: THINKING_LABEL[t] ?? t }))} />
          )}
          {chat.turns.length > 0 && (
            <button type="button" className="button" onClick={chat.reset} disabled={chat.busy}>
              New conversation
            </button>
          )}
        </div>
        {current && !current.available && <p className="callout">Add the key for this provider to backend/.env and restart the backend.</p>}
        {chat.thinking !== 'off' && (
          <p className="caption">
            The model reasons step by step before it answers{chat.thinking === 'on' ? '' : `, with ${THINKING_LABEL[chat.thinking].toLowerCase()} effort`}: slower,
            sometimes better at multi-step questions. Its reasoning appears above each answer.
          </p>
        )}

        {chat.turns.length === 0 ? (
          <div className="examples" aria-label="Example questions">
            {chat.setup.examples.slice(0, inPanel ? 4 : undefined).map((q) => (
              <button key={q} type="button" onClick={() => chat.ask(q)}>
                {q}
              </button>
            ))}
          </div>
        ) : (
          <div className="chat-log" aria-live="polite">
            {chat.turns.map((t, i) =>
              t.role === 'user' ? (
                <div key={i} className="msg user">
                  {t.text}
                  {t.attachment && <span className="tag attachment">{describe(t.attachment)}</span>}
                </div>
              ) : (
                <Answer key={i} t={t} />
              ),
            )}
          </div>
        )}
        {chat.draft && (
          <p className="callout">
            A draft of rows is waiting.{' '}
            <button type="button" className="link" onClick={chat.openAdd}>
              Review and save it in Add data
            </button>
          </p>
        )}
        {chat.notice && (
          <p className="status ok" role="status">
            {chat.notice}
          </p>
        )}
      </div>
      <Composer disabled={!current?.available} />
    </div>
  )
}


function Composer({ disabled }: { disabled: boolean }) {
  const chat = useChat()
  const [text, setText] = useState('')
  const [attachment, setAttachment] = useState<Extracted>()
  const [reading, setReading] = useState<string>()
  const file = useRef<HTMLInputElement>(null)
  const area = useRef<HTMLTextAreaElement>(null)

  useLayoutEffect(() => {
    const el = area.current!
    el.style.height = 'auto'
    el.style.height = `${el.scrollHeight}px`
  }, [text])

  async function attach(f: File) {
    if (f.size > MAX_UPLOAD) return setReading(`${f.name} is larger than 15 MB.`)
    setReading(`Reading ${f.name}…`)
    try {
      const data = (await readDataUrl(f)).split(',')[1] ?? ''
      setAttachment(await send<Extracted>('POST', '/extract', { name: f.name, data }))
      setReading(undefined)
    } catch (e) {
      setReading((e as Error).message)
    }
  }

  const empty = !text.trim() && !attachment
  const submit = () => {
    if (chat.busy || disabled || empty) return
    chat.ask(text, attachment)
    setText('')
    setAttachment(undefined)
  }
  return (
    <form
      className="composer-dock"
      onSubmit={(e) => {
        e.preventDefault()
        submit()
      }}
    >
      <div className="composer">
        {(attachment || reading) && (
          <div className="attached">
            {attachment && (
              <span className="tag attachment">
                <span className="name">{describe(attachment)}</span>
                <button type="button" className="tag-remove" onClick={() => setAttachment(undefined)} aria-label="Remove attachment">
                  <X size={14} />
                </button>
              </span>
            )}
            {reading && <span className="caption">{reading}</span>}
          </div>
        )}
        <input
          ref={file}
          type="file"
          accept=".pdf,.txt,.md,.csv"
          hidden
          onChange={(e) => {
            const f = e.target.files?.[0]
            e.target.value = ''
            if (f) attach(f)
          }}
        />
        <button type="button" className="icon-button" onClick={() => file.current?.click()} disabled={chat.busy} aria-label="Attach a PDF or text file" title="Attach a PDF or text file">
          <Paperclip size={18} />
        </button>
        <textarea
          ref={area}
          aria-label="Your question"
          rows={1}
          value={text}
          placeholder="Ask a question…"
          onChange={(e) => setText(e.target.value)}
          onKeyDown={(e) => {
            // Phones have no Shift key: there Enter is a newline and the arrow button sends.
            if (e.key === 'Enter' && !e.shiftKey && !e.nativeEvent.isComposing && !matchMedia('(pointer: coarse)').matches) {
              e.preventDefault()
              submit()
            }
          }}
        />
        {chat.busy ? (
          <button type="button" className="composer-send stop" onClick={chat.stop} aria-label="Stop">
            <Square size={16} />
          </button>
        ) : (
          <button type="submit" className="composer-send" disabled={disabled || empty} aria-label="Send">
            <ArrowUp size={18} />
          </button>
        )}
      </div>
    </form>
  )
}

const arg = (s: Step, key: string) => String(s.args[key] ?? '')

const stepLabel = (s: Step) => {
  switch (s.name) {
    case 'find':
      return `Looked up “${arg(s, 'query')}”`
    case 'sql':
      return 'Queried the panel'
    case 'api':
      return `Read ${arg(s, 'path')}`
    case 'check_row':
      return 'Checked the new row'
    case 'propose_rows':
      return 'Drafted rows to add'
    case 'chart':
      return `Drew “${arg(s, 'title')}”`
    case 'docs':
      return `Searched the docs for “${arg(s, 'query')}”`
    default:
      return s.name
  }
}

export function Answer({ t }: { t: AssistantTurn }) {
  const last = t.steps[t.steps.length - 1]
  const waiting = !t.done && (!last || last.preview !== undefined)
  const n = t.steps.length
  return (
    <div className="msg assistant">
      {t.thinking && (
        <details className="trace">
          <summary>
            Reasoning
            <ChevronRight size={14} className="chev" />
          </summary>
          <pre>{t.thinking}</pre>
        </details>
      )}
      {n > 0 && (
        <details className="trace" open={!t.done}>
          <summary>
            {t.done ? 'Used' : 'Using'} {n} tool{n > 1 ? 's' : ''}
            <ChevronRight size={14} className="chev" />
          </summary>
          <ol className="steps">
            {t.steps.map((s, i) => (
              <li key={i}>
                <details className="step">
                  <summary>
                    <span className="step-icon">
                      {s.preview !== undefined ? <Check size={14} /> : !t.done && i === n - 1 && <i className="spinner" />}
                    </span>
                    <span className="step-label">{stepLabel(s)}</span>
                    <ChevronRight size={14} className="chev" />
                  </summary>
                  <pre>{`${s.name}(${JSON.stringify(s.args)})`}</pre>
                  {s.preview !== undefined && <pre>{s.preview}</pre>}
                </details>
              </li>
            ))}
          </ol>
        </details>
      )}
      {waiting && (
        <span className="working">
          <i className="spinner" />
          Waiting for the model…
        </span>
      )}
      {t.text && <div className="text">{markdown(t.text, new Set(t.unverified))}</div>}
      {t.charts.map((c, i) => (
        <AnswerChart key={i} c={c} />
      ))}
      {t.drafted && <p className="caption">Drafted rows are in Add data: check and edit them there, then save. Nothing is added before you click Save.</p>}
      {t.unverified && t.unverified.length > 0 && <p className="caption">Marked numbers were not found in any tool result: check them before using them.</p>}
      {t.error && <p className="callout">{t.error}</p>}
    </div>
  )
}

function AnswerChart({ c }: { c: ChartSpec }) {
  const years = c.x === 'year'
  const series = c.color ? [...new Set(c.rows.map((r) => String(r[c.color!])))] : []
  const fill = c.color ?? 'var(--accent)'
  return (
    <figure className="answer-chart">
      <figcaption>{c.title}</figcaption>
      <Chart
        label={`${c.title}: ${c.y} by ${c.x}${c.color ? ` and ${c.color}` : ''}, ${c.rows.length} points.`}
        render={(width) =>
          Plot.plot({
            ...base(width, 240),
            marginLeft: 60,
            x: years ? { label: null, tickFormat: 'd' } : { label: null, tickRotate: c.kind === 'bar' && c.rows.length > 6 ? -30 : 0 },
            y: { label: c.y, grid: true },
            color: c.color ? { domain: series, range: SERIES, legend: true } : undefined,
            marks: [
              c.kind === 'line' ? Plot.line(c.rows, { x: c.x, y: c.y, stroke: fill, strokeWidth: 2 }) : null,
              c.kind === 'bar' ? Plot.barY(c.rows, { x: c.x, y: c.y, fill, tip: true }) : null,
              c.kind !== 'bar' ? Plot.dot(c.rows, { x: c.x, y: c.y, fill, r: 3, tip: true }) : null,
              Plot.ruleY([0]),
            ],
          })
        }
      />
    </figure>
  )
}

/** Paragraphs, bullet lists, tables and **bold** — enough for the answers, without a Markdown
 *  library. Numbers the backend could not verify are wrapped in <mark>. */
function markdown(text: string, unverified: Set<string>): ReactNode {
  const blocks = text.split(/\n{2,}/)
  return blocks.map((block, i) => {
    const lines = block.split('\n')
    if (lines.length > 1 && lines.every((l) => l.trim().startsWith('|'))) {
      const cells = lines.filter((l) => !/^\s*\|[\s:|-]+\|\s*$/.test(l)).map((l) => l.trim().replace(/^\||\|$/g, '').split('|'))
      return (
        <div key={i} className="table-wrap">
          <table>
            <thead>
              <tr>
                {cells[0].map((c, j) => (
                  <th key={j}>{inline(c.trim(), unverified)}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {cells.slice(1).map((r, k) => (
                <tr key={k}>
                  {r.map((c, j) => (
                    <td key={j}>{inline(c.trim(), unverified)}</td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )
    }
    if (lines.every((l) => /^\s*([-*•]|\d+\.)\s/.test(l)))
      return (
        <ul key={i}>
          {lines.map((l, j) => (
            <li key={j}>{inline(l.replace(/^\s*([-*•]|\d+\.)\s/, ''), unverified)}</li>
          ))}
        </ul>
      )
    return (
      <p key={i}>
        {lines.map((l, j) => (
          <Fragment key={j}>
            {j > 0 && <br />}
            {inline(l.replace(/^#+\s*/, ''), unverified)}
          </Fragment>
        ))}
      </p>
    )
  })
}

function inline(text: string, unverified: Set<string>): ReactNode[] {
  return text.split(/(\*\*[^*]+\*\*)/).map((part, i) =>
    part.startsWith('**') && part.endsWith('**') ? <strong key={i}>{marks(part.slice(2, -2), unverified)}</strong> : <Fragment key={i}>{marks(part, unverified)}</Fragment>,
  )
}

function marks(text: string, unverified: Set<string>): ReactNode[] {
  if (!unverified.size) return [text]
  return text.split(/([-+−]?\d(?:[\d.,]*\d)?)/).map((part, i) =>
    unverified.has(part) ? (
      <mark key={i} title="Not found in the tool results">
        {part}
      </mark>
    ) : (
      part
    ),
  )
}
