import { useCallback, useEffect, useId, useState, type FormEvent } from 'react'
import { Power, Sparkles } from 'lucide-react'

import { ApiError } from '../../api'
import { buttonStyles } from '../../components/ui/button'
import { cn } from '../../components/ui/cn'
import {
  AI_SWITCHES,
  allOff,
  allOn,
  anyOn,
  matchesCourse,
  pacingOf,
  readPacing,
  switchesOf,
  type AiControls,
  type AiControlsView,
  type ClassPacing,
} from './aiControls'
import { getAiControls, saveAiControls } from './aiControlsApi'

/**
 * The lecturer's AI switches for one class: automatic checkpoints, the
 * learning assistant, refocus nudges and engagement estimates, and a button
 * that turns them all off at once. A change applies to this class only,
 * unless "Use for every new class" is ticked, which also saves it as the
 * course's default. The class is told at once, so students' pages hide what
 * is off.
 */
export default function AiControlsPanel({
  sessionId,
  courseCode,
  compact = false,
}: {
  sessionId: string
  courseCode?: string
  compact?: boolean
}) {
  const [view, setView] = useState<AiControlsView | null>(null)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [forCourse, setForCourse] = useState(false)
  const headingId = useId()
  const courseId = useId()

  useEffect(() => {
    let cancelled = false
    getAiControls(sessionId).then(
      (found) => {
        if (cancelled) return
        setView(found)
        setForCourse(matchesCourse(found) && anyOff(found))
      },
      () => {
        if (!cancelled) setError('Could not load the AI switches for this class.')
      },
    )
    return () => {
      cancelled = true
    }
  }, [sessionId])

  const save = useCallback(
    (controls: AiControls, applyToCourse: boolean, pacing: ClassPacing) => {
      setSaving(true)
      setError(null)
      saveAiControls(sessionId, controls, applyToCourse, pacing).then(
        (saved) => {
          setView(saved)
          setSaving(false)
        },
        (caught: unknown) => {
          setSaving(false)
          setError(caught instanceof ApiError ? caught.message : 'The change was not saved. Try again.')
        },
      )
    },
    [sessionId],
  )

  if (!view) {
    return error ? (
      <section className="rounded-lg border border-border bg-card p-3">
        <p role="alert" className="text-sm text-critical">{error}</p>
      </section>
    ) : null
  }

  const current = switchesOf(view)
  const pacing = pacingOf(view)
  const on = anyOn(current)

  return (
    <section
      aria-labelledby={headingId}
      className={cn('rounded-lg border border-border bg-card', compact ? 'p-3' : 'p-4 sm:p-5')}
    >
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h2 id={headingId} className="inline-flex items-center gap-2 font-bold">
          <Sparkles size={16} aria-hidden className="text-info" />
          AI in this class
        </h2>
        <button
          type="button"
          disabled={saving}
          onClick={() => save(on ? allOff() : allOn(), forCourse, pacing)}
          className={cn(
            'inline-flex items-center gap-2 rounded-md border px-3 py-1.5 text-sm font-semibold disabled:opacity-50',
            on
              ? 'border-critical/40 text-critical hover:bg-critical/5'
              : 'border-input text-foreground hover:bg-muted',
          )}
        >
          <Power size={14} aria-hidden />
          {on ? 'Pause all AI' : 'Turn all AI back on'}
        </button>
      </div>

      <ul className={cn('mt-3 divide-y divide-border', compact ? '' : 'sm:mt-4')}>
        {AI_SWITCHES.map(({ key, label, detail }) => (
          <li key={key} className="flex items-start justify-between gap-3 py-2.5">
            <span className="min-w-0">
              <span className="block text-sm font-medium">{label}</span>
              {!compact && <span className="mt-0.5 block text-xs text-muted-foreground">{detail}</span>}
            </span>
            <button
              type="button"
              role="switch"
              aria-checked={current[key]}
              aria-label={label}
              title={compact ? detail : undefined}
              disabled={saving}
              onClick={() => save({ ...current, [key]: !current[key] }, forCourse, pacing)}
              className={cn(
                'relative inline-flex h-6 w-11 shrink-0 items-center rounded-full border transition-colors disabled:opacity-50',
                current[key] ? 'border-primary bg-primary' : 'border-input bg-muted',
              )}
            >
              <span
                aria-hidden
                className={cn(
                  'inline-block size-4 rounded-full bg-background shadow transition-transform',
                  current[key] ? 'translate-x-6' : 'translate-x-1',
                )}
              />
            </button>
          </li>
        ))}
      </ul>

      <PacingForm
        key={`${pacing.checkpoint_minutes}-${pacing.answer_seconds}`}
        pacing={pacing}
        disabled={saving}
        autoCheckpoints={current.auto_checkpoints}
        onSave={(next) => save(current, forCourse, next)}
      />

      <label htmlFor={courseId} className="mt-2 flex cursor-pointer items-start gap-2 text-xs text-muted-foreground">
        <input
          id={courseId}
          type="checkbox"
          className="mt-0.5 size-3.5 accent-[var(--primary)]"
          checked={forCourse}
          disabled={saving}
          onChange={(event) => {
            setForCourse(event.target.checked)
            if (event.target.checked) save(current, true, pacing)
          }}
        />
        <span>
          Use these for every new class{courseCode ? ` of ${courseCode}` : ' of this course'}. Otherwise they are for this
          class only.
        </span>
      </label>

      {error && (
        <p role="alert" className="mt-2 text-sm text-critical">
          {error}
        </p>
      )}
    </section>
  )
}

