import { useCallback, useEffect, useMemo, useState, type KeyboardEvent } from 'react'
import { Check } from 'lucide-react'
import { useParams } from 'react-router'

import {
  ApiError,
  bulkReviewQuestions,
  listQuestions,
  regenerateQuestion,
  reviewQuestion,
  type Difficulty,
  type Question,
  type QuestionStatus,
  type ReviewDecision,
} from '../api'
import { buttonStyles } from '../components/ui/button'
import SegmentedTabs from '../components/ui/SegmentedTabs'
import { useToast } from '../components/ui/toast'
import { EmptyState, PageBody, PageHeader, Tag, type Tone, SkeletonRows } from '../components/ui/primitives'
import { getMaterial } from '../features/materials/materialApi'
import type { Material } from '../features/materials/types'
import { sourceName } from '../features/materials/upload'
import {
  countByFilter,
  FILTERS,
  inFilter,
  shortcutFor,
  startingFilter,
  type ReviewFilter,
} from '../features/review/reviewState'

const PAGE_SIZE = 50

type LoadState =
  | { status: 'loading' }
  | { status: 'ready'; questions: Question[]; total: number; offset: number; loadingMore: boolean }
  | { status: 'error'; message: string }

const STATUS_TONE: Record<QuestionStatus, Tone> = {
  draft: 'neutral',
  approved: 'info',
  rejected: 'poor',
  staged: 'good',
  delivered: 'good',
}

const STATUS_LABEL: Record<QuestionStatus, string> = {
  draft: 'To review',
  approved: 'Approved',
  rejected: 'Rejected',
  staged: 'Ready to send',
  delivered: 'Sent',
}

const DONE: Record<ReviewDecision, string> = {
  draft: 'Back to draft',
  approved: 'Approved',
  rejected: 'Rejected',
  staged: 'Ready to send',
}

