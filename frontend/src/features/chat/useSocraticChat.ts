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
  initialChatState,
} from './chatState'

export function useSocraticChat(sessionId: string) {
  const [state, dispatch] = useReducer(chatReducer, initialChatState)
  const controller = useRef<AbortController | null>(null)

  useEffect(() => () => controller.current?.abort(), [])

  const submit = useCallback(async (questionOverride?: string) => {
    const question = (questionOverride ?? state.draft).trim()
    if (!question || state.activeId || question.length > MAX_CHAT_QUESTION_LENGTH) return

    const requestId = crypto.randomUUID()
    const nextController = new AbortController()
    controller.current = nextController
    dispatch({ type: 'submit-started', id: requestId, question })

    try {
      await streamChat({
        sessionId,
        requestId,
        question,
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
  }, [sessionId, state.activeId, state.draft])

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

