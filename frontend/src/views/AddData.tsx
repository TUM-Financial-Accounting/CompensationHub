import { useEffect, useRef, useState } from 'react'

import { clearCache, readDataUrl, send, useApi, type DataColumn, type DataTable, type Draft, type Extracted, type Finding, type FirmListItem, type RowFindings } from '../api'
import { MAX_UPLOAD, describe, useChat } from '../chat'
import { X } from '../icons'
import { useScrollLock } from '../lock'
import { Async, Segmented, Skeleton, Table } from '../ui'
import { Answer } from './Assistant'

type Row = Record<string, string>
const empty = (t: DataTable): Row => Object.fromEntries(t.columns.map((c) => [c.name, c.name === 'days' ? '365' : '']))

/** Dialog to append a row to one of the panel's tables; opened from the "Add data" button in the navigation. */
export function AddDataSheet({ open, onClose }: { open: boolean; onClose: () => void }) {
  const dialog = useRef<HTMLDialogElement>(null)
  useScrollLock(open)
  useEffect(() => {
    const el = dialog.current
    if (!el) return
    if (open && !el.open) el.showModal()
    if (!open && el.open) el.close()
  }, [open])
  return (
    <dialog ref={dialog} className="sheet" aria-labelledby="add-data-title" onClose={onClose}>
      {open && <Sheet close={onClose} />}
    </dialog>
  )
}

function Sheet({ close }: { close: () => void }) {
  const tables = useApi<DataTable[]>('/tables')
  const chat = useChat()
  const [mode, setMode] = useState<'form' | 'document'>(chat.draft || chat.busy ? 'document' : 'form')
  return (
    <>
      <div className="sheet-head">
        <h2 id="add-data-title">Add data</h2>
        <button type="button" className="icon-button" aria-label="Close" onClick={close}>
          <X size={18} />
        </button>
      </div>
      <div className="sheet-body">
        <div className="controls">
          <Segmented
            label="How"
            value={mode}
            onChange={setMode}
            options={[
              { value: 'form', label: 'By hand' },
              { value: 'document', label: 'From a document (AI)' },
            ]}
          />
        </div>
        {mode === 'form' ? (
          <Async state={tables} skeleton={<Skeleton height={400} />}>
            {(all) => <Editor tables={all} reload={tables.reload} />}
          </Async>
        ) : (
          <FromDocument />
        )}
      </div>
    </>
  )
}

