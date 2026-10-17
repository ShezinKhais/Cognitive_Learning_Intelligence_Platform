import { useState } from 'react'
import { AnimatePresence, motion } from 'motion/react'
import { Send } from 'lucide-react'

import { ApiError } from '../../api'
import { buttonStyles } from '../../components/ui/button'
import { cn } from '../../components/ui/cn'
import {
  deliverQuestion,
  loadStagedQuestions,
  type StagedQuestion,
} from './questionActions'

interface ManualQuestionTriggerProps {
  sessionId: string | undefined
  enabled: boolean
}

/**
 * Send a ready question now rather than waiting for the next automatic
 * checkpoint. Opens a list of the session's ready questions to pick from.
 */
export default function ManualQuestionTrigger({ sessionId, enabled }: ManualQuestionTriggerProps) {
  const [questions, setQuestions] = useState<StagedQuestion[]>([])
  const [selectedQuestionId, setSelectedQuestionId] = useState('')
  const [selectorOpen, setSelectorOpen] = useState(false)
  const [loading, setLoading] = useState(false)
  const [delivering, setDelivering] = useState(false)
  const [error, setError] = useState<string | null>(null)

  async function openSelector() {
    if (!enabled || !sessionId) return
    setSelectorOpen(true)
    setError(null)
    setLoading(true)
    try {
      const staged = await loadStagedQuestions(sessionId)
      setQuestions(staged)
      setSelectedQuestionId(staged[0]?.id ?? '')
    } catch (caught) {
      setError(caught instanceof ApiError ? caught.message : 'The ready questions could not be loaded.')
    } finally {
      setLoading(false)
    }
  }

  async function triggerSelectedQuestion() {
    if (!enabled || !sessionId || !selectedQuestionId) return
    setError(null)
    setDelivering(true)
    try {
      await deliverQuestion(sessionId, selectedQuestionId)
      setQuestions((current) => current.filter((question) => question.id !== selectedQuestionId))
      setSelectedQuestionId('')
      setSelectorOpen(false)
    } catch (caught) {
      setError(caught instanceof ApiError ? caught.message : 'The question could not be sent.')
    } finally {
      setDelivering(false)
    }
  }

  return (
    <div className="mt-4">
      {!selectorOpen && (
        <button
          type="button"
          disabled={!enabled}
          onClick={() => void openSelector()}
          className={buttonStyles()}
          title={enabled ? undefined : 'Available while the class is running and nothing is open'}
        >
          <Send size={15} aria-hidden />
          Send a checkpoint now
        </button>
      )}

      <AnimatePresence initial={false}>
        {selectorOpen && (
          <motion.div
            initial={{ height: 0, opacity: 0 }}
            animate={{ height: 'auto', opacity: 1 }}
            exit={{ height: 0, opacity: 0 }}
            transition={{ duration: 0.2 }}
            className="overflow-hidden"
          >
            <fieldset className="rounded-md border border-border bg-background p-4" disabled={delivering}>
              <legend className="sr-only">Choose a question to send</legend>
              <div className="flex flex-wrap items-baseline justify-between gap-2">
                <p className="font-semibold">Choose a question to send</p>
                <p className="text-sm text-muted-foreground">It opens for every connected student straight away.</p>
              </div>

              {loading ? (
                <p role="status" className="mt-3 text-sm text-muted-foreground">Loading ready questions…</p>
              ) : questions.length === 0 ? (
                <p className="mt-3 text-sm text-muted-foreground">
                  No questions are ready for this session. Mark some ready to send in the material review.
                </p>
              ) : (
                <ul className="mt-3 max-h-80 space-y-2 overflow-y-auto pr-1">
                  {questions.map((question) => {
                    const selected = question.id === selectedQuestionId
                    return (
                      <li key={question.id}>
                        <label
                          className={cn(
                            'flex cursor-pointer gap-3 rounded-md border px-3 py-2.5 transition-colors',
                            selected ? 'border-primary bg-accent' : 'border-border bg-card hover:border-input',
                          )}
                        >
                          <input
                            type="radio"
                            name="manual-question"
                            value={question.id}
                            checked={selected}
                            onChange={() => setSelectedQuestionId(question.id)}
                            className="mt-1 accent-[var(--primary)]"
                          />
                          <span className="min-w-0">
                            <span className={cn('block text-sm', selected && 'font-semibold text-accent-foreground')}>
                              {question.prompt}
                            </span>
                            {(question.sourceSlide !== null || (question.options?.length ?? 0) > 0) && (
                              <span className="mt-0.5 block text-xs text-muted-foreground">
                                {[
                                  question.options?.length ? `${question.options.length} options` : null,
                                  question.sourceSlide !== null ? `slide ${question.sourceSlide}` : null,
                                ]
                                  .filter(Boolean)
                                  .join(', ')}
                              </span>
                            )}
                          </span>
                        </label>
                      </li>
                    )
                  })}
                </ul>
              )}

              {error && (
                <p role="alert" className="mt-3 text-sm text-critical">
                  {error}
                </p>
              )}

              <div className="mt-4 flex gap-2">
                <button
                  type="button"
                  disabled={!enabled || delivering || !selectedQuestionId}
                  onClick={() => void triggerSelectedQuestion()}
                  className={buttonStyles()}
                >
                  <Send size={15} aria-hidden />
                  {delivering ? 'Sending…' : 'Send it'}
                </button>
                <button
                  type="button"
                  onClick={() => {
                    setSelectorOpen(false)
                    setError(null)
                  }}
                  className={buttonStyles({ intent: 'quiet' })}
                >
                  Cancel
                </button>
              </div>
            </fieldset>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  )
}
