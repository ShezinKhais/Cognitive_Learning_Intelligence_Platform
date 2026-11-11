import { useCallback, useEffect, useRef, useState } from 'react'
import { apiAuthenticatedRequest } from '../../api'

type Policy = 'checking' | 'allowed' | 'blocked' | 'unavailable'

/** A capture restriction is separate from consent and from scoring exemptions. */
export function useCameraPolicy(stopCamera: () => void) {
  const [policy, setPolicy] = useState<Policy>('checking')
  const current = useRef<Policy>('checking')
  const sequence = useRef(0)
  const pending = useRef<AbortController | null>(null)
  const check = useCallback(async () => {
    const request = ++sequence.current
    pending.current?.abort()
    const controller = new AbortController()
    pending.current = controller
    const timeout = window.setTimeout(() => controller.abort(), 5000)
    try {
      const result = await apiAuthenticatedRequest<{ camera_allowed: boolean }>('/me/consideration/policy', { cache: 'no-store', signal: controller.signal })
      if (request !== sequence.current) return false
      // A malformed or unavailable policy never grants camera access.
      const allowed = result.camera_allowed === true
      current.current = allowed ? 'allowed' : 'blocked'
      setPolicy(current.current)
      if (!allowed) stopCamera()
      return allowed
    } catch {
      if (request === sequence.current) {
        current.current = 'unavailable'
        setPolicy('unavailable')
        stopCamera()
      }
      return false
    } finally {
      window.clearTimeout(timeout)
      if (pending.current === controller) pending.current = null
    }
  }, [stopCamera])
  useEffect(() => () => { ++sequence.current; pending.current?.abort() }, [])
  return { policy, current, check }
}
