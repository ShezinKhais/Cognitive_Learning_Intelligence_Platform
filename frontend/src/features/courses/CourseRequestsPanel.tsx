import { useId, useState, type FormEvent } from 'react'
import { Check, X } from 'lucide-react'

import { ApiError } from '../../api'
import { buttonStyles } from '../../components/ui/button'
import { Panel, Tag } from '../../components/ui/primitives'
import { useToast } from '../../components/ui/toast'
import { STATUS_LABEL, STATUS_TONE, type CourseRequest } from './courseRequests'
import { approveCourseRequest, declineCourseRequest, requestCourse } from './courseRequestsApi'

const FIELD = 'mt-1 w-full rounded-md border border-input bg-background px-3 py-2 text-sm'

function message(caught: unknown, fallback: string): string {
  return caught instanceof ApiError ? caught.message : fallback
}

/** A lecturer asks an admin for a course that does not exist yet. */
export function RequestCourseForm({
  onCancel,
  onSent,
}: {
  onCancel: () => void
  onSent: (request: CourseRequest) => void
}) {
  const notify = useToast()
  const [code, setCode] = useState('')
  const [name, setName] = useState('')
  const [reason, setReason] = useState('')
  const [sending, setSending] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const codeId = useId()
  const codeHint = useId()
  const nameId = useId()
  const reasonId = useId()

  function submit(event: FormEvent) {
    event.preventDefault()
    setSending(true)
    setError(null)
    requestCourse({ code: code.trim(), name: name.trim(), reason: reason.trim() || undefined }).then(
      (request) => {
        notify(`Asked for ${request.code}. An admin will look at it.`)
        onSent(request)
      },
      (caught: unknown) => {
        setSending(false)
        setError(message(caught, 'The request could not be sent. Try again.'))
      },
    )
  }

  return (
    <Panel title="Request a course" description="An admin adds it, with you as its lecturer, or tells you why not.">
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
            No spaces, for example CSIT399.
          </p>
        </div>
        <div>
          <label htmlFor={nameId} className="text-sm font-semibold">
            Name
          </label>
          <input id={nameId} required maxLength={255} value={name} onChange={(e) => setName(e.target.value)} className={FIELD} />
        </div>
        <div className="sm:col-span-2">
          <label htmlFor={reasonId} className="text-sm font-semibold">
            Why it is needed <span className="font-normal text-muted-foreground">(optional)</span>
          </label>
          <textarea
            id={reasonId}
            rows={2}
            maxLength={500}
            value={reason}
            onChange={(e) => setReason(e.target.value)}
            className={FIELD}
          />
        </div>
        {error && (
          <p role="alert" className="text-sm text-critical sm:col-span-2">
            {error}
          </p>
        )}
        <div className="flex gap-2 sm:col-span-2">
          <button type="submit" className={buttonStyles()} disabled={sending}>
            {sending ? 'Sending…' : 'Send request'}
          </button>
          <button type="button" className={buttonStyles({ intent: 'secondary' })} onClick={onCancel}>
            Cancel
          </button>
        </div>
      </form>
    </Panel>
  )
}

/**
 * Course requests. An admin sees those waiting, and approves or declines
 * each; a lecturer sees their own and what was decided.
 */
export function CourseRequestsPanel({
  isAdmin,
  requests,
  onDecided,
}: {
  isAdmin: boolean
  requests: CourseRequest[]
  onDecided: (request: CourseRequest) => void
}) {
  const shown = isAdmin ? requests.filter((request) => request.status === 'pending') : requests
  if (shown.length === 0) return null
  return (
    <Panel
      title={isAdmin ? `Course requests (${shown.length})` : 'Your course requests'}
      description={
        isAdmin
          ? 'Approving adds the course, with the lecturer who asked as its lecturer.'
          : 'An admin approves or declines each one.'
      }
    >
      <ul className="divide-y divide-border">
        {shown.map((request) =>
          isAdmin ? (
            <AdminRequest key={request.id} request={request} onDecided={onDecided} />
          ) : (
            <li key={request.id} className="flex flex-wrap items-start justify-between gap-2 py-3 first:pt-0 last:pb-0">
              <span className="min-w-0">
                <span className="block text-sm font-semibold">
                  {request.code}: {request.name}
                </span>
                {request.status === 'declined' && request.decision_note && (
                  <span className="mt-0.5 block text-sm text-muted-foreground">{request.decision_note}</span>
                )}
              </span>
              <Tag tone={STATUS_TONE[request.status]}>{STATUS_LABEL[request.status]}</Tag>
            </li>
          ),
        )}
      </ul>
    </Panel>
  )
}

function AdminRequest({ request, onDecided }: { request: CourseRequest; onDecided: (request: CourseRequest) => void }) {
  const notify = useToast()
  const [name, setName] = useState(request.name)
  const [declining, setDeclining] = useState(false)
  const [note, setNote] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const nameId = useId()
  const noteId = useId()

  function decide(action: Promise<CourseRequest>, done: string) {
    setBusy(true)
    setError(null)
    action.then(
      (decided) => {
        notify(done)
        onDecided(decided)
      },
      (caught: unknown) => {
        setBusy(false)
        setError(message(caught, 'That did not work. Try again.'))
      },
    )
  }

  return (
    <li className="py-3 first:pt-0 last:pb-0">
      <p className="text-sm font-semibold">{request.code}</p>
      <p className="text-xs text-muted-foreground">
        Asked by {request.requester_name ?? 'a lecturer'}
        {request.reason ? `: ${request.reason}` : ''}
      </p>
      <div className="mt-2 grid gap-2 sm:grid-cols-[1fr_auto] sm:items-end">
        <div>
          <label htmlFor={nameId} className="text-xs font-semibold">
            Name
          </label>
          <input
            id={nameId}
            maxLength={255}
            value={name}
            onChange={(e) => setName(e.target.value)}
            className={FIELD}
            disabled={busy}
          />
        </div>
        <div className="flex gap-2">
          <button
            type="button"
            className={buttonStyles()}
            disabled={busy || !name.trim()}
            onClick={() =>
              decide(
                approveCourseRequest(request.id, name.trim() !== request.name ? name.trim() : undefined),
                `Added ${request.code}`,
              )
            }
          >
            <Check size={15} aria-hidden />
            Approve
          </button>
          <button
            type="button"
            className={buttonStyles({ intent: 'secondary' })}
            disabled={busy}
            aria-expanded={declining}
            onClick={() => setDeclining((value) => !value)}
          >
            <X size={15} aria-hidden />
            Decline
          </button>
        </div>
      </div>
      {declining && (
        <form
          className="mt-2 grid gap-2 sm:grid-cols-[1fr_auto] sm:items-end"
          onSubmit={(event) => {
            event.preventDefault()
            decide(declineCourseRequest(request.id, note.trim() || undefined), `Declined ${request.code}`)
          }}
        >
          <div>
            <label htmlFor={noteId} className="text-xs font-semibold">
              Why, for the lecturer <span className="font-normal text-muted-foreground">(optional)</span>
            </label>
            <input id={noteId} maxLength={500} value={note} onChange={(e) => setNote(e.target.value)} className={FIELD} />
          </div>
          <button type="submit" className={buttonStyles({ intent: 'danger' })} disabled={busy}>
            Decline request
          </button>
        </form>
      )}
      {error && (
        <p role="alert" className="mt-2 text-sm text-critical">
          {error}
        </p>
      )}
    </li>
  )
}
