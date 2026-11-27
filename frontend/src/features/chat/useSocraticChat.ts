import {
  useCallback,
  useEffect,
  useReducer,
  useRef,
  useState,
} from 'react'

import {
  MAX_CHAT_QUESTION_LENGTH,
  streamChat,
} from './chatApi'
import { chatHistoryLoadMessage, listAllChatHistory, restoredExchange } from './chatHistoryApi'
import {
  chatReducer,
  historyFor,
  initialChatState,
} from './chatState'

export function useSocraticChat(sessionId: string, discussionSince?: string, discussionUntil?: string, discussion = false, discussionRollingMinutes?: number) {
  const [state, dispatch] = useReducer(chatReducer, initialChatState)
  const controller = useRef<AbortController | null>(null)
  const [historyLoading, setHistoryLoading] = useState(true)
  const [historyError, setHistoryError] = useState<string | null>(null)
  const [historyAttempt, setHistoryAttempt] = useState(0)
  const [saveWarning, setSaveWarning] = useState(false)

  useEffect(() => () => controller.current?.abort(), [])

  useEffect(() => {
    // A different session or source must never inherit another panel's
    // previous exchanges. Abort an outstanding reply on navigation.
    controller.current?.abort()
    controller.current = null
    dispatch({ type: 'history-reset' })
    setSaveWarning(false)
  }, [sessionId, discussion])

  useEffect(() => {
    const abort = new AbortController()
    let mounted = true
    setHistoryLoading(true)
    setHistoryError(null)

    void listAllChatHistory(abort.signal, sessionId).then(
      (saved) => {
        if (!mounted) return
        const source = discussion ? 'discussion' : 'materials'
        const exchanges = saved
          .filter((record) => record.session_id === sessionId && record.source === source)
          .reverse()
          .map(restoredExchange)
        dispatch({ type: 'history-loaded', exchanges })
        setHistoryLoading(false)
      },
      (failure: unknown) => {
        if (!mounted) return
        setHistoryError(chatHistoryLoadMessage(failure))
        setHistoryLoading(false)
      },
    )

    return () => {
      mounted = false
      abort.abort()
    }
  }, [sessionId, discussion, historyAttempt])

  const submit = useCallback(async (questionOverride?: string) => {
    const question = (questionOverride ?? state.draft).trim()
    if (!question || controller.current || question.length > MAX_CHAT_QUESTION_LENGTH) return

    const requestId = crypto.randomUUID()
    const nextController = new AbortController()
    controller.current = nextController
    setSaveWarning(false)
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
        onEvent: (event) => {
          if (controller.current !== nextController) return
          if (event.type === 'completed' && event.history_saved === false) setSaveWarning(true)
          dispatch({ type: 'stream-event', event })
        },
      })
    } catch (caught: unknown) {
      if (controller.current !== nextController) return
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
    historyLoading,
    historyError,
    saveWarning,
    retryHistory: () => setHistoryAttempt((attempt) => attempt + 1),
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
