import {
  useEffect,
  useState,
} from 'react'
import {
  Link,
  useParams,
} from 'react-router'

import { ApiError } from '../api'
import { buttonStyles } from '../components/ui/button'
import { PageHeader, Panel, Tag } from '../components/ui/primitives'
import LiveResults from '../features/live/LiveResults'
import ReadinessChecklist from '../features/live/ReadinessChecklist'
import RoomsPanel from '../features/live/RoomsPanel'
import { statusLabel, statusTone } from '../features/sessions/format'
import { getSession, type SessionSummary } from '../features/sessions/sessionsApi'
import LecturerAttentionPanel from '../features/attention/LecturerAttentionPanel'
import type {
  LecturerEngagement,
} from '../features/attention/lecturerAttention'
import {
  getSessionEngagement,
} from '../features/attention/lecturerAttentionApi'
import TopicRecoveryPanel from '../features/intelligence/TopicRecoveryPanel'
import type {
  TopicDifficulty,
} from '../features/intelligence/topicRecovery'
import {
  getSessionTopics,
} from '../features/intelligence/topicRecoveryApi'
import LiveAlertsPanel from '../features/live/LiveAlertsPanel'
import CheckpointMonitor from '../features/live/CheckpointMonitor'
import {
  endSession,
  getSessionReadiness,
  pauseSession,
  resumeSession,
  startSession,
  type SessionLifecycleAction,
  type SessionReadiness,
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
    return 'Connecting…'
  }

  if (status === 'unavailable') {
    return 'Live updates are not reaching this page'
  }

  return 'Reconnecting…'
}