function Editor({ tables, reload }: { tables: DataTable[]; reload: () => void }) {
  const [id, setId] = useState(tables[0].id)
  const table = tables.find((t) => t.id === id) ?? tables[0]
  const [row, setRow] = useState<Row>(() => empty(table))
  const [status, setStatus] = useState<{ ok: boolean; text: string }>()
  const [saving, setSaving] = useState(false)
  const firms = useApi<FirmListItem[]>('/firms')
  const check = useCheck(table.id === 'execs' ? row : null)

  const pick = (next: string) => {
    setId(next)
    setRow(empty(tables.find((t) => t.id === next)!))
    setStatus(undefined)
  }

  async function save() {
    setSaving(true)
    setStatus(undefined)
    try {
      await send('POST', '/rows', { changes: [{ table: table.id, rows: [row] }] })
      clearCache()
      setRow(empty(table))
      setStatus({ ok: true, text: 'Saved and checked by a full rebuild. Peer groups and forecasts are recalculated in the background (about two minutes).' })
      reload()
    } catch (e) {
      setStatus({ ok: false, text: (e as Error).message })
    } finally {
      setSaving(false)
    }
  }

  async function remove(index: number) {
    if (!confirm('Delete this row? The panel is rebuilt without it.')) return
    try {
      await send<DataTable>('DELETE', `/tables/${encodeURIComponent(table.id)}/rows/${index}`)
      clearCache()
      reload()
    } catch (e) {
      setStatus({ ok: false, text: (e as Error).message })
    }
  }

  const missing = table.columns.filter((c) => c.required && !row[c.name]?.trim())
  return (
    <>
      <div className="controls">
        <label className="field">
          <span>Table</span>
          <select value={table.id} onChange={(e) => pick(e.target.value)}>
            {tables.map((t) => (
              <option key={t.id} value={t.id}>
                {t.name}
              </option>
            ))}
          </select>
        </label>
      </div>
      <p>{table.purpose}</p>
      <details>
        <summary className="caption">
          File structure: <code>{table.file}</code>
        </summary>
        <pre className="header-line">{table.columns.map((c) => c.name).join(',')}</pre>
      </details>

      <form
        className="form-grid"
        onSubmit={(e) => {
          e.preventDefault()
          save()
        }}
      >
        {table.columns.map((c) => (
          <Field key={c.name} c={c} value={row[c.name] ?? ''} onChange={(v) => setRow({ ...row, [c.name]: v })} firms={firms.data} />
        ))}
        <div className="form-actions wide">
          <button type="submit" className="button primary" disabled={saving || missing.length > 0}>
            {saving ? 'Saving and rebuilding…' : 'Save row'}
          </button>
          {missing.length > 0 && <span className="caption">Still required: {missing.map((c) => c.label).join(', ')}</span>}
          {status && (
            <span className={`status ${status.ok ? 'ok' : 'bad'}`} role={status.ok ? 'status' : 'alert'}>
              {status.text}
            </span>
          )}
        </div>
      </form>

      {check && check.length > 0 && (
        <section className="subchart" aria-live="polite">
          <h3>Check before saving</h3>
          <ul className="findings">
            {check.map((f, i) => (
              <li key={i} className={f.level}>
                <span className="level">{f.level}</span>
                <span>{f.message}</span>
              </li>
            ))}
          </ul>
        </section>
      )}

      {table.rows.length > 0 && (
        <section className="subchart">
          <h3>
            {table.deletable ? 'Rows added by hand' : 'Last rows in the file'} ({table.rows.length})
          </h3>
          <Table
            caption={`Rows of ${table.name}`}
            rows={table.rows.map((r, i) => ({ ...r, __i: String(i) })).slice(table.deletable ? 0 : -8)}
            rowKey={(r) => r.__i}
            sort={{ key: '__i', desc: true }}
            columns={[
              ...table.columns.slice(0, 6).map((c) => ({ key: c.name, label: c.label, value: (r: Row) => r[c.name] })),
              ...(table.deletable
                ? [
                    {
                      key: '__i',
                      label: '',
                      value: (r: Row) => Number(r.__i),
                      render: (r: Row) => (
                        <button type="button" className="link" onClick={() => remove(Number(r.__i))}>
                          Delete
                        </button>
                      ),
                    },
                  ]
                : []),
            ]}
          />
        </section>
      )}
    </>
  )
}


/** The assistant reads an attached report or pasted figures and drafts the rows; they are checked, edited and
 *  saved here. Shares the conversation with the Assistant page. */
