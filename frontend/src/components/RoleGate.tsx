import { useEffect, useState, type ReactNode } from 'react'
import { Navigate, useLocation } from 'react-router'

import { ApiError, getAccessToken, getCurrentUser, type CurrentUser, type Role } from '../api'
import { hasRequiredConsent } from '../authRouting'

type State =
  | { status: 'loading' }
  | { status: 'ready'; user: CurrentUser }
  | { status: 'unauthenticated' }
  | { status: 'error'; message: string }

type Props = {
  allow: readonly Role[]
  children: (user: CurrentUser) => ReactNode
}

/**
 * Renders its children only for a signed-in user in one of the allowed roles
 * who has accepted the terms, and sends everyone else where they need to go:
 * sign-in (remembering the page), access denied, or the consent page.
 *
 * Used as a layout route, so the check runs before a guarded page mounts and
 * none of its markup renders for someone who typed the URL.
 */
export default function RoleGate({ allow, children }: Props) {
  const location = useLocation()
  const [state, setState] = useState<State>({ status: 'loading' })

  useEffect(() => {
    if (!getAccessToken()) {
      setState({ status: 'unauthenticated' })
      return
    }

    let cancelled = false
    getCurrentUser()
      .then((user) => {
        if (!cancelled) setState({ status: 'ready', user })
      })
      .catch((caught: unknown) => {
        if (cancelled) return
        if (caught instanceof ApiError && caught.status === 401) {
          setState({ status: 'unauthenticated' })
        } else {
          setState({
            status: 'error',
            message: caught instanceof Error ? caught.message : 'Could not verify access.',
          })
        }
      })

    return () => {
      cancelled = true
    }
  }, [])

  if (state.status === 'loading') {
    return <main className="min-h-screen grid place-items-center">Checking access...</main>
  }
  if (state.status === 'unauthenticated') {
    return <Navigate to="/login" replace state={{ from: location.pathname }} />
  }
  if (state.status === 'error') {
    return <main className="p-8 text-critical" role="alert">{state.message}</main>
  }
  if (!allow.includes(state.user.role)) {
    return <Navigate to="/access-denied" replace />
  }
  if (!hasRequiredConsent(state.user)) {
    return <Navigate to="/consent" replace state={{ from: location.pathname }} />
  }
  return <>{children(state.user)}</>
}
