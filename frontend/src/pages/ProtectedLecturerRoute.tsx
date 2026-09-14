import {
  useEffect,
  useState,
} from 'react'
import {
  Navigate,
  Outlet,
  useLocation,
} from 'react-router'

import {
  ApiError,
  getAccessToken,
  getCurrentUser,
  type CurrentUser,
} from '../api'

type State =
  | { status: 'loading' }
  | { status: 'ready'; user: CurrentUser }
  | { status: 'unauthenticated' }
  | { status: 'error'; message: string }

export default function ProtectedLecturerRoute() {
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
            message: caught instanceof Error
              ? caught.message
              : 'Could not verify access.',
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

  if (state.user.role !== 'lecturer' && state.user.role !== 'admin') {
    return <Navigate to="/access-denied" replace />
  }

  return <Outlet />
}