function FromDocument() {
  const chat = useChat()
  const [text, setText] = useState('')
  const [attachment, setAttachment] = useState<Extracted>()
  const [reading, setReading] = useState<string>()
  const model = chat.setup?.models.find((m) => m.id === chat.model)
  const last = chat.turns[chat.turns.length - 1]

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

  if (!chat.setup) return <Skeleton height={240} />
  return (
    <>
      <p>
        Attach a remuneration report (PDF or text) or paste the figures. The assistant ({chat.model || 'no model'}) drafts the rows; nothing is saved before you
        click Save.
      </p>
      {!model?.available && <p className="callout">No assistant model is available: add a provider key to backend/.env and restart the backend.</p>}
      <form
        className="form-grid"
        onSubmit={(e) => {
          e.preventDefault()
          chat.ask(text, attachment)
          setText('')
          setAttachment(undefined)
        }}
      >
        <label className="field wide">
          <span>Document</span>
          <input
            type="file"
            accept=".pdf,.txt,.md,.csv"
            disabled={chat.busy}
            onChange={(e) => {
              const f = e.target.files?.[0]
              e.target.value = ''
              if (f) attach(f)
            }}
          />
          {(attachment || reading) && <span className="help">{attachment ? describe(attachment) : reading}</span>}
        </label>
        <label className="field wide">
          <span>{chat.draft ? 'Change the draft' : 'What to add'}</span>
          <textarea rows={3} value={text} onChange={(e) => setText(e.target.value)} placeholder={chat.draft ? 'e.g. row 2 is the CFO' : 'e.g. the board members of 2025, or paste the figures here'} />
        </label>
        <div className="form-actions wide">
          {chat.busy ? (
            <button type="button" className="button" onClick={chat.stop}>
              Stop
            </button>
          ) : (
            <button type="submit" className="button primary" disabled={!model?.available || (!text.trim() && !attachment)}>
              {chat.draft ? 'Ask the assistant' : 'Draft the rows'}
            </button>
          )}
        </div>
      </form>
      {last?.role === 'assistant' && <Answer t={last} />}
      {chat.draft && <DraftEditor draft={chat.draft} />}
      {chat.notice && (
        <p className="status ok" role="status">
          {chat.notice}
        </p>
      )}
    </>
  )
}

