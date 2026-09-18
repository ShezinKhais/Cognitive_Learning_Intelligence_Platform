import { useCallback, useEffect, useMemo, useState } from 'react'
import { useParams } from 'react-router'

import {
  ApiError,
  bulkReviewQuestions,
  listQuestions,
  reviewQuestion,
  type Difficulty,
  type Question,
  type QuestionStatus,
} from '../api'

const PAGE_SIZE = 50

type LoadState =
  | { status: 'loading' }
  | { status: 'ready'; questions: Question[]; total: number; offset: number; loadingMore: boolean }
  | { status: 'error'; message: string }

const STATUS_TONE: Record<QuestionStatus, 'success' | 'warning' | 'critical' | 'muted'> = {
  draft: 'muted',
  approved: 'success',
  rejected: 'critical',
  staged: 'success',
  delivered: 'success',
}

const STATUS_LABEL: Record<QuestionStatus, string> = {
  draft: 'Draft',
  approved: 'Approved',
  rejected: 'Rejected',
  staged: 'Staged',
  delivered: 'Delivered',
}

export default function QuestionReview() {
  const { materialId } = useParams<{ materialId: string }>()
  const [state, setState] = useState<LoadState>({ status: 'loading' })
  const [selected, setSelected] = useState<Set<string>>(new Set())
  const [bulkBusy, setBulkBusy] = useState(false)
  const [bulkError, setBulkError] = useState<string | null>(null)

  useEffect(() => {
    if (!materialId) return
    let cancelled = false

    // Reset to loading and clear the selection before the new material's
    // request even starts -- otherwise the previous material's questions
    // (and a selection referring to ids that don't exist for this material)
    // stay on screen until the new page arrives, which reads as the wrong
    // material's queue for however long the request takes.
    setState({ status: 'loading' })
    setSelected(new Set())
    setBulkError(null)

    listQuestions(materialId, PAGE_SIZE, 0)
      .then((page) => {
        if (!cancelled) {
          setState({
            status: 'ready',
            questions: page.items,
            total: page.total,
            offset: page.items.length,
            loadingMore: false,
          })
        }
      })
      .catch((err) => {
        if (cancelled) return
        const message = err instanceof ApiError ? err.message : 'Could not load questions.'
        setState({ status: 'error', message })
      })

    return () => {
      cancelled = true
    }
  }, [materialId])

  const loadMore = useCallback(async () => {
    if (!materialId || state.status !== 'ready' || state.loadingMore) return
    setState({ ...state, loadingMore: true })
    try {
      const page = await listQuestions(materialId, PAGE_SIZE, state.offset)
      setState((prev) =>
        prev.status === 'ready'
          ? {
              status: 'ready',
              questions: [...prev.questions, ...page.items],
              total: page.total,
              offset: prev.offset + page.items.length,
              loadingMore: false,
            }
          : prev,
      )
    } catch (err) {
      setBulkError(err instanceof ApiError ? err.message : 'Could not load more questions.')
      setState((prev) => (prev.status === 'ready' ? { ...prev, loadingMore: false } : prev))
    }
  }, [materialId, state])

  const draftQuestions = useMemo(
    () => (state.status === 'ready' ? state.questions.filter((q) => q.status === 'draft') : []),
    [state],
  )

  function updateQuestion(updated: Question) {
    setState((prev) =>
      prev.status === 'ready'
        ? {
            ...prev,
            questions: prev.questions.map((q) => (q.id === updated.id ? updated : q)),
          }
        : prev,
    )
    // A question that just changed status (via its own Approve/Reject/Save)
    // is no longer eligible for bulk selection regardless of what it was
    // before -- drop it from `selected` so a stale checkbox state can never
    // cause "Approve selected" to act on a question that isn't draft
    // anymore (this is what let rejecting a question, then bulk-approving,
    // silently re-approve it).
    setSelected((prev) => {
      if (!prev.has(updated.id)) return prev
      const next = new Set(prev)
      next.delete(updated.id)
      return next
    })
  }

  function toggleSelected(id: string) {
    setSelected((prev) => {
      const next = new Set(prev)
      if (next.has(id)) next.delete(id)
      else next.add(id)
      return next
    })
  }

  function selectAllDrafts() {
    setSelected(new Set(draftQuestions.map((q) => q.id)))
  }

  async function handleApproveAll() {
    if (!materialId || selected.size === 0) return
    // Belt-and-braces on top of updateQuestion already pruning `selected`:
    // only ever send ids that are still draft in the latest state, so a
    // stale selection can never reach the bulk endpoint even if some other
    // code path added to `selected` without going through toggleSelected.
    const draftIds =
      state.status === 'ready'
        ? state.questions.filter((q) => q.status === 'draft' && selected.has(q.id)).map((q) => q.id)
        : []
    if (draftIds.length === 0) return

    setBulkBusy(true)
    setBulkError(null)
    try {
      const result = await bulkReviewQuestions(materialId, draftIds, 'approved')
      const byId = new Map(result.updated.map((q) => [q.id, q]))
      setState((prev) =>
        prev.status === 'ready'
          ? { ...prev, questions: prev.questions.map((q) => byId.get(q.id) ?? q) }
          : prev,
      )
      setSelected(new Set())
      if (result.skipped_ids.length > 0) {
        setBulkError(
          `${result.updated.length} approved, ${result.skipped_ids.length} skipped ` +
            `(already reviewed elsewhere or no longer eligible).`,
        )
      }
    } catch (err) {
      setBulkError(err instanceof ApiError ? err.message : 'Bulk approve failed.')
    } finally {
      setBulkBusy(false)
    }
  }

  if (!materialId) {
    return <main className="p-8 text-critical">No material selected.</main>
  }

  return (
    <main className="min-h-screen p-8">
      <div className="mx-auto max-w-3xl">
        <div className="flex items-start justify-between gap-4">
          <div>
            <h1 className="text-xl font-bold text-foreground">Question review</h1>
            <p className="mt-1 text-sm text-muted-foreground">
              Approve, edit or reject generated questions. Nothing reaches a student until it's
              approved here.
            </p>
          </div>
          {draftQuestions.length > 0 && (
            <div className="flex shrink-0 items-center gap-2">
              <button
                type="button"
                onClick={selectAllDrafts}
                disabled={selected.size === draftQuestions.length}
                className="rounded-lg border border-border px-4 py-2 text-sm font-medium disabled:opacity-50"
              >
                Select all ({draftQuestions.length})
              </button>
              <button
                type="button"
                onClick={handleApproveAll}
                disabled={selected.size === 0 || bulkBusy}
                className="rounded-lg bg-primary px-4 py-2 text-sm font-medium text-primary-foreground disabled:opacity-50"
              >
                {bulkBusy ? 'Approving...' : `Approve selected (${selected.size})`}
              </button>
            </div>
          )}
        </div>

        {bulkError && (
          <div className="mt-4 rounded-lg bg-critical/10 p-4 text-sm text-critical">
            {bulkError}
          </div>
        )}

        {state.status === 'loading' && (
          <p className="mt-8 text-sm text-muted-foreground">Loading questions...</p>
        )}

        {state.status === 'error' && (
          <div className="mt-8 rounded-lg bg-critical/10 p-4 text-sm text-critical">
            {state.message}
          </div>
        )}

        {state.status === 'ready' && state.questions.length === 0 && (
          <p className="mt-8 text-sm text-muted-foreground">
            No questions have been generated for this material yet.
          </p>
        )}

        {state.status === 'ready' && state.questions.length > 0 && (
          <>
            <div className="mt-8 space-y-4">
              {state.questions.map((question) => (
                <QuestionCard
                  key={question.id}
                  materialId={materialId}
                  question={question}
                  selected={selected.has(question.id)}
                  onToggleSelected={() => toggleSelected(question.id)}
                  onUpdated={updateQuestion}
                />
              ))}
            </div>

            {state.questions.length < state.total && (
              <div className="mt-6 flex flex-col items-center gap-2">
                <p className="text-xs text-muted-foreground">
                  Showing {state.questions.length} of {state.total}
                </p>
                <button
                  type="button"
                  onClick={loadMore}
                  disabled={state.loadingMore}
                  className="rounded-lg border border-border px-4 py-2 text-sm font-medium disabled:opacity-50"
                >
                  {state.loadingMore ? 'Loading...' : 'Load more'}
                </button>
              </div>
            )}
          </>
        )}
      </div>
    </main>
  )
}

