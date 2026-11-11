import { useCallback, useEffect, useRef, useState } from 'react'
import { apiAuthenticatedRequest } from '../../api'

type Policy = 'checking' | 'allowed' | 'blocked' | 'unavailable'

/** A capture restriction is separate from consent and from scoring exemptions. */
export function useCameraPolicy(stopCamera: () => void) {
  const [policy, setPolicy] = useState<Policy>('checking')
  const current = useRef<Policy>('checking')
  const pending = useRef<{ controller: AbortController; result: Promise<boolean> } | null>(null)
  const check = useCallback(() => {
    if (pending.current) return pending.current.result
    const controller = new AbortController()
    const timeout = window.setTimeout(() => controller.abort(), 5000)
    const isCurrent = () => pending.current?.controller === controller
    const result = apiAuthenticatedRequest<{ camera_allowed: boolean }>(
      '/me/consideration/policy', { cache: 'no-store', signal: controller.signal },
    ).then(response => {
      if (!isCurrent()) return false
      controller.signal.throwIfAborted()
      const allowed = response.camera_allowed === true
      current.current = allowed ? 'allowed' : 'blocked'
      setPolicy(current.current)
      if (!allowed) stopCamera()
      return allowed
    }).catch(() => {
      if (isCurrent()) {
        current.current = 'unavailable'
        setPolicy('unavailable')
        stopCamera()
      }
      return false
    }).finally(() => {
      window.clearTimeout(timeout)
      if (isCurrent()) pending.current = null
    })
    pending.current = { controller, result }
    return result
  }, [stopCamera])
  useEffect(() => () => {
    const request = pending.current
    pending.current = null
    request?.controller.abort()
  }, [])
  return { policy, current, check }
}
