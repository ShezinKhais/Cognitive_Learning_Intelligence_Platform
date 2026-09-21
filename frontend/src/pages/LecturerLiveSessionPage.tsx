import {
  useEffect,
  useState,
} from 'react'
import {
  Link,
  useParams,
} from 'react-router'

import { ApiError } from '../api'
import SignOutButton from '../components/SignOutButton'
import LiveAlertsPanel from '../features/live/LiveAlertsPanel'
import ManualQuestionTrigger from '../features/live/ManualQuestionTrigger'
import {
  endSession,
  pauseSession,
  resumeSession,
  startSession,
  type SessionLifecycleAction,
} from '../features/live/sessionActions'
import {
  useLiveSession,
  type LiveQuestion,
} from '../features/live/useLiveSession'

function connectionLabel(
  status: string,
): string {
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

function questionCycleLabel(
  status: string | undefined,
  paused: boolean | undefined,
): string {
  if (!status) {
    return 'Waiting...'
  }

  if (status === 'prepared') {
    return 'Not started'
  }

  if (status === 'active') {
    return paused
      ? 'Paused'
      : 'Running'
  }

  return 'Stopped'
}

function secondsUntilClose(
  question: LiveQuestion | null,
): number {
  if (!question) {
    return 0
  }

  const closesAt =
    Date.parse(question.closes_at)

  if (Number.isNaN(closesAt)) {
    return 0
  }

  return Math.max(
    0,
    Math.ceil(
      (closesAt - Date.now()) /
        1000,
    ),
  )
}

function closeReasonLabel(
  reason: string,
): string {
  if (reason === 'window_elapsed') {
    return 'Response window ended'
  }

  if (reason === 'lecturer_closed') {
    return 'Closed by lecturer'
  }

  if (reason === 'session_ended') {
    return 'Session ended'
  }

  return 'Question closed'
}

export default function LecturerLiveSessionPage() {
  const { sessionId } =
    useParams<{
      sessionId: string
    }>()

 const {
  connectionStatus,
  sessionState,
  activeQuestion,
  closedQuestion,
  alerts,
  sessionNotice,
  acknowledgeAlert,
} = useLiveSession(sessionId)
  const [
    actionInProgress,
    setActionInProgress,
  ] =
    useState<SessionLifecycleAction | null>(
      null,
    )

  const [
    actionError,
    setActionError,
  ] =
    useState<string | null>(
      null,
    )

  const [
    secondsRemaining,
    setSecondsRemaining,
  ] = useState(0)

  useEffect(() => {
    setSecondsRemaining(
      secondsUntilClose(
        activeQuestion,
      ),
    )

    if (!activeQuestion) {
      return
    }

    const timer =
      window.setInterval(
        () => {
          setSecondsRemaining(
            secondsUntilClose(
              activeQuestion,
            ),
          )
        },
        250,
      )

    return () => {
      window.clearInterval(timer)
    }
  }, [activeQuestion])

  async function handleSessionAction(
    action: SessionLifecycleAction,
  ) {
    if (!sessionId) {
      return
    }

    setActionError(null)
    setActionInProgress(action)

    try {
      if (action === 'start') {
        await startSession(
          sessionId,
        )
      } else if (
        action === 'pause'
      ) {
        await pauseSession(
          sessionId,
        )
      } else if (
        action === 'resume'
      ) {
        await resumeSession(
          sessionId,
        )
      } else {
        await endSession(
          sessionId,
        )
      }
    } catch (error) {
      if (
        error instanceof ApiError
      ) {
        setActionError(
          error.message,
        )
      } else {
        setActionError(
          'The session action could not be completed.',
        )
      }
    } finally {
      setActionInProgress(null)
    }
  }

  const isBusy =
    actionInProgress !== null

  const canStart =
    connectionStatus ===
      'connected' &&
    sessionState?.status ===
      'prepared' &&
    !isBusy

  const canPause =
    connectionStatus ===
      'connected' &&
    sessionState?.status ===
      'active' &&
    !sessionState.paused &&
    !isBusy

  const canResume =
    connectionStatus ===
      'connected' &&
    sessionState?.status ===
      'active' &&
    sessionState.paused &&
    !isBusy

  const canEnd =
    connectionStatus ===
      'connected' &&
    (
      sessionState?.status ===
        'prepared' ||
      sessionState?.status ===
        'active'
    ) &&
    !isBusy

  const canTriggerQuestion =
    connectionStatus ===
      'connected' &&
    sessionState?.status ===
      'active' &&
    !sessionState.paused &&
    activeQuestion === null

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
                {sessionId ??
                  'Unavailable'}
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
                {questionCycleLabel(
                  sessionState?.status,
                  sessionState?.paused,
                )}
              </p>
            </div>

            {actionError && (
              <div
                role="alert"
                className="mt-4 rounded-md border border-destructive/40 bg-destructive/10 px-4 py-3 text-sm text-destructive"
              >
                {actionError}
              </div>
            )}

            <div className="mt-5 flex flex-wrap gap-3">
              {sessionState?.status ===
                'prepared' && (
                <button
                  type="button"
                  disabled={
                    !canStart
                  }
                  onClick={() =>
                    void handleSessionAction(
                      'start',
                    )
                  }
                  className="rounded-md bg-primary px-4 py-2 text-sm font-medium text-primary-foreground disabled:cursor-not-allowed disabled:opacity-50"
                >
                  {actionInProgress ===
                  'start'
                    ? 'Starting...'
                    : 'Start Session'}
                </button>
              )}

              {sessionState?.status ===
                'active' &&
                !sessionState.paused && (
                  <button
                    type="button"
                    disabled={
                      !canPause
                    }
                    onClick={() =>
                      void handleSessionAction(
                        'pause',
                      )
                    }
                    className="rounded-md border border-border px-4 py-2 text-sm font-medium disabled:cursor-not-allowed disabled:opacity-50"
                  >
                    {actionInProgress ===
                    'pause'
                      ? 'Pausing...'
                      : 'Pause Session'}
                  </button>
                )}

              {sessionState?.status ===
                'active' &&
                sessionState.paused && (
                  <button
                    type="button"
                    disabled={
                      !canResume
                    }
                    onClick={() =>
                      void handleSessionAction(
                        'resume',
                      )
                    }
                    className="rounded-md bg-primary px-4 py-2 text-sm font-medium text-primary-foreground disabled:cursor-not-allowed disabled:opacity-50"
                  >
                    {actionInProgress ===
                    'resume'
                      ? 'Resuming...'
                      : 'Resume Session'}
                  </button>
                )}

              {(sessionState?.status ===
                'prepared' ||
                sessionState?.status ===
                  'active') && (
                <button
                  type="button"
                  disabled={
                    !canEnd
                  }
                  onClick={() =>
                    void handleSessionAction(
                      'end',
                    )
                  }
                  className="rounded-md border border-border px-4 py-2 text-sm font-medium disabled:cursor-not-allowed disabled:opacity-50"
                >
                  {actionInProgress ===
                  'end'
                    ? 'Ending...'
                    : 'End Session'}
                </button>
              )}

              {(sessionState?.status ===
                'ended' ||
                sessionState?.status ===
                  'cancelled') && (
                <p className="text-sm text-muted-foreground">
                  This session is no
                  longer active.
                </p>
              )}
            </div>
          </section>

          <section className="rounded-xl border border-border bg-card p-6">
            <h2 className="text-lg font-semibold">
              Participants
            </h2>

            <p className="mt-2 text-sm text-muted-foreground">
              {sessionState?.status === 'prepared'
                ? 'Connected and waiting for the session to start'
                : sessionState?.status === 'active'
                  ? 'Currently connected students'
                  : sessionState?.status === 'ended'
                    ? 'Session ended'
                    : sessionState?.status === 'cancelled'
                      ? 'Session cancelled'
                      : 'Waiting for session state'}
            </p>

            <p className="mt-5 text-3xl font-semibold">
              {sessionState?.status === 'ended' ||
              sessionState?.status === 'cancelled'
                ? 0
                : (sessionState?.participant_count ?? '—')}
            </p>
          </section>

          <section className="rounded-xl border border-border bg-card p-6 lg:col-span-2">
            <div className="flex flex-wrap items-start justify-between gap-4">
              <div>
                <h2 className="text-lg font-semibold">
                  Checkpoint Monitor
                </h2>

                <p className="mt-1 text-sm text-muted-foreground">
                  Questions delivered:{' '}
                  {sessionState?.questions_delivered ??
                    0}
                </p>
              </div>

              {activeQuestion && (
                <div
                  aria-live="polite"
                  className="rounded-md border border-border px-4 py-2 text-center"
                >
                  <p className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
                    Response window
                  </p>

                  <p className="mt-1 text-2xl font-semibold">
                    {secondsRemaining}s
                  </p>
                </div>
              )}
            </div>

            {activeQuestion ? (
              <div className="mt-6 rounded-xl border border-border bg-muted/30 p-5">
                <div className="flex flex-wrap items-start justify-between gap-4">
                  <div>
                    <p className="text-xs font-semibold uppercase tracking-wide text-info">
                      Checkpoint in progress
                    </p>

                    <p className="mt-2 text-lg font-semibold">
                      Question{' '}
                      {sessionState?.questions_delivered ?? 1}
                    </p>

                    <p className="mt-1 text-sm text-muted-foreground">
                      This checkpoint is currently open for connected students.
                    </p>
                  </div>

                  {activeQuestion.source_slide !== null && (
                    <span className="rounded-full bg-background px-3 py-1 text-xs font-medium text-muted-foreground">
                      Source slide {activeQuestion.source_slide}
                    </span>
                  )}
                </div>

                <details className="mt-5 rounded-lg border border-border bg-background">
                  <summary className="cursor-pointer px-4 py-3 text-sm font-medium">
                    View question
                  </summary>

                  <div className="border-t border-border px-4 py-4">
                    <p className="font-medium">
                      {activeQuestion.prompt}
                    </p>

                    {activeQuestion.options &&
                      activeQuestion.options.length > 0 && (
                        <div className="mt-4 grid gap-2 sm:grid-cols-2">
                          {activeQuestion.options.map(
                            (option, index) => (
                              <div
                                key={`${index}-${option}`}
                                className="rounded-md border border-border p-3 text-sm"
                              >
                                <span className="mr-2 font-semibold">
                                  {String.fromCharCode(65 + index)}.
                                </span>

                                {option}
                              </div>
                            ),
                          )}
                        </div>
                      )}

                    <p className="mt-4 text-xs text-muted-foreground">
                      Response window:{' '}
                      {activeQuestion.window_seconds}s
                    </p>
                  </div>
                </details>
              </div>
            ) : closedQuestion ? (
              <div className="mt-6 rounded-md border border-border p-5">
                <p className="font-medium">
                  {closeReasonLabel(
                    closedQuestion.reason,
                  )}
                </p>

                <p className="mt-2 text-sm text-muted-foreground">
                  Responses received:{' '}
                  {
                    closedQuestion.respondents
                  }{' '}
                  of{' '}
                  {
                    closedQuestion.eligible
                  }{' '}
                  eligible students.
                </p>
              </div>
            ) : (
              <p className="mt-6 text-sm text-muted-foreground">
                No active question.
              </p>
            )}

            <ManualQuestionTrigger
              sessionId={sessionId}
              enabled={
                canTriggerQuestion
              }
            />
          </section>

          <section className="rounded-xl border border-border bg-card p-6">
            <h2 className="text-lg font-semibold">
              Live Results
            </h2>

            <p className="mt-2 text-sm text-muted-foreground">
              Detailed response results
              will appear when response
              persistence is available.
            </p>

            {closedQuestion && (
              <div className="mt-5">
                <p className="text-3xl font-semibold">
                  {
                    closedQuestion.respondents
                  }
                  /
                  {
                    closedQuestion.eligible
                  }
                </p>

                <p className="mt-1 text-sm text-muted-foreground">
                  students responded
                </p>
              </div>
            )}
          </section>

          <LiveAlertsPanel
            alerts={alerts}
            sessionNotice={sessionNotice}
            onAcknowledge={
              acknowledgeAlert
            }
          />
        </div>
      </div>
    </main>
  )
}
