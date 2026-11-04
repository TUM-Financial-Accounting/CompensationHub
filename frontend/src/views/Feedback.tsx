import { useState, type FormEvent } from 'react'

import { send, useApi, type FeedbackPost } from '../api'
import { Async, PageHead, Panel } from '../ui'

const when = (iso: string) => new Date(iso).toLocaleString('en-GB', { dateStyle: 'medium', timeStyle: 'short' })

export function FeedbackView() {
  // A new query per visit skips useApi's session cache, so posts by others show up.
  const [visit] = useState(Date.now)
  const state = useApi<FeedbackPost[]>(`/feedback?visit=${visit}`)
  const [mine, setMine] = useState<FeedbackPost[]>([])
  const [author, setAuthor] = useState('')
  const [body, setBody] = useState('')
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState<string>()

  const submit = async (e: FormEvent) => {
    e.preventDefault()
    setSaving(true)
    setError(undefined)
    try {
      const post = await send<FeedbackPost>('POST', '/feedback', { author, body })
      setMine((m) => [post, ...m])
      setBody('')
    } catch (err) {
      setError((err as Error).message)
    } finally {
      setSaving(false)
    }
  }

  return (
    <>
      <PageHead title="Feedback">
        Bugs, wishes and questions for the developers. Every post is visible to everyone who opens this page.
      </PageHead>
      <Panel title="New post">
        <form className="feedback-form" onSubmit={submit}>
          <label className="field">
            <span>Name (optional)</span>
            <input value={author} maxLength={80} autoComplete="name" onChange={(e) => setAuthor(e.target.value)} />
          </label>
          <label className="field">
            <span>Feedback</span>
            <textarea value={body} rows={5} maxLength={5000} required onChange={(e) => setBody(e.target.value)} />
          </label>
          {error && (
            <p role="alert" className="error-detail">
              Not posted: {error}
            </p>
          )}
          <button type="submit" className="button primary" disabled={saving || !body.trim()}>
            {saving ? 'Posting…' : 'Post'}
          </button>
        </form>
      </Panel>
      <Async state={state} height={240}>
        {(posts) => {
          const all = [...mine, ...posts]
          return (
            <Panel title="Posts" caption="Newest first.">
              {all.length === 0 && <p className="caption">No posts yet.</p>}
              {all.map((p) => (
                <article key={p.id} className="feedback-post">
                  <header>
                    <strong>{p.author || 'Anonymous'}</strong>
                    <time dateTime={p.created}>{when(p.created)}</time>
                  </header>
                  <p>{p.body}</p>
                </article>
              ))}
            </Panel>
          )
        }}
      </Async>
    </>
  )
}
