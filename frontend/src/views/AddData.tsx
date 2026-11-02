import { useEffect, useRef, useState } from 'react'

import { clearCache, send, useApi, type DataColumn, type DataTable, type Finding, type FirmListItem, type RowFindings } from '../api'
import { X } from '../icons'
import { useScrollLock } from '../lock'
import { Async, Skeleton, Table } from '../ui'

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
  return (
    <>
      <div className="sheet-head">
        <h2 id="add-data-title">Add data</h2>
        <button type="button" className="icon-button" aria-label="Close" onClick={close}>
          <X size={18} />
        </button>
      </div>
      <div className="sheet-body">
        <Async state={tables} skeleton={<Skeleton height={400} />}>
          {(all) => <Editor tables={all} reload={tables.reload} />}
        </Async>
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
