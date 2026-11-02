import { createContext, useContext } from 'react'

import type { ChartSpec, ChatSetup, Draft, Extracted } from './api'

// One conversation for the whole app, so the side panel and the Assistant page share it and it
// survives navigation. `page` (the current route) tells the assistant what "this company" means.

export type Step = { name: string; args: Record<string, unknown>; preview?: string }
export type UserTurn = { role: 'user'; text: string; attachment?: Extracted }
export type AssistantTurn = {
  role: 'assistant'
  steps: Step[]
  charts: ChartSpec[]
  thinking?: string
  text?: string
  unverified?: string[]
  error?: string
  drafted?: boolean
  done: boolean
}
export type Turn = UserTurn | AssistantTurn

export interface Chat {
  setup?: ChatSetup
  model: string
  setModel: (m: string) => void
  thinking: string
  setThinking: (t: string) => void
  turns: Turn[]
  busy: boolean
  ask: (question: string, attachment?: Extracted) => void
  stop: () => void
  reset: () => void
  draft: Draft | null
  setDraft: (d: Draft | null) => void
  notice?: string
  setNotice: (n?: string) => void
}

export const ChatContext = createContext<Chat | null>(null)

export const useChat = () => useContext(ChatContext)!

