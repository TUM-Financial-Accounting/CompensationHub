import { useState, type FormEvent } from 'react'

import { send } from '../api'
import { BarChart } from '../icons'

/** The email inside a password link's token, to show whose password is chosen (the server checks the link). */
function linked(link: string): string | undefined {
  try {
    return JSON.parse(atob(link.split('.')[0].replace(/-/g, '+').replace(/_/g, '/'))).email
  } catch {
    return undefined
  }
}

type Mode = 'signin' | 'register' | 'link'

const HEAD: Record<Mode, string> = {
  signin: 'Sign in to open the dashboard.',
  register: 'Create your account.',
  link: 'Choose your new password.',
}
const SUBMIT: Record<Mode, string> = { signin: 'Sign in', register: 'Register', link: 'Save password and sign in' }

/** Sign in or register with email and password; with ?invite=… (a password link from an admin)
 *  choose a new password. `problem` is set when the server did not answer. */
export function SignIn({ problem }: { problem?: string }) {
  const [link] = useState(() => new URLSearchParams(location.search).get('invite'))
  const [mode, setMode] = useState<Mode>(link ? 'link' : 'signin')
  const [email, setEmail] = useState(() => (link && linked(link)) || '')
  const [name, setName] = useState('')
  const [password, setPassword] = useState('')
  const [repeat, setRepeat] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string>()
  const fresh = mode !== 'signin' // a new password: at least 8 characters, typed twice

  const submit = async (e: FormEvent) => {
    e.preventDefault()
    if (fresh && password !== repeat) return setError('The two passwords differ.')
    setBusy(true)
    setError(undefined)
    try {
      if (mode === 'link') await send('POST', '/auth/password', { link, password })
      else if (mode === 'register') await send('POST', '/auth/register', { email, name, password })
      else await send('POST', '/auth/signin', { email, password })
      history.replaceState(null, '', '/' + location.hash) // drop ?invite=…
      location.reload()
    } catch (err) {
      setError((err as Error).message)
      setBusy(false)
    }
  }
  const switchTo = (m: Mode) => {
    setMode(m)
    setError(undefined)
    setRepeat('')
  }

  return (
    <main className="signin">
      <div className="signin-card">
        <span className="brand-mark" aria-hidden="true">
          <BarChart size={20} />
        </span>
        <div className="signin-head">
          <h1>DAX Executive Pay</h1>
          <p>{problem ? 'The server did not answer.' : HEAD[mode]}</p>
        </div>
        {problem ? (
          <>
            <p role="alert" className="callout">
              {problem}
            </p>
            <button type="button" className="button signin-button" onClick={() => location.reload()}>
              Try again
            </button>
          </>
        ) : (
          <form className="signin-form" onSubmit={submit} key={mode}>
            {mode === 'register' && (
              <label className="field">
                <span>Name, shown on feedback</span>
                <input autoComplete="name" required maxLength={100} autoFocus value={name} onChange={(e) => setName(e.target.value)} />
              </label>
            )}
            {(mode !== 'link' || email) && (
              <label className="field">
                <span>Email</span>
                <input
                  type="email"
                  autoComplete="username"
                  required
                  readOnly={mode === 'link'}
                  autoFocus={mode === 'signin'}
                  value={email}
                  onChange={(e) => setEmail(e.target.value)}
                />
              </label>
            )}
            <label className="field">
              <span>{fresh ? 'Password, at least 8 characters' : 'Password'}</span>
              <input
                type="password"
                autoComplete={fresh ? 'new-password' : 'current-password'}
                required
                minLength={fresh ? 8 : undefined}
                autoFocus={mode === 'link'}
                value={password}
                onChange={(e) => setPassword(e.target.value)}
              />
            </label>
            {fresh && (
              <label className="field">
                <span>Repeat password</span>
                <input type="password" autoComplete="new-password" required value={repeat} onChange={(e) => setRepeat(e.target.value)} />
              </label>
            )}
            {mode === 'link' && !email && (
              <p role="alert" className="callout">
                This link looks cut off: copy the whole link, from https:// to its last character.
              </p>
            )}
            {error && (
              <p role="alert" className="callout">
                {error}
              </p>
            )}
            <button type="submit" className="button primary signin-button" disabled={busy}>
              {busy ? 'One moment…' : SUBMIT[mode]}
            </button>
          </form>
        )}
        {!problem && mode !== 'link' && (
          <p className="signin-switch">
            {mode === 'signin' ? 'No account yet? ' : 'Have an account? '}
            <button type="button" className="link" onClick={() => switchTo(mode === 'signin' ? 'register' : 'signin')}>
              {mode === 'signin' ? 'Register' : 'Sign in'}
            </button>
          </p>
        )}
        <div className="signin-note">
          <p>{mode === 'link' ? 'The link works once.' : 'Forgot your password? Ask an admin for a password link.'}</p>
          <p>Board pay of DAX and MDAX firms, for the Chair of Financial Accounting, TUM.</p>
        </div>
      </div>
    </main>
  )
}
