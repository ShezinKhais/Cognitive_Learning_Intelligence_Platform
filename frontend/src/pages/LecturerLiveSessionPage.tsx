import { Link, useParams } from 'react-router'

import SignOutButton from '../components/SignOutButton'
import { useLiveSession } from '../features/live/useLiveSession'

function connectionLabel(status: string): string {
  if (status === 'connected') {
    return 'Connected'
  }

  if (status === 'connecting') {
    return 'Connecting...'
  }

  if (status === 'unavailable') {
    return 'Unavailable'
  }

  return 'Disconnected'
}

function sessionLabel(
  status: string | undefined,
): string {
  if (!status) {
    return 'Waiting...'
  }

  return (
    status.charAt(0).toUpperCase() +
    status.slice(1)
  )
}

export default function LecturerLiveSessionPage() {
  const { sessionId } =
    useParams<{ sessionId: string }>()

  const {
    connectionStatus,
    sessionState,
  } = useLiveSession(sessionId)

  return (
    <main className="min-h-screen bg-background">
      <header className="border-b border-border bg-card">
        <div className="mx-auto flex max-w-7xl items-center justify-between gap-4 px-5 py-4 sm:px-8">
          <div>
            <p className="text-xs font-semibold uppercase tracking-[0.18em] text-muted-foreground">
              C.L.I.P lecturer workspace
            </p>

            <h1 className="mt-1 text-xl font-bold text-card-foreground">
              Live Session
            </h1>
          </div>

          <div className="flex items-center gap-3">
            <Link
              to="/lecturer/materials"
              className="rounded-md border border-border px-4 py-2 text-sm font-medium hover:bg-muted"
            >
              Materials
            </Link>

            <SignOutButton />
          </div>
        </div>
      </header>

      <div className="mx-auto max-w-7xl px-5 py-8 sm:px-8">
        <section className="rounded-xl border border-border bg-card p-6">
          <div className="flex flex-wrap items-start justify-between gap-4">
            <div>
              <p className="text-sm font-medium text-muted-foreground">
                Session
              </p>

              <h2 className="mt-1 text-2xl font-semibold">
                Lecturer Live Panel
              </h2>

              <p className="mt-2 text-sm text-muted-foreground">
                Session ID:{' '}
                {sessionId ?? 'Unavailable'}
              </p>
            </div>

            <div className="rounded-full border border-border px-3 py-1 text-sm">
              {connectionLabel(
                connectionStatus,
              )}
            </div>
          </div>
        </section>

        <div className="mt-6 grid gap-6 lg:grid-cols-2">
          <section className="rounded-xl border border-border bg-card p-6">
            <h2 className="text-lg font-semibold">
              Session Controls
            </h2>

            <div className="mt-4">
              <p className="text-sm text-muted-foreground">
                Session status
              </p>

              <p className="mt-1 text-2xl font-semibold">
                {sessionLabel(
                  sessionState?.status,
                )}
              </p>
            </div>

            <div className="mt-4">
              <p className="text-sm text-muted-foreground">
                Question cycle
              </p>

              <p className="mt-1 font-medium">
                {!sessionState
  ? 'Waiting...'
  : sessionState.status === 'prepared'
    ? 'Not started'
    : sessionState.status === 'active'
      ? sessionState.paused
        ? 'Paused'
        : 'Running'
      : 'Stopped'}
              </p>
            </div>

            <div className="mt-5 flex flex-wrap gap-3">
              <button
                type="button"
                disabled
                className="rounded-md bg-primary px-4 py-2 text-sm font-medium text-primary-foreground disabled:cursor-not-allowed disabled:opacity-50"
              >
                Start Session
              </button>

              <button
                type="button"
                disabled
                className="rounded-md border border-border px-4 py-2 text-sm font-medium disabled:cursor-not-allowed disabled:opacity-50"
              >
                Pause Session
              </button>

              <button
                type="button"
                disabled
                className="rounded-md border border-border px-4 py-2 text-sm font-medium disabled:cursor-not-allowed disabled:opacity-50"
              >
                End Session
              </button>
            </div>
          </section>

          <section className="rounded-xl border border-border bg-card p-6">
            <h2 className="text-lg font-semibold">
              Participants
            </h2>

            <p className="mt-2 text-sm text-muted-foreground">
              Currently connected students
            </p>

            <p className="mt-5 text-3xl font-semibold">
              {sessionState?.participant_count ??
                '—'}
            </p>
          </section>

          <section className="rounded-xl border border-border bg-card p-6">
            <h2 className="text-lg font-semibold">
              Current Question
            </h2>

            {sessionState?.active_question_id ? (
              <>
                <p className="mt-2 text-sm text-muted-foreground">
                  Active question
                </p>

                <p className="mt-2 break-all text-sm font-medium">
                  {
                    sessionState.active_question_id
                  }
                </p>
              </>
            ) : (
              <p className="mt-2 text-sm text-muted-foreground">
                No active question.
              </p>
            )}

            <p className="mt-4 text-sm text-muted-foreground">
              Questions delivered:{' '}
              {sessionState?.questions_delivered ??
                0}
            </p>

            <button
              type="button"
              disabled
              className="mt-5 rounded-md border border-border px-4 py-2 text-sm font-medium disabled:cursor-not-allowed disabled:opacity-50"
            >
              Trigger Question
            </button>
          </section>

          <section className="rounded-xl border border-border bg-card p-6">
            <h2 className="text-lg font-semibold">
              Live Results
            </h2>

            <p className="mt-2 text-sm text-muted-foreground">
              Results will appear when response
              data becomes available.
            </p>
          </section>

          <section className="rounded-xl border border-border bg-card p-6 lg:col-span-2">
            <h2 className="text-lg font-semibold">
              Alerts
            </h2>

            <p className="mt-2 text-sm text-muted-foreground">
              No live alerts.
            </p>
          </section>
        </div>
      </div>
    </main>
  )
}