import {
  useCallback,
  useEffect,
  useReducer,
  useRef,
} from 'react'

import {
  clearAccessToken,
  getAccessToken,
} from '../../api'
import {
  initialLiveSessionState,
  liveSessionReducer,
} from './liveSessionState'
import {
  parseAnswerReceipt,
  parseAttentionPrompt,
  parseFeedbackResult,
  parseLiveError,
  parseLiveQuestion,
  parseQuestionClosed,
  parseReady,
  parseServerEvent,
  parseSessionState,
} from './liveSessionProtocol'
import type { SessionStatus } from './types'

interface Cursor {
  lastSeq: number
  streamId: string | null
}

interface AnswerSubmission {
  selected_option?: number
  free_text?: string
}

const MAX_RECONNECT_DELAY_MS = 10_000

function liveSocketUrl(): string {
  const url = new URL('/ws/session', window.location.origin)
  url.protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
  return url.toString()
}

function cursorKey(sessionId: string): string {
  return `clip_live_session_cursor:${sessionId}`
}

function readCursor(sessionId: string): Cursor {
  try {
    const value = window.sessionStorage.getItem(cursorKey(sessionId))
    if (!value) return { lastSeq: 0, streamId: null }

    const parsed = JSON.parse(value) as Partial<Cursor>
    return {
      lastSeq:
        typeof parsed.lastSeq === 'number' && parsed.lastSeq >= 0
          ? parsed.lastSeq
          : 0,
      streamId:
        typeof parsed.streamId === 'string' ? parsed.streamId : null,
    }
  } catch {
    return { lastSeq: 0, streamId: null }
  }
}

function storeCursor(sessionId: string, cursor: Cursor): void {
  try {
    window.sessionStorage.setItem(cursorKey(sessionId), JSON.stringify(cursor))
  } catch {
    // A blocked or full sessionStorage must not break the live connection.
    // Recovery still works for disconnects during this mounted page.
  }
}

