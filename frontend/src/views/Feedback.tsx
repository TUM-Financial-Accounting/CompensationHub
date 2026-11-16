import { useRef, useState, type FormEvent } from 'react'

import { readDataUrl, send, useApi, type FeedbackPost } from '../api'
import { Paperclip, X } from '../icons'
import { Async, PageHead, Panel } from '../ui'

const when = (iso: string) => new Date(iso).toLocaleString('en-GB', { dateStyle: 'medium', timeStyle: 'short' })

// Limits of POST /api/feedback (schemas.Photo, NewFeedback).
const PHOTO_TYPES = ['image/png', 'image/jpeg', 'image/gif', 'image/webp']
const MAX_PHOTO = 8 * 2 ** 20
const MAX_PHOTOS = 4

interface Picked { name: string; type: string; url: string }

export function FeedbackView() {
  // A new query per visit skips useApi's session cache, so posts by others show up.
  const [visit] = useState(Date.now)
  const state = useApi<FeedbackPost[]>(`/feedback?visit=${visit}`)
  const [mine, setMine] = useState<FeedbackPost[]>([])
  const [replying, setReplying] = useState<number>()
  const [marked, setMarked] = useState<Record<number, boolean>>({}) // done flags changed in this visit
  const [error, setError] = useState<string>()
  const add = (post: FeedbackPost) => setMine((m) => [post, ...m])
  const mark = (id: number, done: boolean) => {
    setError(undefined)
    send<FeedbackPost>('POST', `/feedback/${id}/done`, { done }).then(
      (p) => setMarked((m) => ({ ...m, [p.id]: p.done })),
      (e: Error) => setError(`Not changed: ${e.message}`),
    )
  }

  return (
    <>
      <PageHead title="Feedback">
        Bugs, wishes and questions for the developers. Every post is visible to everyone who opens this page.
      </PageHead>
      <Panel title="New post">
        <PostForm onPosted={add} />
      </Panel>
      <Async state={state} height={240}>
        {(posts) => {
          const all = [...mine, ...posts].map((p) => (p.id in marked ? { ...p, done: marked[p.id] } : p))
          const replies = (id: number) => all.filter((r) => r.reply_to === id).sort((a, b) => a.id - b.id)
          const threads = all.filter((p) => p.reply_to === null)
          return (
            <Panel title="Posts" caption="Newest first; replies under their post, oldest first. Anyone can mark a post as done.">
              {error && (
                <p role="alert" className="error-detail">
                  {error}
                </p>
              )}
              {threads.length === 0 && <p className="caption">No posts yet.</p>}
              {threads.map((p) => (
                <section key={p.id} className={`feedback-thread${p.done ? ' done' : ''}`}>
                  <Post post={p} />
                  {(replies(p.id).length > 0 || replying === p.id) && (
                    <div className="feedback-replies">
                      {replies(p.id).map((r) => (
                        <Post key={r.id} post={r} />
                      ))}
                      {replying === p.id && (
                        <PostForm
                          replyTo={p}
                          onPosted={(r) => {
                            add(r)
                            setReplying(undefined)
                          }}
                          onCancel={() => setReplying(undefined)}
                        />
                      )}
                    </div>
                  )}
                  <div className="feedback-actions">
                    {replying !== p.id && (
                      <button type="button" className="link" onClick={() => setReplying(p.id)}>
                        Reply
                      </button>
                    )}
                    <button type="button" className="link" onClick={() => mark(p.id, !p.done)}>
                      {p.done ? 'Mark as not done' : 'Mark as done'}
                    </button>
                  </div>
                </section>
              ))}
            </Panel>
          )
        }}
      </Async>
    </>
  )
}

