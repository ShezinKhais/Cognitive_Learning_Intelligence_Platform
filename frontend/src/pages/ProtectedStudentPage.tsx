import {
  Navigate,
  useLocation,
} from 'react-router'

import { useStudentApp } from '../features/student/StudentAppContext'
import StudentHomePage from './StudentHomePage'

export default function ProtectedStudentPage() {
  const location = useLocation()

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
          from: location.pathname,
        }}
      />
    )
  }

  if (currentUser.role !== 'student') {
    return (
      <Navigate
        to="/access-denied"
        replace
      />
    )
  }

  return <StudentHomePage />
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
