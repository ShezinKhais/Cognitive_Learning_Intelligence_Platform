import { useId, useState, type FormEvent } from 'react'

import { ApiError } from '../../api'
import { buttonStyles } from '../../components/ui/button'
import { Panel } from '../../components/ui/primitives'
import { useToast } from '../../components/ui/toast'
import { createCourse, type Course } from './accountsApi'

const FIELD = 'mt-1 w-full rounded-md border border-input bg-background px-3 py-2 text-sm'

/** An admin adds a course by its code and name. Used on the Accounts and
 * Courses pages. */
export function AddCourseForm({ onCancel, onAdded }: { onCancel: () => void; onAdded: (course: Course) => void }) {
  const notify = useToast()
  const [code, setCode] = useState('')
  const [name, setName] = useState('')
  const [sending, setSending] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const codeId = useId()
  const codeHint = useId()
  const nameId = useId()

  function submit(event: FormEvent) {
    event.preventDefault()
    setSending(true)
    setError(null)
    createCourse({ code: code.trim(), name: name.trim() }).then(
      (course) => {
        notify(`Added ${course.code}`)
        onAdded(course)
      },
      (caught: unknown) => {
        setSending(false)
        setError(caught instanceof ApiError ? caught.message : 'The course could not be added. Try again.')
      },
    )
  }

  return (
    <Panel title="Add a course">
      <form onSubmit={submit} className="grid gap-3 sm:grid-cols-[12rem_1fr]">
        <div>
          <label htmlFor={codeId} className="text-sm font-semibold">
            Code
          </label>
          <input
            id={codeId}
            required
            minLength={2}
            maxLength={20}
            pattern="[A-Za-z0-9_\-]+"
            title="Letters, digits, hyphens or underscores, with no spaces"
            aria-describedby={codeHint}
            value={code}
            onChange={(e) => setCode(e.target.value)}
            className={FIELD}
          />
          <p id={codeHint} className="mt-1 text-xs text-muted-foreground">
            No spaces, for example CSIT321.
          </p>
        </div>
        <div>
          <label htmlFor={nameId} className="text-sm font-semibold">
            Name
          </label>
          <input id={nameId} required maxLength={255} value={name} onChange={(e) => setName(e.target.value)} className={FIELD} />
        </div>
        {error && (
          <p role="alert" className="text-sm text-critical sm:col-span-2">
            {error}
          </p>
        )}
        <div className="flex gap-2 sm:col-span-2">
          <button type="submit" className={buttonStyles()} disabled={sending}>
            {sending ? 'Adding…' : 'Add'}
          </button>
          <button type="button" className={buttonStyles({ intent: 'secondary' })} onClick={onCancel}>
            Cancel
          </button>
        </div>
      </form>
    </Panel>
  )
}
