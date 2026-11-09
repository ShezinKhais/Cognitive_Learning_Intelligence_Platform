import { useEffect, useId, useState, type FormEvent } from 'react'
import { apiAuthenticatedRequest, type Page, type Question } from '../../api'
import { buttonStyles } from '../../components/ui/button'
import { useReviewResource } from '../review/useReviewResource'

interface LessonQuestion extends Question { material_title: string }
interface Plan { session_id: string; selected_only: boolean; editable: boolean; items: LessonQuestion[] }
const PAGE_SIZE = 10
const MAX_QUESTIONS = 100

/** Explicit opt-in: legacy classes retain their course bank until a plan is saved. */
export default function LessonQuestionPlan({ sessionId, onSaved, onPendingChange }: {
  sessionId: string
  onSaved: () => void
  onPendingChange: (pending: boolean) => void
}) {
  const id = useId()
  const path = `/sessions/${encodeURIComponent(sessionId)}/question-plan`
  const resource = useReviewResource<Plan>(path)
  const [saved, setSaved] = useState<Plan | null>(null)
  const [selectedOnly, setSelectedOnly] = useState(false)
  const [selected, setSelected] = useState<Map<string, LessonQuestion>>(new Map())
  const [confirmed, setConfirmed] = useState(false)
  const [saving, setSaving] = useState(false)
  const [message, setMessage] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [material, setMaterial] = useState('')
  const [topic, setTopic] = useState('')
  const [filters, setFilters] = useState({ material: '', topic: '' })
  const [offset, setOffset] = useState(0)
  const query = new URLSearchParams({ limit: String(PAGE_SIZE), offset: String(offset), ...filters })
  const candidates = useReviewResource<Page<LessonQuestion>>(`${path}/candidates?${query}`)

  function reset(plan: Plan) {
    setSaved(plan); setSelectedOnly(plan.selected_only)
    setSelected(new Map(plan.items.map(question => [question.id, question])))
    setConfirmed(false)
  }
  useEffect(() => { if (resource.data) reset(resource.data) }, [resource.data])
  const savedIds = new Set(saved?.items.map(question => question.id))
  const dirty = Boolean(saved) && (selectedOnly !== saved?.selected_only || (
    selectedOnly && (selected.size !== savedIds.size || [...selected.keys()].some(key => !savedIds.has(key)))
  ))
  useEffect(() => { onPendingChange(dirty || saving) }, [dirty, saving, onPendingChange])
  useEffect(() => () => onPendingChange(false), [onPendingChange])

  function toggle(question: LessonQuestion) {
    setConfirmed(false)
    setSelected(current => {
      const next = new Map(current)
      if (next.has(question.id)) next.delete(question.id)
      else if (next.size < MAX_QUESTIONS) next.set(question.id, question)
      return next
    })
  }
  async function save() {
    if (!confirmed || saving || !saved?.editable) return
    setSaving(true); setError(null); setMessage(null)
    try {
      const fresh = await apiAuthenticatedRequest<Plan>(path, {
        method: 'PUT', body: JSON.stringify({ selected_only: selectedOnly,
          question_ids: selectedOnly ? [...selected.keys()] : [], reviewed_confirmed: confirmed }),
      })
      reset(fresh)
      setMessage(fresh.selected_only ? `Saved ${fresh.items.length} checkpoints for this lesson.` : 'Saved: use the course question bank.')
      onSaved()
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : 'The lesson selection could not be saved.')
    } finally { setSaving(false) }
  }
  function filter(event: FormEvent) {
    event.preventDefault(); setOffset(0); setFilters({ material: material.trim(), topic: topic.trim() })
  }

  return <section aria-labelledby={`${id}-heading`} className="mt-5 rounded-lg border border-border bg-card p-4">
    <h2 id={`${id}-heading`} className="font-bold">Checkpoints for this lesson</h2>
    <p className="mt-1 text-sm text-muted-foreground">Choose before starting. Each lesson gets its own copies; past answers and other lessons stay intact.</p>
    {resource.error ? <p role="alert">Could not load lesson selection. <button type="button" onClick={resource.retry} className="underline">Try again</button></p> : !saved ? <p role="status">Loading lesson selection…</p> : <>
      <fieldset disabled={saving || !saved.editable} className="mt-3">
        <legend className="sr-only">Question source</legend>
        <label className="flex items-center gap-2 text-sm"><input type="checkbox" checked={selectedOnly} onChange={event => { setSelectedOnly(event.target.checked); setConfirmed(false) }} />Use only selected checkpoints in this lesson</label>
        <p className="mt-1 text-xs text-muted-foreground">When off, the existing course bank is used. When on, an empty or exhausted selection sends no other questions.</p>
        {selectedOnly && <>
          <h3 className="mt-4 text-sm font-bold">Selected ({selected.size}/{MAX_QUESTIONS})</h3>
          {selected.size === 0 ? <p className="text-sm">No checkpoints selected. This lesson will have no checkpoints until you add some and save.</p> : <ul className="mt-2 space-y-2">{[...selected.values()].map(question => <li key={question.id} className="rounded border border-border p-2 text-sm">
            <span>{question.prompt}</span> <button type="button" className="ml-2 font-semibold underline" aria-label={`Remove ${question.prompt}`} onClick={() => toggle(question)}>Remove</button>
          </li>)}</ul>}
          <form onSubmit={filter} className="mt-4 flex flex-wrap items-end gap-3">
            <label className="text-sm">Find material<input value={material} maxLength={255} onChange={event => setMaterial(event.target.value)} className="mt-1 block rounded border border-input px-2 py-1" /></label>
            <label className="text-sm">Find topic<input value={topic} maxLength={255} onChange={event => setTopic(event.target.value)} className="mt-1 block rounded border border-input px-2 py-1" /></label>
            <button type="submit" className={buttonStyles({ intent: 'secondary' })}>Find checkpoints</button>
          </form>
          {candidates.error ? <p role="alert" className="mt-3">Could not load approved questions. <button type="button" onClick={candidates.retry} className="underline">Try again</button></p> : !candidates.data ? <p role="status">Loading approved questions…</p> : <>
            {candidates.data.items.length === 0 ? <p className="mt-3 text-sm">No approved questions match. Review or write a question in Materials first.</p> : <ul className="mt-3 space-y-3">{candidates.data.items.map(question => <li key={question.id} className="rounded border border-border p-3">
              <label className="flex items-start gap-2 text-sm font-semibold"><input type="checkbox" checked={selected.has(question.id)} disabled={!selected.has(question.id) && selected.size >= MAX_QUESTIONS} onChange={() => toggle(question)} />{question.prompt}</label>
              <p className="mt-1 text-xs text-muted-foreground">{question.material_title} · {question.topic ?? 'No topic'}</p>
              <details className="mt-2 text-sm"><summary className="cursor-pointer font-semibold">Review answer and source</summary>
                <p className="mt-2">Reference answer: {question.type === 'mcq' ? question.options?.[question.correct_option ?? -1] ?? 'Unavailable' : question.reference_answer ?? 'Unavailable'}</p>
                {question.key_points?.length ? <ul className="list-disc pl-5">{question.key_points.map((point, index) => <li key={index}>{point}</li>)}</ul> : null}
                <p>{question.source_slide ? `Page or slide ${question.source_slide}` : 'Page or slide unavailable'}</p>
                <p className="whitespace-pre-wrap">{question.source_excerpt || 'No source passage attached. Verify the material before selecting.'}</p>
              </details>
            </li>)}</ul>}
            {candidates.data.total > PAGE_SIZE && <nav aria-label="Lesson candidate pages" className="mt-3 flex items-center gap-3">
              <button type="button" className={buttonStyles({ intent: 'secondary' })} disabled={offset === 0} onClick={() => setOffset(value => Math.max(0, value - PAGE_SIZE))}>Previous</button>
              <span className="text-sm">{offset + 1}–{Math.min(offset + PAGE_SIZE, candidates.data.total)} of {candidates.data.total}</span>
              <button type="button" className={buttonStyles({ intent: 'secondary' })} disabled={offset + PAGE_SIZE >= candidates.data.total} onClick={() => setOffset(value => value + PAGE_SIZE)}>Next</button>
            </nav>}
          </>}
        </>}
        <label className="mt-4 flex items-start gap-2 text-sm"><input type="checkbox" checked={confirmed} onChange={event => setConfirmed(event.target.checked)} />I reviewed the selected questions, answers and sources for this lesson.</label>
        <div className="mt-3 flex flex-wrap gap-2">
          <button type="button" className={buttonStyles()} disabled={!dirty || !confirmed} onClick={() => void save()}>{saving ? 'Saving…' : 'Save lesson selection'}</button>
          <button type="button" className={buttonStyles({ intent: 'quiet' })} disabled={!dirty} onClick={() => reset(saved)}>Discard changes</button>
        </div>
      </fieldset>
      {dirty && <p role="status" className="mt-2 text-sm">Save or discard your selection changes before starting the class.</p>}
    </>}
    {error && <p role="alert" className="mt-3 text-sm text-critical">{error}</p>}
    {message && <p role="status" className="mt-3 text-sm">{message}</p>}
  </section>
}