function Post({ post }: { post: FeedbackPost }) {
  const by = post.author || 'Anonymous'
  return (
    <article className="feedback-post">
      <header>
        <strong>{by}</strong>
        <time dateTime={post.created}>{when(post.created)}</time>
        {post.done && <span className="badge">Done</span>}
      </header>
      <p>{post.body}</p>
      {post.photos.length > 0 && (
        <div className="feedback-photos">
          {post.photos.map((id, i) => (
            <a key={id} href={`/api/feedback/photos/${id}`} target="_blank" rel="noreferrer">
              <img src={`/api/feedback/photos/${id}`} alt={`Photo ${i + 1} posted by ${by}`} loading="lazy" />
            </a>
          ))}
        </div>
      )}
    </article>
  )
}

/** A new post, or with `replyTo` a reply to that post. */
function PostForm({ replyTo, onPosted, onCancel }: { replyTo?: FeedbackPost; onPosted: (p: FeedbackPost) => void; onCancel?: () => void }) {
  const [author, setAuthor] = useState('')
  const [body, setBody] = useState('')
  const [photos, setPhotos] = useState<Picked[]>([])
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState<string>()
  const file = useRef<HTMLInputElement>(null)

  async function attach(files: File[]) {
    setError(undefined)
    const bad = files.find((f) => !PHOTO_TYPES.includes(f.type) || f.size > MAX_PHOTO)
    if (bad) return setError(`${bad.name}: photos must be PNG, JPEG, GIF or WebP, at most ${MAX_PHOTO / 2 ** 20} MB.`)
    if (photos.length + files.length > MAX_PHOTOS) return setError(`At most ${MAX_PHOTOS} photos per post.`)
    const urls = await Promise.all(files.map(readDataUrl))
    setPhotos((ps) => [...ps, ...files.map((f, i) => ({ name: f.name, type: f.type, url: urls[i] }))])
  }

  const submit = async (e: FormEvent) => {
    e.preventDefault()
    setSaving(true)
    setError(undefined)
    try {
      const post = await send<FeedbackPost>('POST', '/feedback', {
        author,
        body,
        reply_to: replyTo?.id ?? null,
        photos: photos.map((p) => ({ type: p.type, data: p.url.split(',')[1] })),
      })
      setBody('')
      setPhotos([])
      onPosted(post)
    } catch (err) {
      setError(`Not posted: ${(err as Error).message}`)
    } finally {
      setSaving(false)
    }
  }

  return (
    <form className="feedback-form" onSubmit={submit} aria-label={replyTo ? `Reply to ${replyTo.author || 'Anonymous'}` : undefined}>
      <label className="field">
        <span>Name (optional)</span>
        <input value={author} maxLength={80} autoComplete="name" onChange={(e) => setAuthor(e.target.value)} />
      </label>
      <label className="field">
        <span>{replyTo ? 'Reply' : 'Feedback'}</span>
        <textarea value={body} rows={replyTo ? 3 : 5} maxLength={5000} required autoFocus={!!replyTo} onChange={(e) => setBody(e.target.value)} />
      </label>
      {photos.length > 0 && (
        <div className="feedback-photos">
          {photos.map((p, i) => (
            <figure key={i}>
              <img src={p.url} alt={p.name} />
              <button type="button" className="icon-button" aria-label={`Remove ${p.name}`} onClick={() => setPhotos((ps) => ps.filter((_, j) => j !== i))}>
                <X size={14} />
              </button>
            </figure>
          ))}
        </div>
      )}
      {error && (
        <p role="alert" className="error-detail">
          {error}
        </p>
      )}
      <input
        ref={file}
        type="file"
        accept={PHOTO_TYPES.join(',')}
        multiple
        hidden
        onChange={(e) => {
          const files = [...(e.target.files ?? [])]
          e.target.value = ''
          if (files.length) attach(files)
        }}
      />
      <div className="feedback-actions">
        <button type="submit" className="button primary" disabled={saving || !body.trim()}>
          {saving ? 'Posting…' : replyTo ? 'Post reply' : 'Post'}
        </button>
        <button type="button" className="button" onClick={() => file.current?.click()} disabled={saving || photos.length >= MAX_PHOTOS}>
          <Paperclip size={16} /> Add photos
        </button>
        {onCancel && (
          <button type="button" className="button ghost" onClick={onCancel}>
            Cancel
          </button>
        )}
      </div>
    </form>
  )
}
