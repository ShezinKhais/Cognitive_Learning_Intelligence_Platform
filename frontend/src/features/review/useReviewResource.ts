import { useEffect, useState } from 'react'
import { ApiError, apiAuthenticatedRequest } from '../../api'
import { reviewError } from './reviewDisplay'

/** No local/session storage. Abort on navigation; never display another request's result. */
export function useReviewResource<T>(path: string) {
  const [attempt, setAttempt] = useState(0)
  const [state, setState] = useState<{
    key: string
    attempt: number
    data?: T
    error?: string
  }>({ key: '', attempt: -1 })
  useEffect(() => {
    const controller = new AbortController()
    apiAuthenticatedRequest<T>(path, {
      signal: controller.signal,
      cache: 'no-store',
    }).then(
      (data) => {
        if (!controller.signal.aborted) setState({ key: path, attempt, data })
      },
      (error) => {
        if (!controller.signal.aborted)
          setState({
            key: path,
            attempt,
            error: reviewError(
              error instanceof ApiError ? error.status : undefined,
            ),
          })
      },
    )
    return () => controller.abort()
  }, [path, attempt])
  const current = state.key === path && state.attempt === attempt
  return {
    data: current ? state.data : undefined,
    error: current ? state.error : undefined,
    retry: () => setAttempt((value) => value + 1),
  }
}
