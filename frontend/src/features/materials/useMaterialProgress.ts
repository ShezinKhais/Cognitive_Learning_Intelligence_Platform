import {
  useEffect,
  useRef,
  useState,
} from 'react'

import {
  clearAccessToken,
  getAccessToken,
} from '../../api'
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
    let connectedOnce = false

    function connect() {
      if (stopped) return

      setStatus('connecting')
      const currentSocket = new WebSocket(progressSocketUrl())
      socket = currentSocket

      currentSocket.addEventListener('open', () => {
        const data = {
          token: accessToken,
          // Zero matters when the socket connects after a very fast upload:
          // it asks the server to replay progress emitted before READY.
          last_seq: lastSeq,
        }

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

        if (event.code === 4001) {
          stopped = true
          clearAccessToken()
          window.location.assign('/login')
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