function sessionLabel(
  status: string | undefined,
): string {
  if (!status) {
    return 'Waiting...'
  }

  const labels: Record<string, string> = {
    prepared: 'Not started',
    active: 'Live',
    ended: 'Ended',
    cancelled: 'Cancelled',
  }
  return labels[status] ?? status
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
    rooms,
    acknowledgeAlert,
  } = useLiveSession(sessionId)

  // The session's title and course, for the header. The socket carries its
  // live state; this is only what it is called.
  const [details, setDetails] = useState<SessionSummary | null>(null)
  useEffect(() => {
    if (!sessionId) return
    let cancelled = false
    getSession(sessionId).then((found) => !cancelled && setDetails(found), () => undefined)
    return () => {
      cancelled = true
    }
  }, [sessionId])

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

  const [
    readiness,
    setReadiness,
  ] =
    useState<SessionReadiness | null>(
      null,
    )

  const [
    readinessLoading,
    setReadinessLoading,
  ] = useState(false)

  const [
    readinessError,
    setReadinessError,
  ] =
    useState<string | null>(
      null,
    )

  const [
    topics,
    setTopics,
  ] =
    useState<TopicDifficulty[]>(
      [],
    )

  const [
    topicsLoading,
    setTopicsLoading,
  ] = useState(false)

  const [
    topicsError,
    setTopicsError,
  ] =
    useState<string | null>(
      null,
    )

  const [
    engagement,
    setEngagement,
  ] =
    useState<LecturerEngagement[]>(
      [],
    )

  const [
    engagementLoading,
    setEngagementLoading,
  ] = useState(false)

  const [
    engagementError,
    setEngagementError,
  ] =
    useState<string | null>(
      null,
    )

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

  useEffect(() => {
    if (
      !sessionId ||
      sessionState?.status !==
        'prepared'
    ) {
      setReadiness(null)
      setReadinessError(null)
      setReadinessLoading(false)
      return
    }

    let active = true

    async function loadReadiness() {
      if (!sessionId) {
        return
      }

      setReadinessLoading(true)
      setReadinessError(null)

      try {
        const result =
          await getSessionReadiness(
            sessionId,
          )

        if (!active) {
          return
        }

        setReadiness(result)
      } catch (error: unknown) {
        if (!active) {
          return
        }

        setReadiness(null)

        setReadinessError(
          error instanceof ApiError
            ? error.message
            : 'Session readiness could not be checked.',
        )
      } finally {
        if (active) {
          setReadinessLoading(false)
        }
      }
    }

    void loadReadiness()

    return () => {
      active = false
    }
  }, [
    sessionId,
    sessionState?.status,
  ])

  useEffect(() => {
    if (!sessionId) {
      setTopics([])
      setTopicsError(null)
      setTopicsLoading(false)
      return
    }

    const currentSessionId =
      sessionId

    let active = true

    async function loadTopics() {
      setTopicsLoading(true)
      setTopicsError(null)

      try {
        const result =
          await getSessionTopics(
            currentSessionId,
          )

        if (!active) {
          return
        }

        setTopics(result)
      } catch (error: unknown) {
        if (!active) {
          return
        }

        setTopics([])

        setTopicsError(
          error instanceof ApiError
            ? error.message
            : 'Topic recovery data could not be loaded.',
        )
      } finally {
        if (active) {
          setTopicsLoading(false)
        }
      }
    }

    void loadTopics()

    return () => {
      active = false
    }
  }, [
    sessionId,
    closedQuestion,
  ])

  useEffect(() => {
    if (
      !sessionId ||
      sessionState?.status !==
        'active'
    ) {
      setEngagement([])
      setEngagementError(null)
      setEngagementLoading(false)
      return
    }

    const currentSessionId =
      sessionId

    let active = true

    let refreshTimer:
      | number
      | undefined

    async function loadEngagement() {
      if (!active) {
        return
      }

      setEngagementLoading(true)

      try {
        const result =
          await getSessionEngagement(
            currentSessionId,
          )

        if (!active) {
          return
        }

        setEngagement(result)
        setEngagementError(null)
      } catch (error: unknown) {
        if (!active) {
          return
        }

        setEngagementError(
          error instanceof ApiError
            ? error.message
            : 'Attention and engagement indicators could not be loaded.',
        )
      } finally {
        if (active) {
          setEngagementLoading(false)

          refreshTimer =
            window.setTimeout(
              () => {
                void loadEngagement()
              },
              10_000,
            )
        }
      }
    }

    void loadEngagement()

    return () => {
      active = false

      if (
        refreshTimer !==
        undefined
      ) {
        window.clearTimeout(
          refreshTimer,
        )
      }
    }
  }, [
    sessionId,
    sessionState?.status,
  ])

  async function refreshReadiness() {
    if (!sessionId) {
      return
    }

    setReadinessLoading(true)
    setReadinessError(null)

    try {
      const result =
        await getSessionReadiness(
          sessionId,
        )

      setReadiness(result)
    } catch (error: unknown) {
      setReadiness(null)

      setReadinessError(
        error instanceof ApiError
          ? error.message
          : 'Session readiness could not be checked.',
      )
    } finally {
      setReadinessLoading(false)
    }
  }

  async function handleSessionAction(
    action: SessionLifecycleAction,
  ) {
    if (!sessionId) {
      return
    }

    if (
      action === 'start' &&
      readiness?.ready !== true
    ) {
      setActionError(
        'The session cannot start until the readiness check passes.',
      )
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

        if (action === 'start') {
          void refreshReadiness()
        }
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
    sessionState?.status ===
      'prepared' &&
    readiness?.ready !== false &&
    !readinessLoading &&
    !isBusy

  const canPause =
    sessionState?.status ===
      'active' &&
    !sessionState.paused &&
    !isBusy

  const canResume =
    sessionState?.status ===
      'active' &&
    sessionState.paused &&
    !isBusy

  const canEnd =
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
    <div>

      <PageHeader
        title={details?.title ?? 'Live session'}
        description={details ? details.course_code : undefined}
        actions={
          <>
            {connectionStatus !== 'connected' && (
              <span role="status" className="text-sm text-muted-foreground">
                {connectionLabel(connectionStatus)}
              </span>
            )}
            {sessionId && (
              <Link to={`/lecturer/sessions/${sessionId}/report`} className={buttonStyles({ intent: 'secondary' })}>
                Report
              </Link>
            )}
          </>
        }
      >
        {details && (
          <div className="mt-3">
            <Tag tone={statusTone({ status: sessionState?.status ?? details.status, paused: sessionState?.paused ?? details.paused })}>
              {statusLabel({ status: sessionState?.status ?? details.status, paused: sessionState?.paused ?? details.paused })}
            </Tag>
          </div>
        )}
      </PageHeader>
      <div className="mx-auto max-w-6xl px-5 py-8 sm:px-8">

        <div className="grid gap-6 lg:grid-cols-2">
          <Panel title="Class" description="Start, pause and end the class from here.">
            <dl className="grid grid-cols-2 gap-4">
              <div>
                <dt className="text-sm text-muted-foreground">Session</dt>
                <dd className="mt-1 text-xl font-semibold">
                  {sessionLabel(sessionState?.status)}
                </dd>
              </div>
              <div>
                <dt className="text-sm text-muted-foreground">Questions</dt>
                <dd className="mt-1 text-xl font-semibold">
                  {questionCycleLabel(sessionState?.status, sessionState?.paused)}
                </dd>
              </div>
            </dl>

            {sessionState?.status === 'prepared' && (
              <ReadinessChecklist
                readiness={readiness}
                loading={readinessLoading}
                error={readinessError}
                busy={isBusy}
                onRefresh={() => void refreshReadiness()}
              />
            )}

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
                  className={buttonStyles()}
                >
                  {actionInProgress ===
                  'start'
                    ? 'Starting...'
                    : readinessLoading
                      ? 'Checking...'
                      : 'Start the class'}
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
                    className={buttonStyles({ intent: 'secondary' })}
                  >
                    {actionInProgress ===
                    'pause'
                      ? 'Pausing...'
                      : 'Pause'}
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
                    className={buttonStyles()}
                  >
                    {actionInProgress ===
                    'resume'
                      ? 'Resuming...'
                      : 'Resume'}
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
                  className={buttonStyles({ intent: 'danger' })}
                >
                  {actionInProgress ===
                  'end'
                    ? 'Ending...'
                    : 'End the class'}
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
          </Panel>

          <Panel
            title="Participants"
            description={
              sessionState?.status === 'prepared'
                ? 'Connected and waiting for the session to start'
                : sessionState?.status === 'active'
                  ? 'Currently connected students'
                  : sessionState?.status === 'ended'
                    ? 'Session ended'
                    : sessionState?.status === 'cancelled'
                      ? 'Session cancelled'
                      : 'Waiting for session state'
            }
          >
            <p className="text-3xl font-semibold tabular-nums">
              {sessionState?.status === 'ended' ||
              sessionState?.status === 'cancelled'
                ? 0
                : (sessionState?.participant_count ?? '-')}
            </p>
          </Panel>

          <LecturerAttentionPanel
            students={engagement}
            loading={engagementLoading}
            error={engagementError}
            sessionStatus={
              sessionState?.status
            }
          />

          <CheckpointMonitor
            sessionId={sessionId}
            delivered={sessionState?.questions_delivered ?? 0}
            activeQuestion={activeQuestion}
            closedQuestion={closedQuestion}
            secondsRemaining={secondsRemaining}
            canSend={canTriggerQuestion}
          />

          {sessionId && (
            <LiveResults
              sessionId={sessionId}
              openQuestionId={activeQuestion?.question_id ?? null}
              closedQuestionId={closedQuestion?.question_id ?? null}
            />
          )}

          <TopicRecoveryPanel
            topics={topics}
            loading={topicsLoading}
            error={topicsError}
          />

          <RoomsPanel rooms={rooms} />

          <LiveAlertsPanel
            className="lg:col-span-2"
            alerts={alerts}
            sessionNotice={sessionNotice}
            onAcknowledge={
              acknowledgeAlert
            }
          />
        </div>
      </div>
    </div>
  )
}