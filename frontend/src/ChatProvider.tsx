import { useRef, useState, type ReactNode } from 'react'

import { streamChat, useApi, type ChatEvent, type ChatMessage, type ChatSetup, type Draft, type Extracted } from './api'
import { ChatContext, type AssistantTurn, type Chat, type Turn, type UserTurn } from './chat'

const content = (t: UserTurn) =>
  t.attachment ? `${t.text}\n\nAttached document "${t.attachment.name}"${t.attachment.truncated ? ' (cut to its first part)' : ''}:\n${t.attachment.text}` : t.text

export function ChatProvider({ page, children }: { page: string; children: ReactNode }) {
  const setup = useApi<ChatSetup>('/chat/models').data
  const [picked, setModel] = useState<string>()
  const [pickedThinking, setThinking] = useState('off')
  const [turns, setTurns] = useState<Turn[]>([])
  const [draft, setDraft] = useState<Draft | null>(null)
  const [notice, setNotice] = useState<string>()
  const abort = useRef<AbortController>(null)

  const model = picked ?? setup?.models.find((m) => m.default)?.id ?? ''
  const options = setup?.models.find((m) => m.id === model)?.thinking ?? []
  const thinking = options.includes(pickedThinking) ? pickedThinking : 'off'
  const last = turns[turns.length - 1]
  const busy = last?.role === 'assistant' && !last.done

  const update = (fn: (t: AssistantTurn) => AssistantTurn) => setTurns((all) => [...all.slice(0, -1), fn(all[all.length - 1] as AssistantTurn)])

  const onEvent = (e: ChatEvent) => {
    if (e.type === 'draft') setDraft({ changes: e.changes, checks: e.checks })
    update((t) => {
      switch (e.type) {
        case 'thinking':
          return { ...t, thinking: [t.thinking, e.text].filter(Boolean).join('\n\n') }
        case 'tool':
          return { ...t, steps: [...t.steps, { name: e.name, args: e.args }] }
        case 'result':
          return { ...t, steps: t.steps.map((s, i) => (i === t.steps.length - 1 ? { ...s, preview: e.preview } : s)) }
        case 'draft':
          return { ...t, drafted: true }
        case 'chart':
          return { ...t, charts: [...t.charts, e] }
        case 'answer':
          return { ...t, text: e.text, unverified: e.unverified, done: true }
        default:
          return { ...t, error: e.text, done: true }
      }
    })
  }

  async function ask(question: string, attachment?: Extracted) {
    const q = question.trim()
    if ((!q && !attachment) || busy || !model) return
    const user: UserTurn = { role: 'user', text: q || 'Extract the rows to add from this document.', attachment }
    const history = turns.flatMap((t): ChatMessage[] => (t.role === 'user' ? [{ role: 'user', content: content(t) }] : t.text ? [{ role: 'assistant', content: t.text }] : []))
    setTurns((all) => [...all, user, { role: 'assistant', steps: [], charts: [], done: false }])
    setNotice(undefined)
    abort.current = new AbortController()
    try {
      const messages = [...history, { role: 'user' as const, content: content(user) }]
      await streamChat({ model, thinking, messages, page, draft: draft?.changes ?? null }, onEvent, abort.current.signal)
      update((t) => (t.done ? t : { ...t, error: 'The answer stopped early.', done: true }))
    } catch (err) {
      const stopped = (err as Error).name === 'AbortError'
      update((t) => ({ ...t, error: stopped ? 'Stopped.' : `Could not reach the assistant (${(err as Error).message}).`, done: true }))
    }
  }

  const value: Chat = {
    setup,
    model,
    setModel,
    thinking,
    setThinking,
    turns,
    busy,
    ask,
    stop: () => abort.current?.abort(),
    reset: () => (setTurns([]), setDraft(null), setNotice(undefined)),
    draft,
    setDraft,
    notice,
    setNotice,
  }
  return <ChatContext.Provider value={value}>{children}</ChatContext.Provider>
}
