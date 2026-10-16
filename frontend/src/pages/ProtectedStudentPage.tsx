import {
  Navigate,
  Outlet,
  useLocation,
} from 'react-router'

import AppShell from '../components/shell/AppShell'
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
  } = useStudentApp()

  if (authStatus === 'checking') {
    return (
      <StatusPanel
        title="Loading student workspace"
        message="Checking your account and permissions..."
      />
    )
  }

  if (authStatus === 'error') {
    return (
      <StatusPanel
        title="Could not verify your account"
        message={
          error ??
          'An unexpected authentication error occurred.'
        }
        isError
      />
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
      <Outlet />
    </AppShell>
  ) : (
    <Outlet />
  )
}

function StatusPanel({
  title,
  message,
  isError = false,
}: {
  title: string
  message: string
  isError?: boolean
}) {
  return (
    <main className="min-h-screen grid place-items-center p-8">
      <div
        role={isError ? 'alert' : 'status'}
        className="w-full max-w-md rounded-xl border border-border bg-card p-6"
      >
        <h1
          className={
            isError
              ? 'text-xl font-semibold text-critical'
              : 'text-xl font-semibold'
          }
        >
          {title}
        </h1>

        <p className="mt-2 text-sm text-muted-foreground">
          {message}
        </p>
      </div>
    </main>
  )
}
