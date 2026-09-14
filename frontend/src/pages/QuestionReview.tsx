import { useEffect, useMemo, useState } from 'react'
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

type LoadState =
  | { status: 'loading' }
  | { status: 'ready'; questions: Question[] }
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

    listQuestions(materialId)
      .then((page) => {
        if (!cancelled) setState({ status: 'ready', questions: page.items })
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

  const draftQuestions = useMemo(
    () => (state.status === 'ready' ? state.questions.filter((q) => q.status === 'draft') : []),
    [state],
  )

  function updateQuestion(updated: Question) {
    setState((prev) =>
      prev.status === 'ready'
        ? {
            status: 'ready',
            questions: prev.questions.map((q) => (q.id === updated.id ? updated : q)),
          }
        : prev,
    )
  }

  function toggleSelected(id: string) {
    setSelected((prev) => {
      const next = new Set(prev)
      if (next.has(id)) next.delete(id)
      else next.add(id)
      return next
    })
  }

  async function handleApproveAll() {
    if (!materialId || selected.size === 0) return
    setBulkBusy(true)
    setBulkError(null)
    try {
      const updated = await bulkReviewQuestions(materialId, [...selected], 'approved')
      const byId = new Map(updated.map((q) => [q.id, q]))
      setState((prev) =>
        prev.status === 'ready'
          ? { status: 'ready', questions: prev.questions.map((q) => byId.get(q.id) ?? q) }
          : prev,
      )
      setSelected(new Set())
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
            <button
              type="button"
              onClick={handleApproveAll}
              disabled={selected.size === 0 || bulkBusy}
              className="shrink-0 rounded-lg bg-primary px-4 py-2 text-sm font-medium text-primary-foreground disabled:opacity-50"
            >
              {bulkBusy ? 'Approving…' : `Approve selected (${selected.size})`}
            </button>
          )}
        </div>

        {bulkError && (
          <div className="mt-4 rounded-lg bg-critical/10 p-4 text-sm text-critical">
            {bulkError}
          </div>
        )}

        {state.status === 'loading' && (
          <p className="mt-8 text-sm text-muted-foreground">Loading questions…</p>
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

      {question.type === 'mcq' && (
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
                  />
                  <input
                    value={opt}
                    onChange={(e) => {
                      const next = [...options]
                      next[i] = e.target.value
                      setOptions(next)
                    }}
                    className="flex-1 rounded border border-border bg-background px-2 py-1 text-sm"
                  />
                </>
              ) : (
                <span
                  className={i === question.correct_option ? 'font-medium text-success' : ''}
                >
                  {i === question.correct_option ? '✓ ' : ''}
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
              onClick={() =>
                act('approved', { prompt, options, correct_option: correctOption, difficulty })
              }
              className="rounded-lg bg-primary px-3 py-1.5 text-xs font-medium text-primary-foreground disabled:opacity-50"
            >
              Save and approve
            </button>
            <button
              type="button"
              disabled={busy}
              onClick={() => setEditing(false)}
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
                  onClick={() => setEditing(true)}
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
                  title="Regeneration needs a backend route that doesn't exist in the frozen Phase 2 contract yet (see AI 1)"
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
