import { useCallback, useEffect, useRef, useState } from 'react'

export type SensorStatus = 'off' | 'starting' | 'on' | 'unavailable'
export interface SensorSamples<T> { values: T[]; latestAt: number }
type Starter<T> = (signal: AbortSignal, report: (value: T) => void, failed: () => void) => Promise<void>

/** One lifecycle for both local devices: permission, samples and teardown. */
export function useLocalSensor<T>(
  label: string,
  starter: Starter<T>,
  initial: T,
  maxSamples: number,
  onFailure: (message: string) => void,
) {
  const [status, setStatus] = useState<SensorStatus>('off')
  const [latest, setLatest] = useState<T>(initial)
  const controller = useRef<AbortController | null>(null)
  const values = useRef<T[]>([])
  const latestAt = useRef(0)
  const activeAt = useRef(0)
  const failure = useRef(onFailure)
  failure.current = onFailure

  const stop = useCallback(() => {
    controller.current?.abort()
    controller.current = null
    values.current = []
    latestAt.current = 0
    activeAt.current = 0
    setLatest(initial)
    setStatus('off')
  }, [initial])

  const start = useCallback(async () => {
    if (controller.current || document.hidden) return
    const current = new AbortController()
    controller.current = current
    const isCurrent = () => controller.current === current && !current.signal.aborted
    const failed = () => {
      if (!isCurrent()) return
      stop()
      setStatus('unavailable')
      failure.current(`${label} unavailable. Check browser permission or device use in another app. You can continue without it.`)
    }
    setStatus('starting')
    try {
      if (!window.isSecureContext || !navigator.mediaDevices?.getUserMedia) throw new Error('Unavailable')
      await starter(current.signal, value => {
        if (!isCurrent()) return
        if (value !== null) {
          values.current.push(value)
          values.current = values.current.slice(-maxSamples)
        }
        latestAt.current = value === null ? 0 : performance.now()
        setLatest(previous => Object.is(previous, value) ? previous : value)
      }, failed)
      if (isCurrent()) {
        activeAt.current = performance.now()
        setStatus('on')
      }
    } catch {
      failed()
    }
  }, [label, maxSamples, starter, stop])

  const drain = useCallback((): SensorSamples<T> => {
    const drained = { values: values.current, latestAt: latestAt.current }
    values.current = []
    return drained
  }, [])
  const isActive = useCallback(() => activeAt.current > 0, [])
  const isStartingOrActive = useCallback(() => controller.current !== null, [])
  const startedAt = useCallback(() => activeAt.current, [])

  useEffect(() => () => { controller.current?.abort(); controller.current = null }, [])

  return { status, latest, start, stop, drain, isActive, isStartingOrActive, startedAt }
}