export function useLiveSession(
  sessionId: string,
  initialStatus: SessionStatus,
) {
  const [state, dispatch] = useReducer(
    liveSessionReducer,
    initialStatus,
    initialLiveSessionState,
  )
  const socketRef = useRef<WebSocket | null>(null)
  const readyRef = useRef(false)

  useEffect(() => {
    const token = getAccessToken()
    if (!token) {
      dispatch({ type: 'connection', status: 'disconnected' })
      return
    }

    let socket: WebSocket | null = null
    let reconnectTimer: number | undefined
    let stopped = false
    let connectedOnce = false
    let retryCount = 0
    let cursor = readCursor(sessionId)

    function scheduleReconnect(): void {
      if (stopped || reconnectTimer !== undefined) return

      if (!window.navigator.onLine) {
        dispatch({ type: 'connection', status: 'offline' })
        return
      }

      dispatch({ type: 'connection', status: 'reconnecting' })
      const delay = Math.min(1000 * 2 ** retryCount, MAX_RECONNECT_DELAY_MS)
      retryCount += 1
      reconnectTimer = window.setTimeout(() => {
        reconnectTimer = undefined
        connect()
      }, delay)
    }

    function connect(): void {
      if (stopped || !window.navigator.onLine) {
        if (!stopped) dispatch({ type: 'connection', status: 'offline' })
        return
      }

      dispatch({
        type: 'connection',
        status: connectedOnce ? 'reconnecting' : 'connecting',
      })
      readyRef.current = false

      const currentSocket = new WebSocket(liveSocketUrl())
      socket = currentSocket
      socketRef.current = currentSocket

      currentSocket.addEventListener('open', () => {
        const data: Record<string, unknown> = {
          token,
          session_id: sessionId,
          last_seq: cursor.lastSeq,
        }
        if (cursor.streamId) data.stream_id = cursor.streamId

        currentSocket.send(JSON.stringify({ type: 'auth', data }))
      })

      currentSocket.addEventListener('message', (messageEvent) => {
        let raw: unknown
        try {
          raw = JSON.parse(String(messageEvent.data))
        } catch {
          return
        }

        const event = parseServerEvent(raw)
        if (!event) return

        if (event.type === 'ready') {
          const ready = parseReady(event.data)
          if (!ready || ready.session_id !== sessionId) {
            currentSocket.close(4400, 'invalid ready event')
            return
          }

          connectedOnce = true
          readyRef.current = true
          retryCount = 0

          if (ready.resumed_from_seq === null && cursor.lastSeq > 0) {
            cursor = { lastSeq: 0, streamId: ready.stream_id }
            storeCursor(sessionId, cursor)
            dispatch({ type: 'connection', status: 'recovering' })
          } else {
            cursor.streamId = ready.stream_id
            storeCursor(sessionId, cursor)
            dispatch({ type: 'connection', status: 'connected' })
          }
          return
        }

        if (event.seq > 0) {
          if (event.seq <= cursor.lastSeq) return

          if (cursor.lastSeq > 0 && event.seq > cursor.lastSeq + 1) {
            dispatch({ type: 'connection', status: 'recovering' })
            currentSocket.close(4000, 'event gap detected')
            return
          }

          cursor.lastSeq = event.seq
          storeCursor(sessionId, cursor)
        }

        switch (event.type) {
          case 'session.state': {
            const payload = parseSessionState(event.data)
            if (payload && payload.session_id === sessionId) {
              dispatch({ type: 'session-state', payload })
              dispatch({ type: 'connection', status: 'connected' })
            }
            break
          }
          case 'question.delivered': {
            const payload = parseLiveQuestion(event.data)
            if (payload) dispatch({ type: 'question-delivered', payload })
            break
          }
          case 'question.closed': {
            const payload = parseQuestionClosed(event.data)
            if (payload) dispatch({ type: 'question-closed', payload })
            break
          }
          case 'answer.receipt': {
            const payload = parseAnswerReceipt(event.data)
            if (payload) dispatch({ type: 'answer-receipt', payload })
            break
          }
          case 'feedback.result': {
            const payload = parseFeedbackResult(event.data)
            if (payload) dispatch({ type: 'feedback-result', payload })
            break
          }
          case 'prompt.attention': {
            const payload = parseAttentionPrompt(event.data)
            if (payload) dispatch({ type: 'attention-prompt', payload })
            break
          }
          case 'error': {
            const payload = parseLiveError(event.data)
            if (payload) dispatch({ type: 'error', payload })
            break
          }
        }
      })

      currentSocket.addEventListener('close', (closeEvent) => {
        if (socket === currentSocket) socket = null
        if (socketRef.current === currentSocket) socketRef.current = null
        readyRef.current = false
        if (stopped) return

        if (closeEvent.code === 4001) {
          stopped = true
          clearAccessToken()
          window.location.assign('/login')
          return
        }

        if (closeEvent.code === 4003) {
          stopped = true
          dispatch({ type: 'connection', status: 'forbidden' })
          return
        }

        if (closeEvent.code === 4400) {
          stopped = true
          dispatch({
            type: 'error',
            payload: {
              code: 'PROTOCOL_ERROR',
              detail: closeEvent.reason || 'The live-session protocol was rejected.',
            },
          })
          dispatch({ type: 'connection', status: 'disconnected' })
          return
        }

        scheduleReconnect()
      })

      currentSocket.addEventListener('error', () => {
        currentSocket.close()
      })
    }

    function handleOffline(): void {
      if (reconnectTimer !== undefined) {
        window.clearTimeout(reconnectTimer)
        reconnectTimer = undefined
      }
      dispatch({ type: 'connection', status: 'offline' })
      socket?.close()
    }

    function handleOnline(): void {
      if (!stopped && !socket) connect()
    }

    window.addEventListener('offline', handleOffline)
    window.addEventListener('online', handleOnline)
    connect()

    return () => {
      stopped = true
      readyRef.current = false
      if (reconnectTimer !== undefined) window.clearTimeout(reconnectTimer)
      window.removeEventListener('offline', handleOffline)
      window.removeEventListener('online', handleOnline)
      if (socketRef.current === socket) socketRef.current = null
      socket?.close(1000, 'student left session')
    }
  }, [sessionId])

  useEffect(() => {
    const checkpoint = state.checkpoint
    if (!checkpoint || checkpoint.phase !== 'answering') return

    const expiresAt = Date.parse(checkpoint.question.closes_at)
    if (!Number.isFinite(expiresAt)) return

    function expire(): void {
      if (Date.now() >= expiresAt) {
        dispatch({
          type: 'response-window-elapsed',
          questionId: checkpoint!.question.question_id,
        })
      }
    }

    expire()
    const timer = window.setInterval(expire, 250)
    return () => window.clearInterval(timer)
  }, [state.checkpoint])

  useEffect(() => {
    const prompt = state.attentionPrompt
    if (!prompt) return

    const expiresAt = Date.parse(prompt.expires_at)
    if (!Number.isFinite(expiresAt)) return

    const delay = Math.max(0, expiresAt - Date.now())
    const timer = window.setTimeout(() => {
      dispatch({
        type: 'attention-prompt-cleared',
        promptId: prompt.prompt_id,
      })
    }, delay)
    return () => window.clearTimeout(timer)
  }, [state.attentionPrompt])

  const send = useCallback((type: string, data: Record<string, unknown>): boolean => {
    const socket = socketRef.current
    if (!socket || socket.readyState !== WebSocket.OPEN || !readyRef.current) {
      dispatch({
        type: 'error',
        payload: {
          code: 'CONNECTION_UNAVAILABLE',
          detail: 'Wait for the live connection before trying again.',
        },
      })
      return false
    }

    socket.send(JSON.stringify({ type, data }))
    return true
  }, [])

  const selectOption = useCallback((option: number) => {
    dispatch({ type: 'select-option', option })
  }, [])

  const setFreeText = useCallback((value: string) => {
    dispatch({ type: 'set-free-text', value })
  }, [])

  const submitAnswer = useCallback((): boolean => {
    const checkpoint = state.checkpoint
    if (!checkpoint || (checkpoint.phase !== 'answering' && checkpoint.phase !== 'rejected')) {
      return false
    }

    const answer: AnswerSubmission = {}
    if (checkpoint.question.options) {
      if (checkpoint.selectedOption === null) return false
      answer.selected_option = checkpoint.selectedOption
    } else {
      const text = checkpoint.freeText.trim()
      if (!text) return false
      answer.free_text = text
    }

    const deliveredAt =
      Date.parse(checkpoint.question.closes_at) -
      checkpoint.question.window_seconds * 1000
    const clientElapsed = Number.isFinite(deliveredAt)
      ? Math.max(0, Math.min(
          checkpoint.question.window_seconds * 1000,
          Date.now() - deliveredAt,
        ))
      : 0

    const sent = send('answer.submit', {
      question_id: checkpoint.question.question_id,
      ...answer,
      client_elapsed_ms: Math.round(clientElapsed),
    })
    if (sent) dispatch({ type: 'answer-sent' })
    return sent
  }, [send, state.checkpoint])

  const acknowledgePrompt = useCallback((dismissed: boolean): boolean => {
    const prompt = state.attentionPrompt
    if (!prompt) return false

    const sent = send('prompt.ack', {
      prompt_id: prompt.prompt_id,
      dismissed,
    })
    if (sent) {
      dispatch({
        type: 'attention-prompt-cleared',
        promptId: prompt.prompt_id,
      })
    }
    return sent
  }, [send, state.attentionPrompt])

  return {
    state,
    selectOption,
    setFreeText,
    submitAnswer,
    acknowledgePrompt,
    clearError: () => dispatch({ type: 'clear-error' }),
  }
}
