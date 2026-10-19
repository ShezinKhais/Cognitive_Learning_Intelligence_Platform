
import {
  CheckCircle2,
  Clock3,
  MessagesSquare,
  RefreshCw,
  Users,
  XCircle,
} from 'lucide-react'
import { AnimatePresence, motion } from 'motion/react'

import { buttonStyles } from '../components/ui/button'
import SegmentedTabs from '../components/ui/SegmentedTabs'
import { BackLink } from '../components/ui/primitives'
import { useDocumentTitle } from '../components/ui/useDocumentTitle'
import {
  useEffect,
  useState,
} from 'react'
import {
  Link,
  useParams,
} from 'react-router'

import { useStudentApp } from '../features/student/StudentAppContext'
import { SocraticChatPanel } from '../features/chat/SocraticChatPanel'
import { remainingResponseSeconds } from '../features/student/liveSessionState'
import type {
  CheckpointState,
  LiveConnectionStatus,
} from '../features/student/liveSessionTypes'
import type { StudentSession } from '../features/student/types'
import ParticipationGauge from '../features/student/ParticipationGauge'
import RoomConfirm from '../features/student/RoomConfirm'
import { useLiveSession } from '../features/student/useLiveSession'
import { AttentionControls } from '../features/attention/AttentionControls'

const SOCRATIC_CHAT_ENABLED =
  import.meta.env.VITE_SOCRATIC_CHAT_ENABLED === 'true'
const LOCAL_ATTENTION_ENABLED =
  import.meta.env.VITE_LOCAL_ATTENTION_ENABLED === 'true'

export default function StudentLiveSessionPage() {
  const { sessionId } = useParams<{ sessionId: string }>()
  const { sessions } = useStudentApp()
  const session = sessions.find((candidate) => candidate.id === sessionId)

  if (!sessionId || !session) {
    return (
      <div className="grid place-items-center bg-background p-6">
        <section className="w-full max-w-md rounded-xl border border-border bg-card p-6 text-center shadow-[var(--shadow-card)]">
          <h1 className="text-xl font-semibold">Session unavailable</h1>
          <p className="mt-2 text-sm text-muted-foreground">
            This session is not assigned to your student account.
          </p>
          <Link
            to="/student"
            className="mt-5 inline-flex rounded-lg bg-primary px-4 py-2 text-sm font-medium text-primary-foreground"
          >
            Return to sessions
          </Link>
        </section>
      </div>
    )
  }

  return <LiveSessionPanel session={session} />
}

