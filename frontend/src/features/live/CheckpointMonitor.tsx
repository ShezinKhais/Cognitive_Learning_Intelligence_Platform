import { AnimatePresence, motion } from 'motion/react'
import { CheckCircle2 } from 'lucide-react'

import { Panel } from '../../components/ui/primitives'
import ManualQuestionTrigger from './ManualQuestionTrigger'
import type { ClosedQuestion, LiveQuestion, QuestionCloseReason } from './useLiveSession'

const CLOSED_BECAUSE: Record<QuestionCloseReason, string> = {
  window_elapsed: 'Time ran out',
  lecturer_closed: 'You closed it',
  session_ended: 'The class ended',
}

/**
 * The checkpoint the class is answering now, or how the last one went, and
 * the way to send one by hand.
 */
export default function CheckpointMonitor({
  sessionId,
  delivered,
  activeQuestion,
  closedQuestion,
  secondsRemaining,
  canSend,
}: {
  sessionId: string | undefined
  delivered: number
  activeQuestion: LiveQuestion | null
  closedQuestion: ClosedQuestion | null
  secondsRemaining: number
  canSend: boolean
}) {
  return (
    <Panel
      className="lg:col-span-2"
      title="Checkpoints"
      description={delivered === 1 ? '1 sent so far' : `${delivered} sent so far`}
    >
      <AnimatePresence mode="wait" initial={false}>
        {activeQuestion ? (
          <motion.div
            key={activeQuestion.question_id}
            initial={{ opacity: 0, y: 8 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0, y: -8 }}
            transition={{ duration: 0.2 }}
          >
            <OpenCheckpoint question={activeQuestion} number={delivered || 1} secondsRemaining={secondsRemaining} />
          </motion.div>
        ) : closedQuestion ? (
          <motion.div
            key={`closed-${closedQuestion.question_id}`}
            initial={{ opacity: 0, y: 8 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0, y: -8 }}
            transition={{ duration: 0.2 }}
          >
            <ClosedCheckpoint question={closedQuestion} />
          </motion.div>
        ) : (
          <motion.p key="none" initial={{ opacity: 0 }} animate={{ opacity: 1 }} className="text-sm text-muted-foreground">
            Nothing open. Checkpoints go out on their own as the class runs, or send one now.
          </motion.p>
        )}
      </AnimatePresence>

      <ManualQuestionTrigger sessionId={sessionId} enabled={canSend} />
    </Panel>
  )
}

function OpenCheckpoint({
  question,
  number,
  secondsRemaining,
}: {
  question: LiveQuestion
  number: number
  secondsRemaining: number
}) {
  const share = question.window_seconds > 0 ? Math.min(1, secondsRemaining / question.window_seconds) : 0
  const colour = secondsRemaining <= 5 ? 'bg-critical' : secondsRemaining <= 10 ? 'bg-warning' : 'bg-primary'

  return (
    <div className="rounded-md border border-border bg-background">
      <div className="flex flex-wrap items-start justify-between gap-4 px-4 pt-4">
        <div className="min-w-0">
          <p className="flex items-center gap-2 text-sm font-semibold text-primary">
            <span className="relative flex h-2 w-2" aria-hidden>
              <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-primary opacity-60 motion-reduce:hidden" />
              <span className="relative inline-flex h-2 w-2 rounded-full bg-primary" />
            </span>
            Question {number} is open
            {question.source_slide !== null && (
              <span className="font-normal text-muted-foreground">, from slide {question.source_slide}</span>
            )}
          </p>
          <p className="mt-2 text-lg font-semibold leading-snug">{question.prompt}</p>
        </div>
        <p aria-live="polite" className="shrink-0 text-right">
          <span className="block text-3xl font-bold tabular-nums">{secondsRemaining}s</span>
          <span className="text-xs text-muted-foreground">left of {question.window_seconds}s</span>
        </p>
      </div>

      {question.options && question.options.length > 0 && (
        <ol className="mt-4 grid gap-2 px-4 sm:grid-cols-2">
          {question.options.map((option, index) => (
            <li key={`${index}-${option}`} className="flex gap-2.5 rounded-md border border-border bg-card px-3 py-2 text-sm">
              <span className="font-bold text-muted-foreground">{String.fromCharCode(65 + index)}</span>
              {option}
            </li>
          ))}
        </ol>
      )}

      <div className="mt-4 h-1.5 overflow-hidden rounded-b-md bg-muted" aria-hidden>
        <motion.div
          className={`h-full ${colour} transition-colors`}
          initial={false}
          animate={{ width: `${share * 100}%` }}
          transition={{ duration: 0.25, ease: 'linear' }}
        />
      </div>
    </div>
  )
}

function ClosedCheckpoint({ question }: { question: ClosedQuestion }) {
  const share = question.eligible > 0 ? question.respondents / question.eligible : 0
  return (
    <div className="flex flex-wrap items-center gap-4 rounded-md border border-border bg-background px-4 py-4">
      <CheckCircle2 size={22} aria-hidden className="shrink-0 text-success" />
      <div className="min-w-0 flex-1">
        <p className="font-semibold">{CLOSED_BECAUSE[question.reason] ?? 'Closed'}</p>
        <p className="text-sm text-muted-foreground">
          <strong className="text-foreground tabular-nums">{question.respondents}</strong> of{' '}
          <span className="tabular-nums">{question.eligible}</span> answered
        </p>
      </div>
      <div className="h-2 w-full overflow-hidden rounded-full bg-muted sm:w-48" aria-hidden>
        <motion.div
          className="h-full rounded-full bg-success"
          initial={{ width: 0 }}
          animate={{ width: `${share * 100}%` }}
          transition={{ duration: 0.6, ease: [0.16, 1, 0.3, 1] }}
        />
      </div>
    </div>
  )
}
