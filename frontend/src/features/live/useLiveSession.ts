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

export interface LiveQuestion {
  question_id: string
  prompt: string
  options: string[] | null
  closes_at: string
  window_seconds: number
  source_slide: number | null
}

export type QuestionCloseReason =
  | 'window_elapsed'
  | 'lecturer_closed'
  | 'session_ended'

export interface ClosedQuestion {
  question_id: string
  reason: QuestionCloseReason
  respondents: number
  eligible: number
}

export type LiveAlertKind =
  | 'topic_difficulty'
  | 'student_disengagement'
  | 'breakout_inactive'

export interface LiveAlert {
  alert_id: string
  kind: LiveAlertKind
  message: string
  reason: string
  confidence: number
}

export interface LiveSessionNotice {
  code: string
  detail: string | null
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
  activeQuestion: LiveQuestion | null
  closedQuestion: ClosedQuestion | null
  alerts: LiveAlert[]
  sessionNotice: LiveSessionNotice | null
  acknowledgeAlert: (alertId: string) => void
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

function isLiveQuestion(
  value: unknown,
): value is LiveQuestion {
  if (
    !value ||
    typeof value !== 'object'
  ) {
    return false
  }

  const question =
    value as Record<string, unknown>

  const optionsValid =
    question.options === null ||
    (
      Array.isArray(question.options) &&
      question.options.every(
        (option) =>
          typeof option === 'string',
      )
    )

  return (
    typeof question.question_id === 'string' &&
    typeof question.prompt === 'string' &&
    optionsValid &&
    typeof question.closes_at === 'string' &&
    typeof question.window_seconds === 'number' &&
    (
      question.source_slide === null ||
      typeof question.source_slide === 'number'
    )
  )
}

function isClosedQuestion(
  value: unknown,
): value is ClosedQuestion {
  if (
    !value ||
    typeof value !== 'object'
  ) {
    return false
  }

  const closed =
    value as Record<string, unknown>

  return (
    typeof closed.question_id === 'string' &&
    typeof closed.reason === 'string' &&
    typeof closed.respondents === 'number' &&
    typeof closed.eligible === 'number'
  )
}

function isLiveAlertKind(
  value: unknown,
): value is LiveAlertKind {
  return (
    value === 'topic_difficulty' ||
    value === 'student_disengagement' ||
    value === 'breakout_inactive'
  )
}

function isLiveAlert(
  value: unknown,
): value is LiveAlert {
  if (
    !value ||
    typeof value !== 'object'
  ) {
    return false
  }

  const alert =
    value as Record<string, unknown>

  return (
    typeof alert.alert_id === 'string' &&
    isLiveAlertKind(alert.kind) &&
    typeof alert.message === 'string' &&
    typeof alert.reason === 'string' &&
    typeof alert.confidence === 'number' &&
    alert.confidence >= 0 &&
    alert.confidence <= 1
  )
}

function isLiveSessionNotice(
  value: unknown,
): value is LiveSessionNotice {
  if (
    !value ||
    typeof value !== 'object'
  ) {
    return false
  }

  const notice =
    value as Record<string, unknown>

  return (
    typeof notice.code === 'string' &&
    (
      notice.detail === null ||
      notice.detail === undefined ||
      typeof notice.detail === 'string'
    )
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

  const [
    activeQuestion,
    setActiveQuestion,
  ] = useState<LiveQuestion | null>(
    null,
  )

  const [
    closedQuestion,
    setClosedQuestion,
  ] = useState<ClosedQuestion | null>(
    null,
  )

  const [
    alerts,
    setAlerts,
  ] = useState<LiveAlert[]>([])

  const [
    sessionNotice,
    setSessionNotice,
  ] = useState<LiveSessionNotice | null>(
    null,
  )

  useEffect(() => {
    setSessionState(null)
    setActiveQuestion(null)
    setClosedQuestion(null)
    setAlerts([])
    setSessionNotice(null)

    if (!sessionId) {
      setConnectionStatus(
        'unavailable',
      )
      return
    }

    const activeSessionId: string =
      sessionId

    const token = getAccessToken()

    if (!token) {
      setConnectionStatus(
        'disconnected',
      )
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
            last_seq?: number
            stream_id?: string
          } = {
            token: accessToken,
            session_id:
              activeSessionId,
          }

          if (
            lastSeq > 0 &&
            streamId
          ) {
            data.last_seq =
              lastSeq
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

            if (
              message.data.status ===
                'ended' ||
              message.data.status ===
                'cancelled'
            ) {
              setActiveQuestion(null)
            }

            return
          }

          if (
            message.type ===
              'question.delivered' &&
            isLiveQuestion(
              message.data,
            )
          ) {
            setActiveQuestion(
              message.data,
            )

            setClosedQuestion(null)

            return
          }

          if (
            message.type ===
              'question.closed' &&
            isClosedQuestion(
              message.data,
            )
          ) {
            const closed =
              message.data

            setClosedQuestion(
              closed,
            )

            setActiveQuestion(
              (current) =>
                current?.question_id ===
                closed.question_id
                  ? null
                  : current,
            )

            return
          }

          if (
            message.type ===
              'alert.raised' &&
            isLiveAlert(
              message.data,
            )
          ) {
            const alert =
              message.data

            setAlerts(
              (current) => {
                if (
                  current.some(
                    (existing) =>
                      existing.alert_id ===
                      alert.alert_id,
                  )
                ) {
                  return current
                }

                return [
                  alert,
                  ...current,
                ].slice(0, 20)
              },
            )

            return
          }

          if (
            message.type ===
              'error' &&
            isLiveSessionNotice(
              message.data,
            )
          ) {
            const notice =
              message.data

            console.warn(
              'Live session WebSocket error:',
              notice.code,
              notice.detail ?? '',
            )

            return
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

  function acknowledgeAlert(
    alertId: string,
  ) {
    setAlerts(
      (current) =>
        current.filter(
          (alert) =>
            alert.alert_id !==
            alertId,
        ),
    )
  }

  return {
    connectionStatus,
    sessionState,
    activeQuestion,
    closedQuestion,
    alerts,
    sessionNotice,
    acknowledgeAlert,
  }
}