export default function QuestionReview() {
  const { materialId } = useParams<{ materialId: string }>()
  const [state, setState] = useState<LoadState>({ status: 'loading' })
  const [selected, setSelected] = useState<Set<string>>(new Set())
  const [bulkBusy, setBulkBusy] = useState(false)
  const notify = useToast()
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
      // A regenerated draft is shown as soon as it exists but sorts last on
      // the server, so a later page can bring it back a second time.
      setState((prev) =>
        prev.status === 'ready'
          ? {
              status: 'ready',
              questions: [
                ...prev.questions,
                ...page.items.filter((item) => !prev.questions.some((q) => q.id === item.id)),
              ],
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

  // The replaced draft stays in the list, now rejected, with its
  // replacement directly after it, so the lecturer sees what changed.
  function replaceQuestion(replacedId: string, fresh: Question) {
    setState((prev) =>
      prev.status === 'ready'
        ? {
            ...prev,
            total: prev.total + 1,
            questions: prev.questions.flatMap((q) =>
              q.id === replacedId ? [{ ...q, status: 'rejected' as const }, fresh] : [q],
            ),
          }
        : prev,
    )
    setSelected((prev) => {
      if (!prev.has(replacedId)) return prev
      const next = new Set(prev)
      next.delete(replacedId)
      return next
    })
  }

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
      if (result.updated.length > 0) notify(`${result.updated.length} approved`)
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

  // Which questions are on screen, and which one the keyboard is on.
  const questions = state.status === 'ready' ? state.questions : []
  const counts = countByFilter(questions)
  const [filter, setFilter] = useState<ReviewFilter | null>(null)
  const shownFilter = filter ?? startingFilter(questions)
  const shown = questions.filter((question) => inFilter(question, shownFilter))
  const approvedIds = questions.filter((question) => question.status === 'approved').map((question) => question.id)

  const [material, setMaterial] = useState<Material | null>(null)
  useEffect(() => {
    if (!materialId) return
    getMaterial(materialId).then(setMaterial, () => undefined)
  }, [materialId])
  const source = material ? sourceName(material) : 'Page'

  async function stageAllApproved() {
    if (!materialId || approvedIds.length === 0) return
    setBulkBusy(true)
    setBulkError(null)
    try {
      const result = await bulkReviewQuestions(materialId, approvedIds, 'staged')
      result.updated.forEach(updateQuestion)
      notify(`${result.updated.length} ready to send`)
    } catch (err) {
      setBulkError(err instanceof ApiError ? err.message : 'Could not make the approved questions ready.')
    } finally {
      setBulkBusy(false)
    }
  }

  if (!materialId) {
    return <PageBody><p className="text-critical">No material selected.</p></PageBody>
  }

  const reviewed = counts.all - counts.review

  return (
    <>
      <PageHeader
        title="Review questions"
        description={
          <>
            {material ? <strong className="font-semibold text-foreground">{material.filename}</strong> : 'This material'}
            . A question reaches a class only once you approve it and make it ready to send.
          </>
        }
        back={{ to: '/lecturer/materials', label: 'Materials' }}
      >
        {counts.all > 0 && (
          <div className="mt-4 max-w-md">
            <div className="flex h-1.5 overflow-hidden rounded-full bg-muted" aria-hidden>
              <span className="bg-success transition-[width] duration-500" style={{ width: `${(counts.staged / counts.all) * 100}%` }} />
              <span className="bg-success/50 transition-[width] duration-500" style={{ width: `${(counts.approved / counts.all) * 100}%` }} />
              <span className="bg-critical/50 transition-[width] duration-500" style={{ width: `${(counts.rejected / counts.all) * 100}%` }} />
            </div>
            <p className="mt-1.5 text-sm text-muted-foreground">
              {reviewed} of {counts.all} decided, {counts.staged} ready to send
            </p>
          </div>
        )}
      </PageHeader>

      <PageBody>
        <div className="max-w-3xl">
          {state.status === 'ready' && counts.all > 0 && (
            <div className="mb-5 flex flex-wrap items-center justify-between gap-3">
              <SegmentedTabs
                label="Show"
                value={shownFilter}
                onChange={setFilter}
                className="flex-wrap"
                segments={FILTERS.map(({ key, label }) => ({
                  key,
                  label: (
                    <>
                      {label} <span className={shownFilter === key ? 'opacity-80' : 'text-muted-foreground'}>{counts[key]}</span>
                    </>
                  ),
                }))}
              />
              <div className="flex flex-wrap gap-2">
                {shownFilter === 'review' && draftQuestions.length > 0 && (
                  <>
                    <button
                      type="button"
                      onClick={selectAllDrafts}
                      disabled={selected.size === draftQuestions.length}
                      className={buttonStyles({ intent: 'quiet' })}
                    >
                      Select all
                    </button>
                    <button
                      type="button"
                      onClick={handleApproveAll}
                      disabled={selected.size === 0 || bulkBusy}
                      className={buttonStyles()}
                    >
                      {bulkBusy ? 'Approving…' : selected.size ? `Approve ${selected.size} selected` : 'Approve selected'}
                    </button>
                  </>
                )}
                {shownFilter === 'approved' && approvedIds.length > 0 && (
                  <button type="button" onClick={stageAllApproved} disabled={bulkBusy} className={buttonStyles()}>
                    {bulkBusy ? 'Working…' : `Make all ${approvedIds.length} ready to send`}
                  </button>
                )}
              </div>
            </div>
          )}

          {bulkError && (
            <p role="alert" className="mb-4 rounded-md border border-critical/30 bg-critical/5 px-4 py-3 text-sm text-critical">
              {bulkError}
            </p>
          )}

          {state.status === 'loading' && <SkeletonRows label="Loading questions" rows={4} />}
          {state.status === 'error' && (
            <p role="alert" className="rounded-md border border-critical/30 bg-critical/5 px-4 py-3 text-critical">{state.message}</p>
          )}
          {state.status === 'ready' && counts.all === 0 && (
            <EmptyState title="No questions yet">
              Questions appear here once the material has been processed. If it has, it may have had too little text
              to draw questions from.
            </EmptyState>
          )}
          {state.status === 'ready' && counts.all > 0 && shown.length === 0 && (
            <EmptyState title={shownFilter === 'review' ? 'Everything is decided' : 'Nothing here'}>
              {shownFilter === 'review'
                ? 'Every question has been approved or rejected. Make the approved ones ready to send under Approved.'
                : 'No question is in this list.'}
            </EmptyState>
          )}

          {shown.length > 0 && (
            <>
              <p className="mb-3 hidden text-xs text-muted-foreground sm:block">
                Shortcuts on a selected question: J and K to move, A approve, R reject, E edit, S make ready.
              </p>
              <ol className="space-y-3" onKeyDown={moveFocus}>
                {shown.map((question) => (
                  <li key={question.id}>
                    <QuestionCard
                      materialId={materialId}
                      question={question}
                      source={source}
                      selected={selected.has(question.id)}
                      onToggleSelected={() => toggleSelected(question.id)}
                      onUpdated={updateQuestion}
                      onReplaced={replaceQuestion}
                    />
                  </li>
                ))}
              </ol>
            </>
          )}

          {state.status === 'ready' && state.questions.length < state.total && (
            <div className="mt-6 flex flex-col items-center gap-2">
              <p className="text-xs text-muted-foreground">
                Showing {state.questions.length} of {state.total}
              </p>
              <button type="button" onClick={loadMore} disabled={state.loadingMore} className={buttonStyles({ intent: 'secondary' })}>
                {state.loadingMore ? 'Loading…' : 'Load more'}
              </button>
            </div>
          )}
        </div>
      </PageBody>
    </>
  )
}

/** J and K (or the arrow keys) move between questions. */
function moveFocus(event: KeyboardEvent<HTMLOListElement>) {
  const action = shortcutFor(event.key)
  if (action !== 'next' && action !== 'previous') return
  if ((event.target as HTMLElement).closest('input, textarea')) return
  const cards = [...event.currentTarget.querySelectorAll<HTMLElement>('[data-question-card]')]
  const index = cards.findIndex((card) => card.contains(document.activeElement))
  const next = cards[action === 'next' ? Math.min(cards.length - 1, index + 1) : Math.max(0, index - 1)]
  if (next) {
    event.preventDefault()
    next.focus()
  }
}

function QuestionCard({
  materialId,
  question,
  source,
  selected,
  onToggleSelected,
  onUpdated,
  onReplaced,
}: {
  materialId: string
  question: Question
  source: 'Page' | 'Slide'
  selected: boolean
  onToggleSelected: () => void
  onUpdated: (q: Question) => void
  onReplaced: (replacedId: string, fresh: Question) => void
}) {
  const isMcq = question.type === 'mcq'

  const [editing, setEditing] = useState(false)
  const [prompt, setPrompt] = useState(question.prompt)
  const [options, setOptions] = useState(question.options ?? [])
  const [correctOption, setCorrectOption] = useState(question.correct_option ?? 0)
  const [difficulty, setDifficulty] = useState<Difficulty>(question.difficulty)
  const [busy, setBusy] = useState(false)
  const notify = useToast()
  const [error, setError] = useState<string | null>(null)


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

  async function regenerate() {
    setBusy(true)
    setError(null)
    try {
      const fresh = await regenerateQuestion(materialId, question.id)
      onReplaced(question.id, fresh)
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Could not regenerate this question.')
    } finally {
      setBusy(false)
    }
  }

  async function act(
    status: ReviewDecision,
    extra?: { prompt?: string; options?: string[]; correct_option?: number; difficulty?: Difficulty },
  ) {
    setBusy(true)
    setError(null)
    try {
      const updated = await reviewQuestion(materialId, question.id, { status, ...extra })
      onUpdated(updated)
      setEditing(false)
      notify(DONE[status])
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

  function onShortcut(event: KeyboardEvent<HTMLElement>) {
    if (editing || busy || event.target !== event.currentTarget) return
    const action = shortcutFor(event.key)
    if (action === 'approve' && question.status === 'draft') void act('approved')
    else if (action === 'reject' && question.status === 'draft') void act('rejected')
    else if (action === 'edit' && question.status === 'draft') startEditing()
    else if (action === 'stage' && question.status === 'approved') void act('staged')
    else return
    event.preventDefault()
  }

  return (
    <article
      data-question-card
      tabIndex={0}
      onKeyDown={onShortcut}
      aria-label={question.prompt}
      className={`rounded-lg border bg-card p-5 outline-none transition-[border-color,box-shadow] focus-visible:border-primary focus-visible:shadow-[0_0_0_3px_var(--accent)] ${
        question.status === 'rejected' ? 'border-border opacity-70' : 'border-border'
      }`}
    >
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
            <Tag tone={STATUS_TONE[question.status]}>{STATUS_LABEL[question.status]}</Tag>
            {question.topic && <span className="ml-2 text-sm text-muted-foreground">{question.topic}</span>}
          </div>
        </div>
        {question.source_slide != null && (
          <span className="shrink-0 text-sm text-muted-foreground">
            {source} {question.source_slide}
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
          <p className="text-[1.05rem] font-semibold">{question.prompt}</p>
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
                  className={
                    i === question.correct_option
                      ? 'inline-flex items-center gap-1.5 font-medium text-success'
                      : 'pl-[1.375rem]'
                  }
                >
                  {i === question.correct_option && (
                    <>
                      <Check size={16} strokeWidth={2.5} aria-hidden className="shrink-0" />
                      <span className="sr-only">Correct answer: </span>
                    </>
                  )}
                  {opt}
                </span>
              )}
            </li>
          ))}
        </ul>
      )}

      {question.source_excerpt && (
        <blockquote className="mt-3 border-l-[3px] border-highlight pl-3 text-sm text-muted-foreground">
          {question.source_excerpt}
        </blockquote>
      )}

      {error && <p className="mt-2 text-xs text-critical">{error}</p>}

      <div className="mt-4 flex flex-wrap items-center gap-2">
        {editing ? (
          <>
            <button
              type="button"
              disabled={busy}
              onClick={saveAndApprove}
              className={buttonStyles()}
            >
              Save and approve
            </button>
            <button
              type="button"
              disabled={busy}
              onClick={cancelEditing}
              className={buttonStyles({ intent: 'secondary' })}
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
                  className={buttonStyles()}
                >
                  Approve
                </button>
                <button
                  type="button"
                  disabled={busy}
                  onClick={startEditing}
                  className={buttonStyles({ intent: 'secondary' })}
                >
                  Edit
                </button>
                <button
                  type="button"
                  disabled={busy}
                  onClick={() => act('rejected')}
                  className={buttonStyles({ intent: 'danger' })}
                >
                  Reject
                </button>
                <button
                  type="button"
                  disabled={busy}
                  onClick={regenerate}
                  title="Replace this draft with a new question from the same page"
                  className={buttonStyles({ intent: 'quiet' })}
                >
                  {busy ? 'Working...' : 'Regenerate'}
                </button>
              </>
            )}
            {question.status === 'approved' && (
              <button
                type="button"
                disabled={busy}
                onClick={() => act('staged')}
                className={buttonStyles()}
              >
                Make ready to send
              </button>
            )}
          </>
        )}
      </div>
    </article>
  )
}