export function LiveSessionPanel({
  session,
  compact = false,
}: {
  session: StudentSession
  compact?: boolean
}) {
  const [activeView, setActiveView] = useState<'class' | 'chat'>('class')
  const {
    state,
    selectOption,
    setFreeText,
    submitAnswer,
    acknowledgePrompt,
    clearError,
    sendAttention,
    attentionConsentRejected,
    confirmRoom,
  } = useLiveSession(session.id, session.status, session.paused ?? false)

  const now = useCurrentTime(
    Boolean(state.checkpoint || state.attentionPrompt),
  )

  useDocumentTitle(compact ? undefined : session.title)

  const finished =
    state.sessionStatus === 'ended' ||
    state.sessionStatus === 'cancelled'

  const secondsRemaining = state.checkpoint
    ? remainingResponseSeconds(
        state.checkpoint.question.closes_at,
        now,
      )
    : 0

  return (
    <div className={`bg-background px-4 py-5 ${compact ? '' : 'sm:px-6 sm:py-8'}`}>
      <div className={`mx-auto ${compact ? 'max-w-xl' : 'max-w-4xl'}`}>
        <header className="rounded-xl border border-border bg-card p-5 shadow-[var(--shadow-card)] sm:p-6">
          <div className="flex flex-wrap items-start justify-between gap-4">
            <div>
              {!compact && (
                <BackLink to="/student">My sessions</BackLink>
              )}

              <p className={`${compact ? '' : 'mt-4'} text-sm font-semibold text-info`}>
                {session.course_code}
              </p>

              <h1 className="mt-1 text-2xl font-bold sm:text-3xl">
                {session.title}
              </h1>
            </div>

          </div>

          <div className="mt-5 flex flex-wrap gap-x-6 gap-y-2 border-t border-border pt-4 text-sm text-muted-foreground">
            {!finished && (
              <span className="inline-flex items-center gap-2">
                <Users aria-hidden="true" size={17} />
                {state.participantCount} connected
              </span>
            )}

            <span>
              Session:{' '}
              <strong className="font-medium text-foreground">
                {sessionStateLabel(state.sessionStatus, state.paused)}
              </strong>
            </span>

            <span className="ml-auto">
              <ParticipationGauge answered={state.answeredIds.length} delivered={state.questionsDelivered} />
            </span>
          </div>
          {state.sessionStatus === 'active' && !compact && (
            <RoomConfirm onConfirm={confirmRoom} serverError={state.error}
              enabled={state.connection === 'connected' && !state.paused} />
          )}
        </header>

        {!finished && <ConnectionNotice status={state.connection} />}

        {LOCAL_ATTENTION_ENABLED && (
          <AttentionControls key={session.id} onSignal={sendAttention}
            consentRejected={attentionConsentRejected}
            enabled={state.connection === 'connected' && state.sessionStatus === 'active' && !state.paused} />
        )}

        {SOCRATIC_CHAT_ENABLED && !finished && (
          <SegmentedTabs
            label="Student session tools"
            value={activeView}
            onChange={setActiveView}
            stretch
            className="mt-5 rounded-xl"
            segments={[
              { key: 'class', label: 'Live class' },
              {
                key: 'chat',
                label: (
                  <>
                    <MessagesSquare aria-hidden="true" size={17} />
                    Learning assistant
                  </>
                ),
              },
            ]}
          />
        )}

        {state.error && !finished && state.connection !== 'forbidden' && (
          <div
            role="alert"
            className="mt-4 flex items-start justify-between gap-4 rounded-xl border border-critical/30 bg-card p-4 text-sm"
          >
            <div>
              <p className="font-semibold text-critical">
                Live session error
              </p>

              <p className="mt-1 text-muted-foreground">
                {state.error.detail ?? state.error.code}
              </p>
            </div>

            <button
              type="button"
              onClick={clearError}
              className="rounded-md px-2 py-1 font-medium text-muted-foreground hover:bg-muted"
            >
              Dismiss
            </button>
          </div>
        )}

        <section
          className="mt-5"
          aria-live="polite"
          hidden={SOCRATIC_CHAT_ENABLED && !finished && activeView !== 'class' && !state.checkpoint}
        >
          <AnimatePresence mode="wait" initial={false}>
            <motion.div
              key={state.checkpoint ? `ask-${state.checkpoint.question.question_id}` : state.completedCheckpoint ? 'done' : 'wait'}
              initial={{ opacity: 0, y: -14, scale: 0.98 }}
              animate={{ opacity: 1, y: 0, scale: 1 }}
              exit={{ opacity: 0, y: 8, transition: { duration: 0.15 } }}
              transition={{ type: 'spring', stiffness: 300, damping: 28 }}
            >
              {state.checkpoint ? (
                <CheckpointCard
                  checkpoint={state.checkpoint}
                  secondsRemaining={secondsRemaining}
                  connected={state.connection === 'connected'}
                  onSelectOption={selectOption}
                  onSetFreeText={setFreeText}
                  onSubmit={submitAnswer}
                />
              ) : state.completedCheckpoint ? (
                <CompletedCheckpointCard
                  checkpoint={state.completedCheckpoint}
                />
              ) : (
                <WaitingCard
                  sessionId={session.id}
                  sessionStatus={state.sessionStatus}
                  paused={state.paused}
                  compact={compact}
                />
              )}
            </motion.div>
          </AnimatePresence>
        </section>

        {SOCRATIC_CHAT_ENABLED && !finished && (
          <div className="mt-5" hidden={activeView !== 'chat'}>
            <SocraticChatPanel
              key={session.id}
              sessionId={session.id}
              compact={compact}
            />
          </div>
        )}
      </div>

      {state.attentionPrompt &&
        Date.parse(state.attentionPrompt.expires_at) > now && (
          <aside
            role="alertdialog"
            aria-labelledby="attention-prompt-title"
            aria-describedby="attention-prompt-message"
            className="fixed inset-x-4 bottom-4 z-20 mx-auto max-w-md rounded-xl border-2 border-warning bg-card p-5 shadow-2xl"
          >
            <p className="text-xs font-semibold text-warning">
              Private check-in
            </p>

            <h2
              id="attention-prompt-title"
              className="mt-1 text-lg font-semibold"
            >
              Are you still with us?
            </h2>

            <p
              id="attention-prompt-message"
              className="mt-2 text-sm text-muted-foreground"
            >
              {state.attentionPrompt.message}
            </p>

            <p className="mt-2 text-xs text-muted-foreground">
              Only you can see this prompt.
            </p>

            <div className="mt-4 flex gap-3">
              <button
                type="button"
                onClick={() => acknowledgePrompt(false)}
                className="flex-1 rounded-lg bg-primary px-4 py-2 text-sm font-semibold text-primary-foreground"
              >
                I’m here
              </button>

              <button
                type="button"
                onClick={() => acknowledgePrompt(true)}
                className="rounded-lg border border-border px-4 py-2 text-sm font-medium"
              >
                Dismiss
              </button>
            </div>
          </aside>
        )}
    </div>
  )
}