function QuestionCard({
  materialId,
  question,
  selected,
  onToggleSelected,
  onUpdated,
}: {
  materialId: string
  question: Question
  selected: boolean
  onToggleSelected: () => void
  onUpdated: (q: Question) => void
}) {
  const isMcq = question.type === 'mcq'

  const [editing, setEditing] = useState(false)
  const [prompt, setPrompt] = useState(question.prompt)
  const [options, setOptions] = useState(question.options ?? [])
  const [correctOption, setCorrectOption] = useState(question.correct_option ?? 0)
  const [difficulty, setDifficulty] = useState<Difficulty>(question.difficulty)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const tone = STATUS_TONE[question.status]
  const toneClass = {
    success: 'bg-success/10 text-success',
    warning: 'bg-warning/10 text-warning',
    critical: 'bg-critical/10 text-critical',
    muted: 'bg-muted text-muted-foreground',
  }[tone]

  function startEditing() {
    // Reset the draft fields from the current question every time editing
    // opens, not just on mount: without this, cancelling out of an edit
    // and reopening it kept whatever was typed before cancelling, since
    // useState's initial value only applies once per component instance.
    setPrompt(question.prompt)
    setOptions(question.options ?? [])
    setCorrectOption(question.correct_option ?? 0)
    setDifficulty(question.difficulty)
    setError(null)
    setEditing(true)
  }

  function cancelEditing() {
    setPrompt(question.prompt)
    setOptions(question.options ?? [])
    setCorrectOption(question.correct_option ?? 0)
    setDifficulty(question.difficulty)
    setError(null)
    setEditing(false)
  }

  async function act(
    status: QuestionStatus,
    extra?: { prompt?: string; options?: string[]; correct_option?: number; difficulty?: Difficulty },
  ) {
    setBusy(true)
    setError(null)
    try {
      const updated = await reviewQuestion(materialId, question.id, { status, ...extra })
      onUpdated(updated)
      setEditing(false)
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Action failed.')
    } finally {
      setBusy(false)
    }
  }

  function saveAndApprove() {
    // Only send MCQ fields for an actual MCQ. A free-text question has no
    // options or correct_option, and submitting options=[] / correct_
    // option=0 for one would silently turn it into what looks like an MCQ
    // with an empty option list.
    act(
      'approved',
      isMcq
        ? { prompt, options, correct_option: correctOption, difficulty }
        : { prompt, difficulty },
    )
  }

  return (
    <div className="rounded-xl border border-border bg-card p-5">
      <div className="flex items-start justify-between gap-3">
        <div className="flex items-start gap-3">
          {question.status === 'draft' && (
            <input
              type="checkbox"
              checked={selected}
              onChange={onToggleSelected}
              className="mt-1"
              aria-label="Select for bulk approve"
            />
          )}
          <div>
            <span className={`inline-block rounded-full px-2.5 py-0.5 text-xs font-medium ${toneClass}`}>
              {STATUS_LABEL[question.status]}
            </span>
            {question.topic && (
              <span className="ml-2 text-xs text-muted-foreground">{question.topic}</span>
            )}
          </div>
        </div>
        {question.source_slide != null && (
          <span className="shrink-0 text-xs text-muted-foreground">
            Slide {question.source_slide}
          </span>
        )}
      </div>

      <div className="mt-3">
        {editing ? (
          <textarea
            value={prompt}
            onChange={(e) => setPrompt(e.target.value)}
            className="w-full rounded-lg border border-border bg-background p-2 text-sm"
            rows={2}
            aria-label="Question prompt"
          />
        ) : (
          <p className="text-sm text-card-foreground">{question.prompt}</p>
        )}
      </div>

      {editing && (
        <div className="mt-2 flex items-center gap-2 text-xs">
          <span className="text-muted-foreground">Difficulty</span>
          {(['easy', 'medium', 'hard'] as const).map((level) => (
            <button
              key={level}
              type="button"
              onClick={() => setDifficulty(level)}
              className={`rounded-full px-2.5 py-0.5 font-medium ${
                difficulty === level
                  ? 'bg-primary text-primary-foreground'
                  : 'bg-muted text-muted-foreground'
              }`}
            >
              {level}
            </button>
          ))}
        </div>
      )}

      {isMcq && (
        <ul className="mt-3 space-y-1.5">
          {(editing ? options : question.options ?? []).map((opt, i) => (
            <li key={i} className="flex items-center gap-2 text-sm">
              {editing ? (
                <>
                  <input
                    type="radio"
                    name={`correct-${question.id}`}
                    checked={correctOption === i}
                    onChange={() => setCorrectOption(i)}
                    aria-label={`Mark "${opt || `option ${i + 1}`}" as the correct answer`}
                  />
                  <input
                    value={opt}
                    onChange={(e) => {
                      const next = [...options]
                      next[i] = e.target.value
                      setOptions(next)
                    }}
                    className="flex-1 rounded border border-border bg-background px-2 py-1 text-sm"
                    aria-label={`Option ${i + 1} text`}
                  />
                </>
              ) : (
                <span
                  className={i === question.correct_option ? 'font-medium text-success' : ''}
                >
                  {i === question.correct_option ? '\u2713 ' : ''}
                  {opt}
                </span>
              )}
            </li>
          ))}
        </ul>
      )}

      {question.source_excerpt && (
        <p className="mt-3 rounded-lg bg-muted p-3 text-xs text-muted-foreground">
          "{question.source_excerpt}"
        </p>
      )}

      {error && <p className="mt-2 text-xs text-critical">{error}</p>}

      <div className="mt-4 flex flex-wrap items-center gap-2">
        {editing ? (
          <>
            <button
              type="button"
              disabled={busy}
              onClick={saveAndApprove}
              className="rounded-lg bg-primary px-3 py-1.5 text-xs font-medium text-primary-foreground disabled:opacity-50"
            >
              Save and approve
            </button>
            <button
              type="button"
              disabled={busy}
              onClick={cancelEditing}
              className="rounded-lg border border-border px-3 py-1.5 text-xs font-medium"
            >
              Cancel
            </button>
          </>
        ) : (
          <>
            {question.status === 'draft' && (
              <>
                <button
                  type="button"
                  disabled={busy}
                  onClick={() => act('approved')}
                  className="rounded-lg bg-success px-3 py-1.5 text-xs font-medium text-success-foreground disabled:opacity-50"
                >
                  Approve
                </button>
                <button
                  type="button"
                  disabled={busy}
                  onClick={startEditing}
                  className="rounded-lg border border-border px-3 py-1.5 text-xs font-medium"
                >
                  Edit
                </button>
                <button
                  type="button"
                  disabled={busy}
                  onClick={() => act('rejected')}
                  className="rounded-lg border border-critical/30 px-3 py-1.5 text-xs font-medium text-critical"
                >
                  Reject
                </button>
                <button
                  type="button"
                  disabled
                  title="Regeneration is being built as a follow-up once the generation module lands in main (agreed with AI 1)"
                  className="rounded-lg border border-border px-3 py-1.5 text-xs font-medium opacity-40"
                >
                  Regenerate
                </button>
              </>
            )}
            {question.status === 'approved' && (
              <button
                type="button"
                disabled={busy}
                onClick={() => act('staged')}
                className="rounded-lg bg-primary px-3 py-1.5 text-xs font-medium text-primary-foreground disabled:opacity-50"
              >
                Stage for delivery
              </button>
            )}
          </>
        )}
      </div>
    </div>
  )
}
