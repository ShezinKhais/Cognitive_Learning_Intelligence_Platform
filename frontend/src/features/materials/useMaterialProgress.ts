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
  data?: unknown
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
): ProgressConnectionStatus {
  const callback = useRef(onProgress)
  const [status, setStatus] = useState<ProgressConnectionStatus>('connecting')

  useEffect(() => {
    callback.current = onProgress
  }, [onProgress])

  useEffect(() => {
    const token = getAccessToken()

    if (!token) {
      setStatus('disconnected')
      return
    }

    let socket: WebSocket | null = null
    let retryTimer: number | undefined
    let stopped = false
    let retryCount = 0

    function connect() {
      if (stopped) return

      setStatus('connecting')
      const currentSocket = new WebSocket(progressSocketUrl())
      socket = currentSocket

      currentSocket.addEventListener('open', () => {
        currentSocket.send(JSON.stringify({
          type: 'auth',
          data: { token },
        }))
      })

      currentSocket.addEventListener('message', (event) => {
        let message: ServerEvent

        try {
          message = JSON.parse(String(event.data)) as ServerEvent
        } catch {
          return
        }

        if (message.type === 'ready') {
          retryCount = 0
          setStatus('connected')
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
  }, [])

  return status
}