function CompletedCheckpointCard({
  checkpoint,
}: {
  checkpoint: CheckpointState
}) {
  return (
    <article className="rounded-xl border border-border bg-card p-5 shadow-[var(--shadow-card)] sm:p-7">
      <CheckpointOutcome checkpoint={checkpoint} />

      <p className="mt-4 text-sm text-muted-foreground">
        Stay on this page. The lecturer’s next question will appear
        automatically.
      </p>
    </article>
  )
}

function CheckpointCard({
  checkpoint,
  secondsRemaining,
  connected,
  onSelectOption,
  onSetFreeText,
  onSubmit,
}: {
  checkpoint: CheckpointState
  secondsRemaining: number
  connected: boolean
  onSelectOption: (option: number) => void
  onSetFreeText: (value: string) => void
  onSubmit: () => boolean
}) {
  const { question } = checkpoint

  const editable =
    connected &&
    secondsRemaining > 0 &&
    !checkpoint.closed &&
    (
      checkpoint.phase === 'answering' ||
      checkpoint.phase === 'rejected'
    )

  const hasOptions = Boolean(question.options?.length)

  const answerPresent = hasOptions
    ? checkpoint.selectedOption !== null
    : checkpoint.freeText.trim().length > 0

  const progress = Math.max(
    0,
    Math.min(
      100,
      (secondsRemaining / question.window_seconds) * 100,
    ),
  )

  return (
    <article className="overflow-hidden rounded-lg border-2 border-primary/40 bg-card shadow-[var(--shadow-card-hover)]">
      <div className="flex flex-wrap items-center justify-between gap-3 border-b border-border px-5 py-4 sm:px-7">
        <div>
          <p className="inline-flex items-center gap-2 text-sm font-semibold text-primary">
            <span aria-hidden className="relative flex h-2 w-2">
              <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-primary opacity-60" />
              <span className="relative inline-flex h-2 w-2 rounded-full bg-primary" />
            </span>
            Live checkpoint
          </p>

          {question.source_slide !== null && (
            <p className="mt-1 text-xs text-muted-foreground">
              Based on slide {question.source_slide}
            </p>
          )}
        </div>

        <div
          className={`inline-flex items-center gap-2 rounded-full px-3 py-1.5 text-sm font-semibold ${
            secondsRemaining <= 5
              ? 'bg-critical/10 text-critical'
              : 'bg-secondary text-secondary-foreground'
          }`}
          aria-label={`${secondsRemaining} seconds remaining`}
        >
          <Clock3 aria-hidden="true" size={16} />
          {secondsRemaining}s
        </div>
      </div>

      <div
        className="h-1.5 bg-muted"
        role="progressbar"
        aria-valuemin={0}
        aria-valuemax={question.window_seconds}
        aria-valuenow={secondsRemaining}
        aria-label="Response time remaining"
      >
        {/* Glides between ticks rather than stepping; turns amber, then red,
            as time runs out. */}
        <motion.div
          className={`h-full ${
            secondsRemaining <= 5 ? 'bg-critical' : secondsRemaining <= 10 ? 'bg-warning' : 'bg-primary'
          }`}
          initial={false}
          animate={{ width: `${progress}%` }}
          transition={{ duration: 0.9, ease: 'linear' }}
        />
      </div>

      <div className="p-5 sm:p-7">
        <h2 className="text-xl font-semibold leading-snug">
          {question.prompt}
        </h2>

        {hasOptions ? (
          <fieldset
            className="mt-6 grid gap-3"
            disabled={!editable}
          >
            <legend className="sr-only">
              Choose one answer
            </legend>

            {question.options!.map((option, index) => {
              const selected =
                checkpoint.selectedOption === index

              return (
                <label
                  key={`${question.question_id}-${index}`}
                  className={`flex cursor-pointer items-start gap-3 rounded-xl border p-4 transition-colors ${
                    selected
                      ? 'border-info bg-info/5'
                      : 'border-border hover:bg-muted/60'
                  } ${
                    !editable
                      ? 'cursor-default opacity-70'
                      : ''
                  }`}
                >
                  <input
                    type="radio"
                    name={`answer-${question.question_id}`}
                    value={index}
                    checked={selected}
                    onChange={() => onSelectOption(index)}
                    className="mt-1 h-4 w-4 accent-[var(--info)]"
                  />

                  <span className="text-sm leading-6">
                    {option}
                  </span>
                </label>
              )
            })}
          </fieldset>
        ) : (
          <div className="mt-6">
            <label
              htmlFor={`answer-${question.question_id}`}
              className="text-sm font-medium"
            >
              Your answer
            </label>

            <textarea
              id={`answer-${question.question_id}`}
              rows={5}
              maxLength={4000}
              value={checkpoint.freeText}
              disabled={!editable}
              onChange={(event) =>
                onSetFreeText(event.target.value)
              }
              className="mt-2 w-full resize-y rounded-xl border border-border bg-input-background p-3 text-sm outline-none focus:ring-2 focus:ring-ring disabled:opacity-70"
            />
          </div>
        )}

        <CheckpointOutcome checkpoint={checkpoint} />

        {(
          checkpoint.phase === 'answering' ||
          checkpoint.phase === 'rejected'
        ) && (
          <button
            type="button"
            onClick={onSubmit}
            disabled={!editable || !answerPresent}
            className="mt-6 w-full rounded-xl bg-primary px-5 py-3 text-sm font-semibold text-primary-foreground disabled:cursor-not-allowed disabled:opacity-45 sm:w-auto"
          >
            Submit answer
          </button>
        )}

        {checkpoint.phase === 'submitting' && (
          <p
            role="status"
            className="mt-6 inline-flex items-center gap-2 text-sm font-medium text-info"
          >
            <RefreshCw
              aria-hidden="true"
              size={17}
              className="animate-spin"
            />
            Saving your answer…
          </p>
        )}

        {/* NEW: Show a message instead of loading forever. */}
        {checkpoint.phase === 'unconfirmed' && (
          <div
            role="status"
            className="mt-6 rounded-xl border border-warning/30 bg-warning/5 p-4"
          >
            <p className="font-semibold text-warning">
              Answer confirmation unavailable
            </p>

            <p className="mt-2 text-sm text-muted-foreground">
              Your answer was sent, but we could not
              confirm whether it was saved.
              Please stay on this page while
              your connection recovers.
            </p>
          </div>
        )}
      </div>
    </article>
  )
}

