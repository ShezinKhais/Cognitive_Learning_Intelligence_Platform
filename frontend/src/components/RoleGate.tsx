import { useEffect, useState, type ReactNode } from 'react'
import { Navigate, useLocation } from 'react-router'

import { ApiError, getCurrentUser, restoreSession, type CurrentUser, type Role } from '../api'
import { accessFor } from '../authRouting'
import PageLoader from './brand/PageLoader'
import { problemArt } from './ui/problem'
import { ProblemState } from './ui/ProblemState'

type State =
  | { status: 'loading' }
  | { status: 'ready'; user: CurrentUser }
  | { status: 'unauthenticated' }
  | { status: 'error'; message: string; cause: unknown }

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
  const requestedPath = `${location.pathname}${location.search}`
  const [state, setState] = useState<State>({ status: 'loading' })

  useEffect(() => {
    let cancelled = false
    // A reload or a new tab has no token in memory yet; the refresh cookie
    // gets one, or says nobody is signed in.
    restoreSession()
      .then((token) => {
        if (!token) {
          if (!cancelled) setState({ status: 'unauthenticated' })
          return
        }
        return getCurrentUser().then((user) => {
          if (!cancelled) setState({ status: 'ready', user })
        })
      })
      .catch((caught: unknown) => {
        if (cancelled) return
        if (caught instanceof ApiError && caught.status === 401) {
          setState({ status: 'unauthenticated' })
        } else {
          setState({
            status: 'error',
            message: caught instanceof Error ? caught.message : 'Could not verify access.',
            cause: caught,
          })
        }
      })

    return () => {
      cancelled = true
    }
  }, [])

  if (state.status === 'loading') {
    return <PageLoader />
  }
  if (state.status === 'unauthenticated') {
    return <Navigate to="/login" replace state={{ from: requestedPath }} />
  }
  if (state.status === 'error') {
    return (
      <ProblemState fullScreen art={problemArt(state.cause)} title="C.L.I.P could not check your account">
        {state.message}
      </ProblemState>
    )
  }
  const access = accessFor(state.user, allow)
  if (access === 'wrong-role') {
    return <Navigate to="/access-denied" replace />
  }
  if (access === 'needs-consent') {
    return <Navigate to="/consent" replace state={{ from: requestedPath }} />
  }
  return <>{children(state.user)}</>
}