/** The rows the assistant proposed, editable; checked again after each edit, saved on click. */
function DraftEditor({ draft }: { draft: Draft }) {
  const chat = useChat()
  const tables = useApi<DataTable[]>('/tables').data
  const [checks, setChecks] = useState<{ key: string; value: RowFindings[] }>()
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState<string>()
  const key = JSON.stringify(draft.changes)

  useEffect(() => {
    const timer = setTimeout(() => {
      send<RowFindings[]>('POST', '/rows/check', { changes: draft.changes }).then(
        (value) => setChecks({ key, value }),
        () => undefined,
      )
    }, 600)
    return () => clearTimeout(timer)
  }, [key, draft.changes])

  const findings = checks?.key === key ? checks.value : draft.checks
  const edit = (ti: number, ri: number, column: string | null, value?: string) =>
    chat.setDraft({
      ...draft,
      changes: draft.changes.map((c, i) =>
        i !== ti ? c : { ...c, rows: column === null ? c.rows.filter((_, j) => j !== ri) : c.rows.map((r, j) => (j === ri ? { ...r, [column]: value ?? '' } : r)) },
      ),
    })

  async function save() {
    setSaving(true)
    setError(undefined)
    try {
      const { added } = await send<{ added: number }>('POST', '/rows', { changes: draft.changes })
      clearCache()
      chat.setDraft(null)
      chat.setNotice(`Saved ${added} row${added === 1 ? '' : 's'}; the panel was rebuilt. Peer groups and forecasts update in the background (about three minutes).`)
    } catch (e) {
      setError((e as Error).message)
    } finally {
      setSaving(false)
    }
  }

  const blocking = findings.some((f) => f.findings.some((x) => x.level === 'error'))
  return (
    <section className="draft" aria-label="Draft rows">
      <h3>Draft — not saved yet</h3>
      {draft.changes.map((c, ti) => {
        const table = tables?.find((t) => t.id === c.table)
        const used = new Set(c.rows.flatMap((r) => Object.keys(r).filter((k) => r[k] !== '')))
        const columns = (table?.columns.filter((col) => col.required || used.has(col.name)).map((col) => ({ name: col.name, label: col.label + (col.unit ? ` (${col.unit})` : '') })) ?? [
          ...used,
        ].map((name) => ({ name, label: name })))
        return (
          <div key={ti} className="subchart">
            <span className="seg-label">{table?.name ?? c.table}</span>
            <div className="table-wrap">
              <table>
                <thead>
                  <tr>
                    <th>Field</th>
                    {c.rows.map((_, ri) => (
                      <th key={ri}>
                        Row {ri + 1}{' '}
                        <button type="button" className="link" onClick={() => edit(ti, ri, null)}>
                          remove
                        </button>
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {columns.map((col) => (
                    <tr key={col.name}>
                      <th scope="row">{col.label}</th>
                      {c.rows.map((r, ri) => (
                        <td key={ri}>
                          <input type="text" aria-label={`${col.label}, row ${ri + 1}`} value={r[col.name] ?? ''} onChange={(e) => edit(ti, ri, col.name, e.target.value)} />
                        </td>
                      ))}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <ul className="findings">
              {findings
                .filter((f) => f.table === c.table)
                .flatMap((f) =>
                  f.findings.map((x, k) => (
                    <li key={`${f.row}-${k}`} className={x.level}>
                      <span className="level">{x.level}</span>
                      <span>
                        Row {f.row + 1}: {x.message}
                      </span>
                    </li>
                  )),
                )}
            </ul>
          </div>
        )
      })}
      <div className="form-actions">
        <button type="button" className="button primary" onClick={save} disabled={saving || blocking || !draft.changes.some((c) => c.rows.length)}>
          {saving ? 'Saving and rebuilding…' : 'Save to the data'}
        </button>
        <button type="button" className="button" onClick={() => chat.setDraft(null)} disabled={saving}>
          Discard
        </button>
        <span className="caption">Edit cells here, or ask the assistant to change the draft.</span>
        {error && (
          <span className="status bad" role="alert">
            {error}
          </span>
        )}
      </div>
    </section>
  )
}

function Field({ c, value, onChange, firms }: { c: DataColumn; value: string; onChange: (v: string) => void; firms?: FirmListItem[] }) {
  const id = `field-${c.name}`
  const label = (
    <span>
      {c.label}
      {c.unit && <span className="unit"> ({c.unit})</span>}
      {c.required && (
        <span className="req" aria-hidden="true">
          {' '}
          *
        </span>
      )}
    </span>
  )
  if (c.kind === 'bool')
    return (
      <label className="field check-row">
        <input type="checkbox" checked={value === 'yes'} onChange={(e) => onChange(e.target.checked ? 'yes' : 'no')} />
        {c.label}
      </label>
    )
  return (
    <label className={`field${c.name === 'source' || c.name === 'note' ? ' wide' : ''}`} htmlFor={id}>
      {label}
      {c.kind === 'choice' ? (
        <select id={id} value={value} required={c.required} onChange={(e) => onChange(e.target.value)}>
          <option value="">{c.required ? 'Choose…' : '–'}</option>
          {c.options.map((o) => (
            <option key={o}>{o}</option>
          ))}
        </select>
      ) : (
        <input
          id={id}
          type={c.kind === 'number' || c.kind === 'integer' ? 'number' : 'text'}
          step={c.kind === 'integer' ? 1 : 'any'}
          value={value}
          required={c.required}
          list={c.kind === 'firm' ? 'firm-names' : undefined}
          onChange={(e) => onChange(e.target.value)}
        />
      )}
      {c.kind === 'firm' && (
        <datalist id="firm-names">
          {firms?.map((f) => (
            <option key={f.id} value={f.name} />
          ))}
        </datalist>
      )}
      {c.help && <span className="help">{c.help}</span>}
    </label>
  )
}

/** The backend's plausibility check, re-run 600 ms after the last edit once the row can be placed. */
function useCheck(row: Row | null): Finding[] | undefined {
  const [result, setResult] = useState<{ key: string; check: Finding[] }>()
  const key = row && row.firm && row.year && row.last_name && row.role ? JSON.stringify(row) : null
  useEffect(() => {
    if (!key) return
    let live = true
    const timer = setTimeout(() => {
      send<RowFindings[]>('POST', '/rows/check', { changes: [{ table: 'execs', rows: [JSON.parse(key)] }] }).then(
        (r) => live && setResult({ key, check: r[0].findings }),
        () => undefined,
      )
    }, 600)
    return () => {
      live = false
      clearTimeout(timer)
    }
  }, [key])
  return result && result.key === key ? result.check : undefined
}