function CheckpointOutcome({
  checkpoint,
}: {
  checkpoint: CheckpointState
}) {
  if (checkpoint.phase === 'missed') {
    return (
      <div
        role="status"
        className="mt-6 rounded-xl border border-warning/30 bg-warning/5 p-4"
      >
        <p className="flex items-center gap-2 font-semibold text-warning">
          <Clock3 aria-hidden="true" size={18} />
          Response window closed
        </p>

        <p className="mt-1 text-sm text-muted-foreground">
          No answer was recorded for this checkpoint.
          You can continue participating in the session.
        </p>
      </div>
    )
  }

  if (checkpoint.phase === 'rejected') {
    return (
      <div
        role="alert"
        className="mt-5 rounded-xl border border-critical/30 bg-critical/5 p-4 text-sm"
      >
        <p className="font-semibold text-critical">
          Answer not accepted
        </p>

        <p className="mt-1 text-muted-foreground">
          {checkpoint.receipt?.reason ??
            'Please check your answer and try again.'}
        </p>
      </div>
    )
  }

  if (checkpoint.phase !== 'submitted') {
    return null
  }

  const feedback = checkpoint.feedback

  const resultLabel =
    feedback?.correct === true
      ? 'Correct answer'
      : feedback?.correct === false
        ? 'Not quite'
        : 'Answer received'

  const ResultIcon =
    feedback?.correct === false
      ? XCircle
      : CheckCircle2

  const resultColour =
    feedback?.correct === false
      ? 'text-warning'
      : 'text-success'

  return (
    <div
      role="status"
      className="mt-6 rounded-xl border border-border bg-muted/50 p-4"
    >
      <p
        className={`flex items-center gap-2 font-semibold ${resultColour}`}
      >
        <ResultIcon aria-hidden="true" size={19} />
        {resultLabel}
      </p>

      {feedback?.explanation && (
        <p className="mt-2 text-sm leading-6 text-muted-foreground">
          {feedback.explanation}
        </p>
      )}

      {feedback?.source_slide !== null &&
        feedback?.source_slide !== undefined && (
          <p className="mt-2 text-xs font-medium text-info">
            Review slide {feedback.source_slide}
          </p>
        )}
    </div>
  )
}

