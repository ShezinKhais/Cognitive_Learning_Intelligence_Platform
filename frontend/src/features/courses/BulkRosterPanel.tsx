import { useId, useState, type ChangeEvent } from 'react'
import { FileUp, Users, X } from 'lucide-react'

import { ApiError } from '../../api'
import { buttonStyles } from '../../components/ui/button'
import { Tag, type Tone } from '../../components/ui/primitives'
import { bulkAddStudents, type BulkOutcome, type BulkRosterResult, type CourseRoster } from './coursesApi'

const FIELD = 'w-full rounded-md border border-input bg-input-background px-3 py-2 text-sm'
// Larger than any class list, small enough that a wrong file is caught here.
const MAX_FILE_BYTES = 200_000

const OUTCOME: Record<BulkOutcome, { label: string; tone: Tone }> = {
  add: { label: 'Will be added', tone: 'good' },
  create: { label: 'New account', tone: 'info' },
  already: { label: 'Already on the course', tone: 'neutral' },
  no_account: { label: 'No account', tone: 'mixed' },
  not_student: { label: 'Not a student account', tone: 'mixed' },
  inactive: { label: 'Account switched off', tone: 'mixed' },
  invalid: { label: 'Not an email', tone: 'poor' },
  duplicate: { label: 'Repeated', tone: 'neutral' },
}

/** Add a whole class list to a course: paste it or choose a file, see what
 * each line will do, then confirm (#293). */
export default function BulkRosterPanel({
  code,
  isAdmin,
  onDone,
  onClose,
}: {
  code: string
  isAdmin: boolean
  onDone: (roster: CourseRoster, added: number) => void
  onClose: () => void
}) {
  const id = useId()
  const [text, setText] = useState('')
  const [createMissing, setCreateMissing] = useState(false)
  const [preview, setPreview] = useState<BulkRosterResult | null>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  function edited(next: string) {
    setText(next)
    setPreview(null)
  }

  function readFile(event: ChangeEvent<HTMLInputElement>) {
    const file = event.target.files?.[0]
    event.target.value = ''
    if (!file) return
    if (file.size > MAX_FILE_BYTES) return setError('That file is too large for a class list. Use a CSV or text file.')
    file.text().then(
      (content) => {
        setError(null)
        edited(content)
      },
      () => setError('The file could not be read.'),
    )
  }

  function send(confirm: boolean) {
    setBusy(true)
    setError(null)
    bulkAddStudents(code, { text, confirm, create_missing: isAdmin && createMissing }).then(
      (result) => {
        setBusy(false)
        if (confirm && result.roster) {
          onDone(result.roster, (result.counts.add ?? 0) + (result.counts.create ?? 0))
        } else {
          setPreview(result)
        }
      },
      (caught: unknown) => {
        setBusy(false)
        setError(caught instanceof ApiError ? caught.message : 'The list could not be checked. Try again.')
      },
    )
  }

  const changing = preview ? (preview.counts.add ?? 0) + (preview.counts.create ?? 0) : 0

  return (
    <section aria-labelledby={`${id}-title`} className="mt-4 rounded-lg border border-border bg-muted/30 p-4">
      <div className="flex items-start justify-between gap-3">
        <div>
          <h3 id={`${id}-title`} className="inline-flex items-center gap-2 font-bold">
            <Users size={16} aria-hidden />
            Add many students
          </h3>
          <p className="mt-0.5 text-sm text-muted-foreground">
            One per line: an email, or a name and email separated by a comma. Up to 500.
          </p>
        </div>
        <button type="button" aria-label="Close" className={buttonStyles({ intent: 'quiet' })} onClick={onClose}>
          <X size={15} aria-hidden />
        </button>
      </div>

      <label htmlFor={`${id}-text`} className="sr-only">
        Class list
      </label>
      <textarea
        id={`${id}-text`}
        rows={6}
        value={text}
        onChange={(event) => edited(event.target.value)}
        placeholder={'Ann Lee, ann.lee@uni.edu\nbob.ray@uni.edu'}
        className={`${FIELD} mt-3 font-mono`}
      />

      <div className="mt-2 flex flex-wrap items-center gap-3">
        <label className={buttonStyles({ intent: 'secondary', className: 'cursor-pointer' })}>
          <FileUp size={15} aria-hidden />
          Choose a CSV or text file
          <input type="file" accept=".csv,.txt,text/csv,text/plain" className="sr-only" onChange={readFile} />
        </label>
        {isAdmin && (
          <label className="flex items-center gap-2 text-sm">
            <input
              type="checkbox"
              checked={createMissing}
              onChange={(event) => {
                setCreateMissing(event.target.checked)
                setPreview(null)
              }}
            />
            Create accounts for people who do not have one
          </label>
        )}
      </div>

      {error && (
        <p role="alert" className="mt-3 text-sm text-critical">
          {error}
        </p>
      )}

      {preview && (
        <div className="mt-4">
          <p className="text-sm font-semibold" role="status">
            {changing === 0
              ? 'Nothing to add from this list.'
              : `${changing} ${changing === 1 ? 'student' : 'students'} will be added.`}{' '}
            <span className="font-normal text-muted-foreground">Nothing has changed yet.</span>
          </p>
          <div className="mt-2 max-h-72 overflow-auto rounded-md border border-border bg-card">
            <table className="w-full text-sm">
              <thead className="sticky top-0 bg-card text-left text-muted-foreground">
                <tr>
                  <th scope="col" className="px-3 py-2 font-medium">Line</th>
                  <th scope="col" className="px-3 py-2 font-medium">Student</th>
                  <th scope="col" className="px-3 py-2 font-medium">Result</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-border">
                {preview.lines.map((line) => (
                  <tr key={line.line}>
                    <td className="px-3 py-2 tabular-nums text-muted-foreground">{line.line}</td>
                    <td className="min-w-0 px-3 py-2">
                      {line.name && <span className="block font-medium">{line.name}</span>}
                      <span className="block break-all text-muted-foreground">{line.email}</span>
                    </td>
                    <td className="px-3 py-2">
                      <Tag tone={OUTCOME[line.outcome].tone}>{OUTCOME[line.outcome].label}</Tag>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          {!isAdmin && (preview.counts.no_account ?? 0) > 0 && (
            <p className="mt-2 text-sm text-muted-foreground">
              People without an account are left out. An admin can add them on the Accounts page.
            </p>
          )}
        </div>
      )}

      <div className="mt-4 flex flex-wrap gap-2">
        {preview ? (
          <>
            <button type="button" className={buttonStyles()} disabled={busy || changing === 0} onClick={() => send(true)}>
              {busy ? 'Adding…' : `Add ${changing} ${changing === 1 ? 'student' : 'students'}`}
            </button>
            <button type="button" className={buttonStyles({ intent: 'quiet' })} onClick={() => setPreview(null)}>
              Edit the list
            </button>
          </>
        ) : (
          <button type="button" className={buttonStyles()} disabled={busy || !text.trim()} onClick={() => send(false)}>
            {busy ? 'Checking…' : 'Check the list'}
          </button>
        )}
      </div>
    </section>
  )
}
