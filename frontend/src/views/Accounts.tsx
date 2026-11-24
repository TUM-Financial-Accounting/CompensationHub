import { useState } from 'react'

import { send, useApi, type Account, type PasswordLink } from '../api'
import { Async, PageHead, Panel } from '../ui'

const day = (iso: string) => new Date(iso).toLocaleDateString('en-GB', { dateStyle: 'medium' })

interface Made { name: string; email: string; url: string; expires: string }

/** Admins: everyone who registered, removing accounts, and password links for forgotten
 *  passwords. The app sends no email; the admin passes a link on (copy, or their own mail program). */
export function AccountsView() {
  const [visit, setVisit] = useState(Date.now) // a new query after each change skips useApi's cache
  const state = useApi<Account[]>(`/auth/accounts?visit=${visit}`)
  const [made, setMade] = useState<Made>()
  const [error, setError] = useState<string>()

  const passwordLink = (a: Account) => {
    setError(undefined)
    send<PasswordLink>('POST', `/auth/accounts/${encodeURIComponent(a.email)}/link`).then(
      (r) => setMade({ name: a.name, email: a.email, url: location.origin + r.link, expires: r.expires }),
      (e: Error) => setError(`No link made: ${e.message}`),
    )
  }
  const remove = (a: Account) => {
    if (!confirm(`Remove ${a.name} (${a.email})? They are signed out within a minute, and can register again.`)) return
    setError(undefined)
    send('DELETE', `/auth/accounts/${encodeURIComponent(a.email)}`).then(
      () => setVisit(Date.now()),
      (e: Error) => setError(`Not removed: ${e.message}`),
    )
  }

  return (
    <>
      <PageHead title="Accounts">
        Everyone who registered. Someone who forgot their password gets a password link from you: send it to them yourself, by email or
        chat. Admins are set on the server (ADMIN_EMAILS).
      </PageHead>
      {made && (
        <Panel title="Password link">
          <LinkBox made={made} />
        </Panel>
      )}
      <Async state={state} height={200}>
        {(accounts) => (
          <Panel title="Accounts" caption="A password link keeps the old password working until it is used.">
            {error && (
              <p role="alert" className="error-detail">
                {error}
              </p>
            )}
            <div className="table-wrap">
              <table>
                <thead>
                  <tr>
                    <th>Name</th>
                    <th>Email</th>
                    <th>Status</th>
                    <th>Since</th>
                    <th />
                  </tr>
                </thead>
                <tbody>
                  {accounts.map((a) => (
                    <tr key={a.email}>
                      <td>
                        {a.name} {a.admin && <span className="badge">Admin</span>}
                      </td>
                      <td>{a.email}</td>
                      <td>{a.active ? 'Active' : 'No password yet'}</td>
                      <td>{day(a.created)}</td>
                      <td className="account-actions">
                        <button type="button" className="link" onClick={() => passwordLink(a)}>
                          Password link
                        </button>
                        {!a.admin && (
                          <button type="button" className="link" onClick={() => remove(a)}>
                            Remove
                          </button>
                        )}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </Panel>
        )}
      </Async>
    </>
  )
}

function LinkBox({ made }: { made: Made }) {
  const [copied, setCopied] = useState(false)
  const text = `Hi ${made.name},\n\nhere is a link to choose a new password for the DAX Executive Pay dashboard. It works once, until ${day(made.expires)}:\n\n${made.url}\n`
  const mail = `mailto:${made.email}?subject=${encodeURIComponent('Your DAX Executive Pay password')}&body=${encodeURIComponent(text)}`
  return (
    <div className="link-box" role="status">
      <p>
        For <strong>{made.name}</strong> ({made.email}), works once, until {day(made.expires)}:
      </p>
      <input readOnly value={made.url} onFocus={(e) => e.target.select()} aria-label="Password link" />
      <div className="feedback-actions">
        <button type="button" className="button" onClick={() => navigator.clipboard.writeText(made.url).then(() => setCopied(true))}>
          {copied ? 'Copied' : 'Copy link'}
        </button>
        <a className="button" href={mail}>
          Write email
        </a>
      </div>
    </div>
  )
}
