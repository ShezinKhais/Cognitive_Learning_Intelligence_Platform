import { useState } from 'react'
import { Link, useParams } from 'react-router'

import { ApiError } from '../api'
import SignOutButton from '../components/SignOutButton'
import {
  endSession,
  pauseSession,
  resumeSession,
  startSession,
  type SessionLifecycleAction,
} from '../features/live/sessionActions'
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

export default function LecturerLiveSessionPage() {
  const { sessionId } =
    useParams<{ sessionId: string }>()

  const {
    connectionStatus,
    sessionState,
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
  ] = useState<string | null>(null)

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
        await startSession(sessionId)
      } else if (action === 'pause') {
        await pauseSession(sessionId)
      } else if (action === 'resume') {
        await resumeSession(sessionId)
      } else {
        await endSession(sessionId)
      }
    } catch (error) {
      if (error instanceof ApiError) {
        setActionError(error.message)
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
    connectionStatus === 'connected' &&
    sessionState?.status === 'prepared' &&
    !isBusy

  const canPause =
    connectionStatus === 'connected' &&
    sessionState?.status === 'active' &&
    !sessionState.paused &&
    !isBusy

  const canResume =
    connectionStatus === 'connected' &&
    sessionState?.status === 'active' &&
    sessionState.paused &&
    !isBusy

  const canEnd =
    connectionStatus === 'connected' &&
    (
      sessionState?.status === 'prepared' ||
      sessionState?.status === 'active'
    ) &&
    !isBusy

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
                  disabled={!canStart}
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
                    disabled={!canPause}
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
                    disabled={!canResume}
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
                  disabled={!canEnd}
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
                  This session is no longer
                  active.
                </p>
              )}
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