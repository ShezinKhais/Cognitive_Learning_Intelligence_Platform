import { useStudentApp } from '../features/student/StudentAppContext'
import type { StudentSession } from '../features/student/types'

export default function StudentHomePage() {
  const {
    authStatus,
    currentUser,
    sessions,
    selectedSessionId,
    error,
    selectSession,
  } = useStudentApp()

  if (authStatus === 'checking') {
    return (
      <MessagePanel
        title="Loading student workspace"
        message="Checking your account and sessions..."
      />
    )
  }

  if (authStatus === 'error') {
    return (
      <MessagePanel
        title="Could not load the student workspace"
        message={error ?? 'An unexpected error occurred.'}
        isError
      />
    )
  }

  if (
    authStatus === 'unauthenticated' ||
    !currentUser
  ) {
    return (
      <MessagePanel
        title="Sign-in required"
        message="Please sign in before opening the student workspace."
      />
    )
  }

  if (currentUser.role !== 'student') {
    return (
      <MessagePanel
        title="Student access required"
        message="This workspace is only available to student accounts."
        isError
      />
    )
  }

  return (
    <main className="min-h-screen bg-background px-6 py-10">
      <section className="mx-auto max-w-4xl">
        <header className="flex flex-wrap items-start justify-between gap-4">
          <div>
            <p className="text-sm font-medium text-info">
              Student workspace
            </p>

            <h1 className="mt-2 text-3xl font-bold">
              Welcome, {currentUser.full_name}
            </h1>

            <p className="mt-2 text-muted-foreground">
              View your available learning sessions.
            </p>
          </div>

          <div className="rounded-xl border border-border bg-card px-4 py-3 text-sm">
            <p className="font-medium">{currentUser.email}</p>

            <p className="mt-1 text-muted-foreground">
              Authenticated student
            </p>
          </div>
        </header>

        <div
          role="status"
          className="mt-8 rounded-xl border border-info/20 bg-card p-4 text-sm"
        >
          <span className="font-semibold text-info">
            Mock data:
          </span>{' '}
          The Phase 3 session endpoints are not implemented yet.
        </div>

        <section
          className="mt-8"
          aria-labelledby="sessions-heading"
        >
          <h2
            id="sessions-heading"
            className="text-xl font-semibold"
          >
            Available sessions
          </h2>

          {sessions.length === 0 ? (
            <div className="mt-4 rounded-xl border border-border bg-card p-6">
              <p className="font-medium">
                No sessions available
              </p>

              <p className="mt-2 text-sm text-muted-foreground">
                Sessions assigned to you will appear here.
              </p>
            </div>
          ) : (
            <ul className="mt-4 grid gap-4">
              {sessions.map((session) => (
                <li key={session.id}>
                  <SessionCard
                    session={session}
                    selected={
                      selectedSessionId === session.id
                    }
                    onSelect={() =>
                      selectSession(session.id)
                    }
                  />
                </li>
              ))}
            </ul>
          )}
        </section>
      </section>
    </main>
  )
}

function SessionCard({
  session,
  selected,
  onSelect,
}: {
  session: StudentSession
  selected: boolean
  onSelect: () => void
}) {
  return (
    <article className="rounded-xl border border-border bg-card p-6">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <span className="font-semibold text-info">
          {session.course_code}
        </span>

        <span className="rounded-full bg-secondary px-3 py-1 text-xs font-medium">
          {session.status}
        </span>
      </div>

      <h3 className="mt-3 text-lg font-semibold">
        {session.title}
      </h3>

      <p className="mt-2 text-sm text-muted-foreground">
        {formatStart(session.starts_at)}
      </p>

      <button
        type="button"
        aria-pressed={selected}
        onClick={onSelect}
        className="mt-5 rounded-lg bg-primary px-4 py-2 text-sm font-medium text-primary-foreground"
      >
        {selected ? 'Session selected' : 'Select session'}
      </button>
    </article>
  )
}

function MessagePanel({
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

function formatStart(
  value: string | null | undefined,
): string {
  if (!value) {
    return 'Start time not scheduled'
  }

  const startTime = new Date(value)

  if (Number.isNaN(startTime.getTime())) {
    return 'Start time unavailable'
  }

  return new Intl.DateTimeFormat('en-AE', {
    year: 'numeric',
    month: 'short',
    day: 'numeric',
    hour: 'numeric',
    minute: '2-digit',
    timeZone: 'Asia/Dubai',
    timeZoneName: 'short',
  }).format(startTime)
}