function sessionStateLabel(
  status: StudentSession['status'],
  paused: boolean,
): string {
  if (status === 'active') return paused ? 'Paused' : 'Live'
  const labels: Record<string, string> = {
    prepared: 'Not started',
    ended: 'Ended',
    cancelled: 'Cancelled',
  }
  return labels[status] ?? status
}

function WaitingCard({
  sessionId,
  sessionStatus,
  paused,
  compact,
}: {
  sessionId: string
  sessionStatus: StudentSession['status']
  paused: boolean
  compact: boolean
}) {
  const ended =
    sessionStatus === 'ended' ||
    sessionStatus === 'cancelled'

  return (
    <div className="rounded-xl border border-border bg-card p-8 text-center shadow-[var(--shadow-card)]">
      <div className="mx-auto grid h-12 w-12 place-items-center rounded-full bg-secondary">
        {ended ? (
          <CheckCircle2
            aria-hidden="true"
            className="text-muted-foreground"
          />
        ) : (
          <Clock3
            aria-hidden="true"
            className="text-info"
          />
        )}
      </div>

      <h2 className="mt-4 text-xl font-semibold">
        {ended
          ? sessionStatus === 'cancelled' ? 'This session was cancelled' : 'This session has ended'
          : paused
            ? 'Session paused'
            : 'Waiting for the next checkpoint'}
      </h2>

      <p className="mx-auto mt-2 max-w-lg text-sm leading-6 text-muted-foreground">
        {ended
          ? sessionStatus === 'cancelled' ? 'There is no post-session review for a cancelled session.' : 'Your answers are saved. See how you did, and what to revisit before the next class.'
          : paused
            ? 'The lecturer has paused the session. Checkpoints will resume automatically when the session continues.'
            : 'Stay on this page. The lecturer’s next question will appear automatically.'}
      </p>

      {sessionStatus === 'ended' && !compact && (
        <Link
          to={`/student/session/${sessionId}/summary`}
          className={`${buttonStyles()} mt-5`}
        >
          See how you did
        </Link>
      )}
    </div>
  )
}

function ConnectionNotice({
  status,
}: {
  status: LiveConnectionStatus
}) {
  if (
    status === 'connected' ||
    status === 'ended'
  ) {
    return null
  }

  const copy: Record<
    Exclude<LiveConnectionStatus, 'connected' | 'ended'>,
    string
  > = {
    connecting: 'Connecting to the live session…',
    recovering: 'Connected again. Restoring the latest session state…',
    reconnecting: 'Connection interrupted. Your page will reconnect automatically.',
    offline: 'You appear to be offline. Reconnection will start when your network returns.',
    forbidden: 'You are not permitted to join this session. Return to your assigned sessions.',
    disconnected: 'The live connection is unavailable.',
  }

  return (
    <div
      role="status"
      className="mt-4 rounded-xl border border-warning/30 bg-card p-4 text-sm"
    >
      <p className="flex items-center gap-2 font-medium text-warning">
        <RefreshCw
          aria-hidden="true"
          size={17}
          className={
            status === 'connecting' ||
            status === 'reconnecting'
              ? 'animate-spin'
              : ''
          }
        />

        {copy[status]}
      </p>

      {(
        status === 'reconnecting' ||
        status === 'offline' ||
        status === 'recovering'
      ) && (
        <p className="mt-1 text-muted-foreground">
          Answer controls remain locked until recovery is complete.
        </p>
      )}
    </div>
  )
}

function useCurrentTime(enabled: boolean): number {
  const [now, setNow] = useState(Date.now())

  useEffect(() => {
    if (!enabled) return

    const timer = window.setInterval(
      () => setNow(Date.now()),
      250,
    )

    return () => window.clearInterval(timer)
  }, [enabled])

  return now
}
