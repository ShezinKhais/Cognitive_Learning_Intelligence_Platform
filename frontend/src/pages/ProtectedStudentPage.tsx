import {
  Navigate,
  Outlet,
  useLocation,
} from 'react-router'

import PageLoader from '../components/brand/PageLoader'
import AppShell from '../components/shell/AppShell'
import { PageOutlet } from '../components/shell/ShellOutlet'
import { ProblemState } from '../components/ui/ProblemState'
import { problemArt } from '../components/ui/problem'
import { useStudentApp } from '../features/student/StudentAppContext'
import { accessFor } from '../authRouting'

/** `withShell` frames the pages in the side menu; the Teams meeting panel
 * uses this guard too, and has no room for one. */
export default function ProtectedStudentPage({ withShell = false }: { withShell?: boolean }) {
  const location = useLocation()
  const requestedPath = `${location.pathname}${location.search}`

  const {
    authStatus,
    currentUser,
    error,
    cause,
  } = useStudentApp()

  if (authStatus === 'checking') {
    return <PageLoader />
  }

  if (authStatus === 'error') {
    return (
      <ProblemState fullScreen art={problemArt(cause)} title="C.L.I.P could not check your account">
        {error ?? 'An unexpected authentication error occurred.'}
      </ProblemState>
    )
  }

  if (
    authStatus === 'unauthenticated' ||
    !currentUser
  ) {
    return (
      <Navigate
        to="/login"
        replace
        state={{
          from: requestedPath,
        }}
      />
    )
  }

  // The same rule RoleGate applies. The student workspace keeps its own gate
  // because StudentAppProvider already loads the user for the whole page.
  const access = accessFor(currentUser, ['student'])

  if (access === 'wrong-role') {
    return (
      <Navigate
        to="/access-denied"
        replace
      />
    )
  }

  if (access === 'needs-consent') {
    return (
      <Navigate
        to="/consent"
        replace
        state={{ from: requestedPath }}
      />
    )
  }

  return withShell ? (
    <AppShell user={currentUser}>
      <PageOutlet />
    </AppShell>
  ) : (
    <Outlet />
  )
}