function PacingForm({
  pacing,
  disabled,
  autoCheckpoints,
  onSave,
}: {
  pacing: ClassPacing
  disabled: boolean
  autoCheckpoints: boolean
  onSave: (pacing: ClassPacing) => void
}) {
  const id = useId()
  const [minutes, setMinutes] = useState(pacing.checkpoint_minutes?.toString() ?? '')
  const [seconds, setSeconds] = useState(pacing.answer_seconds?.toString() ?? '')
  const [problem, setProblem] = useState<string | null>(null)
  const changed =
    minutes.trim() !== (pacing.checkpoint_minutes?.toString() ?? '') ||
    seconds.trim() !== (pacing.answer_seconds?.toString() ?? '')

  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    const every = readPacing(minutes, 'checkpoint_minutes')
    const answer = readPacing(seconds, 'answer_seconds')
    if ('error' in every) return setProblem(`Minutes between checkpoints: ${every.error}`)
    if ('error' in answer) return setProblem(`Seconds to answer: ${answer.error}`)
    setProblem(null)
    onSave({ checkpoint_minutes: every.value, answer_seconds: answer.value })
  }

  const field = 'mt-1 w-full rounded-md border border-input bg-input-background px-2.5 py-1.5 text-sm'
  return (
    <form onSubmit={submit} className="mt-3 border-t border-border pt-3">
      <p className="text-sm font-medium">Pacing</p>
      <div className="mt-1 grid grid-cols-2 gap-3">
        <label htmlFor={`${id}-every`} className="text-xs text-muted-foreground">
          Minutes between checkpoints
          <input
            id={`${id}-every`}
            inputMode="numeric"
            placeholder="15 to 20"
            value={minutes}
            disabled={disabled || !autoCheckpoints}
            onChange={(event) => setMinutes(event.target.value)}
            className={field}
          />
        </label>
        <label htmlFor={`${id}-answer`} className="text-xs text-muted-foreground">
          Seconds to answer
          <input
            id={`${id}-answer`}
            inputMode="numeric"
            placeholder="30"
            value={seconds}
            disabled={disabled}
            onChange={(event) => setSeconds(event.target.value)}
            className={field}
          />
        </label>
      </div>
      {problem && (
        <p role="alert" className="mt-1.5 text-xs text-critical">
          {problem}
        </p>
      )}
      {changed && (
        <button type="submit" disabled={disabled} className={buttonStyles({ className: 'mt-2' })}>
          Save pacing
        </button>
      )}
    </form>
  )
}

function anyOff(controls: AiControls): boolean {
  return AI_SWITCHES.some(({ key }) => !controls[key])
}
