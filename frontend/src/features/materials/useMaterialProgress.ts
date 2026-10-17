import {
  useEffect,
  useRef,
  useState,
} from 'react'

import {
  clearAccessToken,
  refreshAccessToken,
  getAccessToken,
} from '../../api'
import { actionForClose } from './closeCodes'
import type {
  MaterialProgress,
  ProgressConnectionStatus,
} from './types'

interface ServerEvent {
  type: string
  seq?: number
  data?: unknown
}

function resumedSequence(value: unknown): number | null {
  if (!value || typeof value !== 'object') return null

  const resumed = (value as Record<string, unknown>).resumed_from_seq
  return typeof resumed === 'number' ? resumed : null
}

function sequenceStream(value: unknown): string | null {
  if (!value || typeof value !== 'object') return null

  const streamId = (value as Record<string, unknown>).stream_id
  return typeof streamId === 'string' ? streamId : null
}

interface MaterialProgressOptions {
  enabled?: boolean
  onReconnect?: () => void
}

const MATERIAL_STAGES = new Set([
  'validating',
  'extracting',
  'chunking',
  'embedding',
  'generating',
  'done',
  'failed',
])

function isMaterialProgress(value: unknown): value is MaterialProgress {
  if (!value || typeof value !== 'object') return false

  const progress = value as Record<string, unknown>
  return (
    typeof progress.material_id === 'string' &&
    typeof progress.stage === 'string' &&
    MATERIAL_STAGES.has(progress.stage) &&
    typeof progress.percent === 'number' &&
    progress.percent >= 0 &&
    progress.percent <= 100 &&
    (
      progress.message === undefined ||
      progress.message === null ||
      typeof progress.message === 'string'
    )
  )
}

function progressSocketUrl(): string {
  const url = new URL('/ws/session', window.location.origin)
  url.protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
  return url.toString()
}

export function useMaterialProgress(
  onProgress: (progress: MaterialProgress) => void,
  options: MaterialProgressOptions = {},
): ProgressConnectionStatus {
  const callback = useRef(onProgress)
  const reconnectCallback = useRef(options.onReconnect)
  const [status, setStatus] = useState<ProgressConnectionStatus>('connecting')
  const enabled = options.enabled ?? true

  useEffect(() => {
    callback.current = onProgress
    reconnectCallback.current = options.onReconnect
  }, [onProgress, options.onReconnect])

  useEffect(() => {
    if (!enabled) {
      setStatus('disconnected')
      return
    }

    const token = getAccessToken()

    if (!token) {
      setStatus('disconnected')
      return
    }
    const accessToken: string = token

    let socket: WebSocket | null = null
    let retryTimer: number | undefined
    let stopped = false
    let retryCount = 0
    let lastSeq = 0
    let streamId: string | null = null
    let connectedOnce = false
    // One refresh per refusal; any message after it proves the new token.
    let tokenRenewed = false

    function connect() {
      if (stopped) return

      setStatus('connecting')
      const currentSocket = new WebSocket(progressSocketUrl())
      currentSocket.addEventListener('message', () => {
        tokenRenewed = false
      })
      socket = currentSocket

      currentSocket.addEventListener('open', () => {
        const data: {
          token: string
          last_seq: number
          stream_id?: string
        } = {
          // The latest, so a reconnect after a refresh sends the new token.
          token: getAccessToken() ?? accessToken,
          // Zero matters when the socket connects after a very fast upload:
          // it asks the server to replay progress emitted before READY.
          last_seq: lastSeq,
        }
        if (streamId) data.stream_id = streamId

        currentSocket.send(JSON.stringify({
          type: 'auth',
          data,
        }))
      })

      currentSocket.addEventListener('message', (event) => {
        let message: ServerEvent

        try {
          message = JSON.parse(String(event.data)) as ServerEvent
        } catch {
          return
        }

        if (
          typeof message.seq === 'number' &&
          message.seq > lastSeq
        ) {
          lastSeq = message.seq
        }

        if (message.type === 'ready') {
          const reconnected = connectedOnce
          connectedOnce = true
          retryCount = 0

          // A null cursor means the backend restarted or evicted this user's
          // bounded replay buffer. Accept the new stream from sequence zero;
          // the reconnect callback still refreshes the REST snapshot.
          if (reconnected && resumedSequence(message.data) === null) {
            lastSeq = 0
          }

          // The generation changes whenever the backend restarts or evicts an
          // idle user's replay state. Sending it with the next cursor prevents
          // a new in-memory counter from being mistaken for the old stream.
          streamId = sequenceStream(message.data)

          setStatus('connected')
          if (reconnected) reconnectCallback.current?.()
          return
        }

        if (
          message.type === 'material.progress' &&
          isMaterialProgress(message.data)
        ) {
          callback.current(message.data)
        }
      })

      currentSocket.addEventListener('close', (event) => {
        if (stopped) return

        const action = actionForClose(event.code)
        if (action === 'sign-in' && !tokenRenewed) {
          // The token may have run out while the tab slept: refresh it once
          // and reconnect before sending the lecturer to sign in.
          tokenRenewed = true
          void refreshAccessToken().then((token) => {
            if (stopped) return
            if (token) {
              connect()
              return
            }
            stopped = true
            clearAccessToken()
            window.location.assign('/login')
          })
          return
        }
        if (action === 'sign-in') {
          stopped = true
          clearAccessToken()
          window.location.assign('/login')
          return
        }
        if (action === 'stop') {
          stopped = true
          setStatus('unavailable')
          return
        }

        setStatus('disconnected')
        const delay = Math.min(1000 * 2 ** retryCount, 10_000)
        retryCount += 1
        retryTimer = window.setTimeout(connect, delay)
      })

      currentSocket.addEventListener('error', () => {
        currentSocket.close()
      })
    }

    connect()

    return () => {
      stopped = true
      if (retryTimer !== undefined) window.clearTimeout(retryTimer)
      socket?.close()
    }
  }, [enabled])

  return status
}
