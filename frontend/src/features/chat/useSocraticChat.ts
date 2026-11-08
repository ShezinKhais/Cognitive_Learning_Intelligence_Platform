import {
  useCallback,
  useEffect,
  useReducer,
  useRef,
} from 'react'

import {
  MAX_CHAT_QUESTION_LENGTH,
  streamChat,
} from './chatApi'
import {
  chatReducer,
  historyFor,
  initialChatState,
} from './chatState'
import type { ChatExchange, ChatState } from './chatTypes'

// Finished exchanges are kept for this tab, so leaving the page and coming
// back, or reviewing after class, does not lose what the tutor said. Only
// this tab: a shared computer does not show the next person the transcript.
const KEPT = 20

function storageKey(sessionId: string, discussion: boolean, range: string): string {
  // Each discussion range is its own conversation: an answer about the last
  // 15 minutes is not context for a question about the whole class.
  return `clip.tutor.${sessionId}.${discussion ? `discussion.${range}` : 'material'}`
}

function restore(key: string): ChatState {
  try {
    const raw = window.sessionStorage.getItem(key)
    const kept = raw ? (JSON.parse(raw) as ChatExchange[]) : []
    const exchanges = Array.isArray(kept) ? kept.filter((exchange) => exchange?.phase === 'completed') : []
    return { ...initialChatState, exchanges }
  } catch {
    return initialChatState
  }
}

export function useSocraticChat(sessionId: string, discussionSince?: string, discussionUntil?: string, discussion = false, discussionRollingMinutes?: number) {
  const key = storageKey(sessionId, discussion, `${discussionSince ?? 'all'}.${discussionRollingMinutes ?? ''}`)
  const [state, dispatch] = useReducer(chatReducer, key, restore)
  const controller = useRef<AbortController | null>(null)

  useEffect(() => {
    const done = state.exchanges.filter((exchange) => exchange.phase === 'completed').slice(-KEPT)
    try {
      window.sessionStorage.setItem(key, JSON.stringify(done))
    } catch {
      // Storage full or blocked: the conversation still works, it is just not kept.
    }
  }, [key, state.exchanges])

  useEffect(() => () => controller.current?.abort(), [])

  const submit = useCallback(async (questionOverride?: string) => {
    const question = (questionOverride ?? state.draft).trim()
    if (!question || controller.current || question.length > MAX_CHAT_QUESTION_LENGTH) return

    const requestId = crypto.randomUUID()
    const nextController = new AbortController()
    controller.current = nextController
    dispatch({ type: 'submit-started', id: requestId, question })

    try {
      const discussionEnd = discussionRollingMinutes ? Date.now() : undefined
      await streamChat({
        sessionId,
        source: discussion ? 'discussion' : undefined,
        discussionSince: discussionRollingMinutes && discussionEnd !== undefined ? new Date(discussionEnd - discussionRollingMinutes * 60_000).toISOString() : discussionSince,
        discussionUntil: discussionEnd !== undefined ? new Date(discussionEnd).toISOString() : discussionUntil,
        requestId,
        question,
        history: historyFor(state.exchanges),
        signal: nextController.signal,
        onEvent: (event) => dispatch({ type: 'stream-event', event }),
      })
    } catch (caught: unknown) {
      if (nextController.signal.aborted) {
        dispatch({ type: 'cancelled-locally' })
      } else {
        dispatch({
          type: 'request-failed',
          detail: caught instanceof Error
            ? caught.message
            : 'The tutor could not respond.',
        })
      }
    } finally {
      if (controller.current === nextController) controller.current = null
    }
  }, [sessionId, discussion, discussionSince, discussionUntil, discussionRollingMinutes, state.draft, state.exchanges])

  const cancel = useCallback(() => {
    if (!controller.current) return
    dispatch({ type: 'cancel-started' })
    controller.current.abort()
  }, [])

  return {
    state,
    setDraft: (value: string) => dispatch({ type: 'draft-changed', value }),
    submit,
    cancel,
    askFollowUp: (prompt: string) => {
      dispatch({ type: 'follow-up-selected', prompt })
      void submit(prompt)
    },
    clearError: () => dispatch({ type: 'error-cleared' }),
  }
}
