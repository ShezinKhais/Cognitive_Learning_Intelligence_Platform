import { useState } from 'react'

import { ApiError } from '../../api'
import {
  deliverQuestion,
  loadStagedQuestions,
  type StagedQuestion,
} from './questionActions'

interface ManualQuestionTriggerProps {
  sessionId: string | undefined
  enabled: boolean
}

export default function ManualQuestionTrigger({
  sessionId,
  enabled,
}: ManualQuestionTriggerProps) {
  const [
    questions,
    setQuestions,
  ] = useState<StagedQuestion[]>([])

  const [
    selectedQuestionId,
    setSelectedQuestionId,
  ] = useState('')

  const [
    selectorOpen,
    setSelectorOpen,
  ] = useState(false)

  const [
    loading,
    setLoading,
  ] = useState(false)

  const [
    delivering,
    setDelivering,
  ] = useState(false)

  const [
    error,
    setError,
  ] = useState<string | null>(null)

  async function openSelector() {
    if (
      !enabled ||
      !sessionId
    ) {
      return
    }

    setSelectorOpen(true)
    setError(null)
    setLoading(true)

    try {
      const staged =
        await loadStagedQuestions()

      setQuestions(staged)

      setSelectedQuestionId(
        staged[0]?.id ?? '',
      )
    } catch (caught) {
      if (
        caught instanceof ApiError
      ) {
        setError(caught.message)
      } else {
        setError(
          'Staged questions could not be loaded.',
        )
      }
    } finally {
      setLoading(false)
    }
  }

  async function triggerSelectedQuestion() {
    if (
      !enabled ||
      !sessionId ||
      !selectedQuestionId
    ) {
      return
    }

    setError(null)
    setDelivering(true)

    try {
      await deliverQuestion(
        sessionId,
        selectedQuestionId,
      )

      setQuestions(
        (current) =>
          current.filter(
            (question) =>
              question.id !==
              selectedQuestionId,
          ),
      )

      setSelectedQuestionId('')
      setSelectorOpen(false)
    } catch (caught) {
      if (
        caught instanceof ApiError
      ) {
        setError(caught.message)
      } else {
        setError(
          'The question could not be delivered.',
        )
      }
    } finally {
      setDelivering(false)
    }
  }

  const selectedQuestion =
    questions.find(
      (question) =>
        question.id ===
        selectedQuestionId,
    ) ?? null

  if (!selectorOpen) {
    return (
      <button
        type="button"
        disabled={!enabled}
        onClick={() =>
          void openSelector()
        }
        className="mt-5 rounded-md bg-primary px-4 py-2 text-sm font-medium text-primary-foreground disabled:cursor-not-allowed disabled:opacity-50"
      >
        Send checkpoint now
      </button>
    )
  }

  return (
    <div className="mt-5 rounded-lg border border-border bg-background p-4">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h3 className="font-semibold">
            Send checkpoint now
          </h3>

          <p className="mt-1 text-sm text-muted-foreground">
            Automatic checkpoints normally run in the background.
            Use this only when you want to send an approved question immediately.
          </p>
        </div>

        <button
          type="button"
          disabled={delivering}
          onClick={() => {
            setSelectorOpen(false)
            setError(null)
          }}
          className="rounded-md border border-border px-3 py-1.5 text-sm disabled:opacity-50"
        >
          Cancel
        </button>
      </div>

      {loading ? (
        <p className="mt-4 text-sm text-muted-foreground">
          Loading staged questions...
        </p>
      ) : questions.length === 0 ? (
        <p className="mt-4 text-sm text-muted-foreground">
          No staged questions are currently
          available.
        </p>
      ) : (
        <>
          <label
            htmlFor="manual-question"
            className="mt-4 block text-sm font-medium"
          >
            Question
          </label>

          <select
            id="manual-question"
            value={selectedQuestionId}
            disabled={delivering}
            onChange={(event) =>
              setSelectedQuestionId(
                event.target.value,
              )
            }
            className="mt-2 w-full rounded-md border border-border bg-card px-3 py-2 text-sm"
          >
            {questions.map(
              (question) => (
                <option
                  key={question.id}
                  value={question.id}
                >
                  {question.prompt}
                </option>
              ),
            )}
          </select>

          {selectedQuestion && (
            <div className="mt-4 rounded-md border border-border p-4">
              <p className="font-medium">
                {
                  selectedQuestion.prompt
                }
              </p>

              <p className="mt-2 text-xs text-muted-foreground">
                Material:{' '}
                {
                  selectedQuestion.materialName
                }
              </p>

              {selectedQuestion.sourceSlide !==
                null && (
                <p className="mt-1 text-xs text-muted-foreground">
                  Source slide:{' '}
                  {
                    selectedQuestion.sourceSlide
                  }
                </p>
              )}

              {selectedQuestion.options &&
                selectedQuestion.options
                  .length > 0 && (
                  <ul className="mt-3 space-y-1 text-sm">
                    {selectedQuestion.options.map(
                      (
                        option,
                        index,
                      ) => (
                        <li
                          key={`${index}-${option}`}
                        >
                          <span className="font-semibold">
                            {String.fromCharCode(
                              65 + index,
                            )}
                            .
                          </span>{' '}
                          {option}
                        </li>
                      ),
                    )}
                  </ul>
                )}
            </div>
          )}

          <button
            type="button"
            disabled={
              !enabled ||
              delivering ||
              !selectedQuestionId
            }
            onClick={() =>
              void triggerSelectedQuestion()
            }
            className="mt-4 rounded-md bg-primary px-4 py-2 text-sm font-medium text-primary-foreground disabled:cursor-not-allowed disabled:opacity-50"
          >
            {delivering
              ? 'Delivering...'
              : 'Send checkpoint now'}
          </button>
        </>
      )}

      {error && (
        <div
          role="alert"
          className="mt-4 rounded-md border border-destructive/40 bg-destructive/10 px-4 py-3 text-sm text-destructive"
        >
          {error}
        </div>
      )}
    </div>
  )
}
