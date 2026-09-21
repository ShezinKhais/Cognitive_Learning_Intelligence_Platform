import {
  CheckCircle2,
  ChevronLeft,
  Clock3,
  RefreshCw,
  Users,
  Wifi,
  WifiOff,
  XCircle,
} from 'lucide-react'
import {
  useEffect,
  useState,
} from 'react'
import {
  Link,
  useParams,
} from 'react-router'

import { useStudentApp } from '../features/student/StudentAppContext'
import { remainingResponseSeconds } from '../features/student/liveSessionState'
import type {
  CheckpointState,
  LiveConnectionStatus,
} from '../features/student/liveSessionTypes'
import type { StudentSession } from '../features/student/types'
import { useLiveSession } from '../features/student/useLiveSession'

export default function StudentLiveSessionPage() {
  const { sessionId } = useParams<{ sessionId: string }>()
  const { sessions } = useStudentApp()
  const session = sessions.find((candidate) => candidate.id === sessionId)

  if (!sessionId || !session) {
    return (
      <main className="grid min-h-screen place-items-center bg-background p-6">
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
      </main>
    )
  }

  return <LiveSessionPanel session={session} />
}

function LiveSessionPanel({ session }: { session: StudentSession }) {
  const {
    state,
    selectOption,
    setFreeText,
    submitAnswer,
    acknowledgePrompt,
    clearError,
  } = useLiveSession(session.id, session.status)
  const now = useCurrentTime(Boolean(state.checkpoint || state.attentionPrompt))
  const secondsRemaining = state.checkpoint
    ? remainingResponseSeconds(state.checkpoint.question.closes_at, now)
    : 0

  return (
    <main className="min-h-screen bg-background px-4 py-5 sm:px-6 sm:py-8">
      <div className="mx-auto max-w-4xl">
        <header className="rounded-xl border border-border bg-card p-5 shadow-[var(--shadow-card)] sm:p-6">
          <div className="flex flex-wrap items-start justify-between gap-4">
            <div>
              <Link
                to="/student"
                className="inline-flex items-center gap-1 text-sm font-medium text-info hover:underline"
              >
                <ChevronLeft aria-hidden="true" size={17} />
                All sessions
              </Link>
              <p className="mt-4 text-sm font-semibold text-info">
                {session.course_code}
              </p>
              <h1 className="mt-1 text-2xl font-bold sm:text-3xl">
                {session.title}
              </h1>
            </div>

            {state.sessionStatus !== 'ended' &&
              state.sessionStatus !== 'cancelled' && (
                <ConnectionBadge status={state.connection} />
              )}
          </div>

          <div className="mt-5 flex flex-wrap gap-x-6 gap-y-2 border-t border-border pt-4 text-sm text-muted-foreground">
            <span className="inline-flex items-center gap-2">
              <Users aria-hidden="true" size={17} />
              {state.participantCount} connected
            </span>
            <span>
              Session: <strong className="font-medium text-foreground">{state.sessionStatus}</strong>
            </span>
            <span>
              Checkpoints delivered: <strong className="font-medium text-foreground">{state.questionsDelivered}</strong>
            </span>
          </div>
        </header>

        <ConnectionNotice status={state.connection} />

        {state.error && (
          <div
            role="alert"
            className="mt-4 flex items-start justify-between gap-4 rounded-xl border border-critical/30 bg-card p-4 text-sm"
          >
            <div>
              <p className="font-semibold text-critical">Live session error</p>
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

        <section className="mt-5" aria-live="polite">
          {state.checkpoint &&
          !state.checkpoint.closed &&
          (
            state.checkpoint.phase === 'answering' ||
            state.checkpoint.phase === 'rejected' ||
            state.checkpoint.phase === 'submitting'
          ) ? (
            <CheckpointCard
              checkpoint={state.checkpoint}
              secondsRemaining={secondsRemaining}
              connected={state.connection === 'connected'}
              onSelectOption={selectOption}
              onSetFreeText={setFreeText}
              onSubmit={submitAnswer}
            />
          ) : (
            <WaitingCard sessionStatus={state.sessionStatus} />
          )}
        </section>
      </div>

      {state.attentionPrompt && Date.parse(state.attentionPrompt.expires_at) > now && (
        <aside
          role="alertdialog"
          aria-labelledby="attention-prompt-title"
          aria-describedby="attention-prompt-message"
          className="fixed inset-x-4 bottom-4 z-20 mx-auto max-w-md rounded-xl border-2 border-warning bg-card p-5 shadow-2xl"
        >
          <p className="text-xs font-semibold uppercase tracking-wide text-warning">
            Private check-in
          </p>
          <h2 id="attention-prompt-title" className="mt-1 text-lg font-semibold">
            Are you still with us?
          </h2>
          <p id="attention-prompt-message" className="mt-2 text-sm text-muted-foreground">
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
    </main>
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
    (checkpoint.phase === 'answering' || checkpoint.phase === 'rejected')
  const answerPresent = question.options
    ? checkpoint.selectedOption !== null
    : checkpoint.freeText.trim().length > 0
  const progress = Math.max(
    0,
    Math.min(100, (secondsRemaining / question.window_seconds) * 100),
  )

  return (
    <article className="overflow-hidden rounded-xl border border-border bg-card shadow-[var(--shadow-card)]">
      <div className="flex flex-wrap items-center justify-between gap-3 border-b border-border px-5 py-4 sm:px-7">
        <div>
          <p className="text-xs font-semibold uppercase tracking-wide text-info">
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
        className="h-1 bg-muted"
        role="progressbar"
        aria-valuemin={0}
        aria-valuemax={question.window_seconds}
        aria-valuenow={secondsRemaining}
        aria-label="Response time remaining"
      >
        <div
          className={`h-full transition-[width] ${secondsRemaining <= 5 ? 'bg-critical' : 'bg-info'}`}
          style={{ width: `${progress}%` }}
        />
      </div>

      <div className="p-5 sm:p-7">
        <h2 className="text-xl font-semibold leading-snug">{question.prompt}</h2>

        {question.options ? (
          <fieldset className="mt-6 grid gap-3" disabled={!editable}>
            <legend className="sr-only">Choose one answer</legend>
            {question.options.map((option, index) => {
              const selected = checkpoint.selectedOption === index
              return (
                <label
                  key={`${question.question_id}-${index}`}
                  className={`flex cursor-pointer items-start gap-3 rounded-xl border p-4 transition-colors ${
                    selected
                      ? 'border-info bg-info/5'
                      : 'border-border hover:bg-muted/60'
                  } ${!editable ? 'cursor-default opacity-70' : ''}`}
                >
                  <input
                    type="radio"
                    name={`answer-${question.question_id}`}
                    value={index}
                    checked={selected}
                    onChange={() => onSelectOption(index)}
                    className="mt-1 h-4 w-4 accent-[var(--info)]"
                  />
                  <span className="text-sm leading-6">{option}</span>
                </label>
              )
            })}
          </fieldset>
        ) : (
          <div className="mt-6">
            <label htmlFor={`answer-${question.question_id}`} className="text-sm font-medium">
              Your answer
            </label>
            <textarea
              id={`answer-${question.question_id}`}
              rows={5}
              maxLength={4000}
              value={checkpoint.freeText}
              disabled={!editable}
              onChange={(event) => onSetFreeText(event.target.value)}
              className="mt-2 w-full resize-y rounded-xl border border-border bg-input-background p-3 text-sm outline-none focus:ring-2 focus:ring-ring disabled:opacity-70"
            />
          </div>
        )}

        <CheckpointOutcome checkpoint={checkpoint} />

        {(checkpoint.phase === 'answering' || checkpoint.phase === 'rejected') && (
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
          <p role="status" className="mt-6 inline-flex items-center gap-2 text-sm font-medium text-info">
            <RefreshCw aria-hidden="true" size={17} className="animate-spin" />
            Saving your answer…
          </p>
        )}
      </div>
    </article>
  )
}

function CheckpointOutcome({ checkpoint }: { checkpoint: CheckpointState }) {
  if (checkpoint.phase === 'missed') {
    return (
      <div role="status" className="mt-6 rounded-xl border border-warning/30 bg-warning/5 p-4">
        <p className="flex items-center gap-2 font-semibold text-warning">
          <Clock3 aria-hidden="true" size={18} />
          Response window closed
        </p>
        <p className="mt-1 text-sm text-muted-foreground">
          No answer was recorded for this checkpoint. You can continue participating in the session.
        </p>
      </div>
    )
  }

  if (checkpoint.phase === 'rejected') {
    return (
      <div role="alert" className="mt-5 rounded-xl border border-critical/30 bg-critical/5 p-4 text-sm">
        <p className="font-semibold text-critical">Answer not accepted</p>
        <p className="mt-1 text-muted-foreground">
          {checkpoint.receipt?.reason ?? 'Please check your answer and try again.'}
        </p>
      </div>
    )
  }

  if (checkpoint.phase !== 'submitted') return null

  const feedback = checkpoint.feedback
  const resultLabel = feedback?.correct === true
    ? 'Correct answer'
    : feedback?.correct === false
      ? 'Not quite'
      : 'Answer received'
  const ResultIcon = feedback?.correct === false ? XCircle : CheckCircle2
  const resultColour = feedback?.correct === false ? 'text-warning' : 'text-success'

  return (
    <div role="status" className="mt-6 rounded-xl border border-border bg-muted/50 p-4">
      <p className={`flex items-center gap-2 font-semibold ${resultColour}`}>
        <ResultIcon aria-hidden="true" size={19} />
        {resultLabel}
      </p>
      {feedback?.explanation && (
        <p className="mt-2 text-sm leading-6 text-muted-foreground">
          {feedback.explanation}
        </p>
      )}
      {feedback?.source_slide !== null && feedback?.source_slide !== undefined && (
        <p className="mt-2 text-xs font-medium text-info">
          Review slide {feedback.source_slide}
        </p>
      )}
    </div>
  )
}

function WaitingCard({ sessionStatus }: { sessionStatus: StudentSession['status'] }) {
  const ended = sessionStatus === 'ended' || sessionStatus === 'cancelled'
  return (
    <div className="rounded-xl border border-border bg-card p-8 text-center shadow-[var(--shadow-card)]">
      <div className="mx-auto grid h-12 w-12 place-items-center rounded-full bg-secondary">
        {ended ? (
          <CheckCircle2 aria-hidden="true" className="text-muted-foreground" />
        ) : (
          <Clock3 aria-hidden="true" className="text-info" />
        )}
      </div>
      <h2 className="mt-4 text-xl font-semibold">
        {ended ? 'This session has ended' : 'Waiting for the next checkpoint'}
      </h2>
      <p className="mx-auto mt-2 max-w-lg text-sm leading-6 text-muted-foreground">
        {ended
          ? 'Your responses have been saved. A review view will be available in the reporting phase.'
          : 'Stay on this page. The lecturer’s next question will appear automatically.'}
      </p>
    </div>
  )
}

function ConnectionBadge({ status }: { status: LiveConnectionStatus }) {
  const connected = status === 'connected'
  return (
    <span
      className={`inline-flex items-center gap-2 rounded-full px-3 py-1.5 text-xs font-semibold ${
        connected ? 'bg-success/10 text-success' : 'bg-warning/10 text-warning'
      }`}
    >
      {connected ? <Wifi aria-hidden="true" size={15} /> : <WifiOff aria-hidden="true" size={15} />}
      {connectionLabel(status)}
    </span>
  )
}

function ConnectionNotice({ status }: { status: LiveConnectionStatus }) {
  if (status === 'connected') return null

  const copy: Record<Exclude<LiveConnectionStatus, 'connected'>, string> = {
    connecting: 'Connecting to the live session…',
    recovering: 'Connected again. Restoring the latest session state…',
    reconnecting: 'Connection interrupted. Your page will reconnect automatically.',
    offline: 'You appear to be offline. Reconnection will start when your network returns.',
    forbidden: 'You are not permitted to join this session. Return to your assigned sessions.',
    disconnected: 'The live connection is unavailable.',
  }

  return (
    <div role="status" className="mt-4 rounded-xl border border-warning/30 bg-card p-4 text-sm">
      <p className="flex items-center gap-2 font-medium text-warning">
        <RefreshCw
          aria-hidden="true"
          size={17}
          className={status === 'connecting' || status === 'reconnecting' ? 'animate-spin' : ''}
        />
        {copy[status]}
      </p>
      {(status === 'reconnecting' || status === 'offline' || status === 'recovering') && (
        <p className="mt-1 text-muted-foreground">
          Answer controls remain locked until recovery is complete.
        </p>
      )}
    </div>
  )
}

function connectionLabel(status: LiveConnectionStatus): string {
  return {
    connecting: 'Connecting',
    connected: 'Live',
    recovering: 'Recovering',
    reconnecting: 'Reconnecting',
    offline: 'Offline',
    forbidden: 'Access denied',
    disconnected: 'Disconnected',
  }[status]
}

function useCurrentTime(enabled: boolean): number {
  const [now, setNow] = useState(Date.now())

  useEffect(() => {
    if (!enabled) return
    const timer = window.setInterval(() => setNow(Date.now()), 250)
    return () => window.clearInterval(timer)
  }, [enabled])

  return now
}
