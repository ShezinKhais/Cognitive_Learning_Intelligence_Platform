import {
  useEffect,
  useState,
} from 'react'

import {
  clearAccessToken,
  getAccessToken,
} from '../../api'
import { actionForClose } from '../materials/closeCodes'

export type LiveConnectionStatus =
  | 'connecting'
  | 'connected'
  | 'disconnected'
  | 'unavailable'

export type LiveSessionStatus =
  | 'prepared'
  | 'active'
  | 'ending'
  | 'ended'
  | 'cancelled'

export interface LiveSessionState {
  session_id: string
  status: LiveSessionStatus
  participant_count: number
  active_question_id: string | null
  questions_delivered: number
  paused: boolean
}

interface ServerEvent {
  type: string
  seq?: number
  data?: unknown
}

interface ReadyPayload {
  resumed_from_seq: number | null
  stream_id: string | null
}

interface UseLiveSessionResult {
  connectionStatus: LiveConnectionStatus
  sessionState: LiveSessionState | null
}

function liveSocketUrl(): string {
  const url = new URL(
    '/ws/session',
    window.location.origin,
  )

  url.protocol =
    window.location.protocol === 'https:'
      ? 'wss:'
      : 'ws:'

  return url.toString()
}

function isLiveSessionState(
  value: unknown,
): value is LiveSessionState {
  if (
    !value ||
    typeof value !== 'object'
  ) {
    return false
  }

  const state =
    value as Record<string, unknown>

  return (
    typeof state.session_id === 'string' &&
    typeof state.status === 'string' &&
    typeof state.participant_count === 'number' &&
    (
      state.active_question_id === null ||
      typeof state.active_question_id === 'string'
    ) &&
    typeof state.questions_delivered === 'number' &&
    typeof state.paused === 'boolean'
  )
}

function isReadyPayload(
  value: unknown,
): value is ReadyPayload {
  if (
    !value ||
    typeof value !== 'object'
  ) {
    return false
  }

  const ready =
    value as Record<string, unknown>

  return (
    (
      ready.resumed_from_seq === null ||
      typeof ready.resumed_from_seq === 'number'
    ) &&
    (
      ready.stream_id === null ||
      typeof ready.stream_id === 'string'
    )
  )
}

export function useLiveSession(
  sessionId: string | undefined,
): UseLiveSessionResult {
  const [
    connectionStatus,
    setConnectionStatus,
  ] = useState<LiveConnectionStatus>(
    'connecting',
  )

  const [
    sessionState,
    setSessionState,
  ] = useState<LiveSessionState | null>(
    null,
  )

  useEffect(() => {
    if (!sessionId) {
      setConnectionStatus(
        'unavailable',
      )
      setSessionState(null)
      return
    }

    const activeSessionId: string =
      sessionId

    const token = getAccessToken()

    if (!token) {
      setConnectionStatus(
        'disconnected',
      )
      setSessionState(null)
      return
    }

    const accessToken: string = token

    let socket: WebSocket | null = null
    let retryTimer: number | undefined
    let stopped = false
    let retryCount = 0
    let lastSeq = 0
    let streamId: string | null = null

    function connect() {
      if (stopped) {
        return
      }

      setConnectionStatus(
        'connecting',
      )

      const currentSocket =
        new WebSocket(
          liveSocketUrl(),
        )

      socket = currentSocket

      currentSocket.addEventListener(
        'open',
        () => {
          const data: {
            token: string
            session_id: string
            last_seq: number
            stream_id?: string
          } = {
            token: accessToken,
            session_id:
              activeSessionId,
            last_seq: lastSeq,
          }

          if (streamId) {
            data.stream_id =
              streamId
          }

          currentSocket.send(
            JSON.stringify({
              type: 'auth',
              data,
            }),
          )
        },
      )

      currentSocket.addEventListener(
        'message',
        (event) => {
          let message: ServerEvent

          try {
            message =
              JSON.parse(
                String(event.data),
              ) as ServerEvent
          } catch {
            return
          }

          if (
            typeof message.seq ===
              'number' &&
            message.seq > lastSeq
          ) {
            lastSeq =
              message.seq
          }

          if (
            message.type ===
              'ready' &&
            isReadyPayload(
              message.data,
            )
          ) {
            retryCount = 0

            if (
              message.data
                .resumed_from_seq ===
              null
            ) {
              lastSeq = 0
            }

            streamId =
              message.data.stream_id

            setConnectionStatus(
              'connected',
            )

            return
          }

          if (
            message.type ===
              'session.state' &&
            isLiveSessionState(
              message.data,
            )
          ) {
            setSessionState(
              message.data,
            )
          }
        },
      )

      currentSocket.addEventListener(
        'close',
        (event) => {
          if (stopped) {
            return
          }

          const action =
            actionForClose(
              event.code,
            )

          if (
            action === 'sign-in'
          ) {
            stopped = true

            clearAccessToken()

            window.location.assign(
              '/login',
            )

            return
          }

          if (
            action === 'stop'
          ) {
            stopped = true

            setConnectionStatus(
              'unavailable',
            )

            return
          }

          setConnectionStatus(
            'disconnected',
          )

          const delay =
            Math.min(
              1000 *
                2 ** retryCount,
              10_000,
            )

          retryCount += 1

          retryTimer =
            window.setTimeout(
              connect,
              delay,
            )
        },
      )

      currentSocket.addEventListener(
        'error',
        () => {
          currentSocket.close()
        },
      )
    }

    connect()

    return () => {
      stopped = true

      if (
        retryTimer !==
        undefined
      ) {
        window.clearTimeout(
          retryTimer,
        )
      }

      socket?.close()
    }
  }, [sessionId])

  return {
    connectionStatus,
    sessionState,
  }
}