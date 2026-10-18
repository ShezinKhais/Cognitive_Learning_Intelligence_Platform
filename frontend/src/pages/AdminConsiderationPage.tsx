import { useCallback, useEffect, useState } from 'react'

import { ApiError } from '../api'
import { buttonStyles } from '../components/ui/button'
import { EmptyState, MetaLine, PageBody, PageHeader, SkeletonRows, Tag, type Tone } from '../components/ui/primitives'
import SegmentedTabs from '../components/ui/SegmentedTabs'
import { useToast } from '../components/ui/toast'
import {
  decideRequest,
  listRequests,
  NEED_LABEL,
  untilLabel,
  type AdminConsiderationRequest,
  type ConsiderationStatus,
} from '../features/consideration/considerationApi'
import { sinceVerb } from '../features/format/relativeTime'

const TONE: Record<ConsiderationStatus, Tone> = { pending: 'info', approved: 'good', rejected: 'poor', withdrawn: 'neutral' }
const WORD: Record<ConsiderationStatus, string> = {
  pending: 'Waiting',
  approved: 'Approved',
  rejected: 'Not approved',
  withdrawn: 'Withdrawn',
}

type Show = 'pending' | 'all'

/** Special consideration requests to decide. Approving one records the
 * accommodation the live class honours; the lecturer sees only that it exists. */
export default function AdminConsiderationPage() {
  const [show, setShow] = useState<Show>('pending')
  const [requests, setRequests] = useState<AdminConsiderationRequest[] | null>(null)
  const [error, setError] = useState<string | null>(null)

  const load = useCallback((which: Show) => {
    let current = true
    setError(null)
    listRequests(which).then(
      (page) => current && setRequests(page.items),
      () => current && setError('The requests could not be loaded. Check your connection and reload.'),
    )
    return () => {
      current = false
    }
  }, [])

  useEffect(() => load(show), [load, show])

  return (
    <>
      <PageHeader
        title="Special consideration"
        description="Requests from students to be treated differently in class. Only administrators see the details."
        actions={
          <SegmentedTabs
            label="Show"
            value={show}
            onChange={(next) => {
              setRequests(null)
              setShow(next)
            }}
            segments={[
              { key: 'pending', label: 'Waiting' },
              { key: 'all', label: 'All' },
            ]}
          />
        }
      />
      <PageBody>
        {error ? (
          <EmptyState title="This could not be loaded">{error}</EmptyState>
        ) : !requests ? (
          <SkeletonRows label="Loading requests" />
        ) : requests.length === 0 ? (
          <EmptyState art="lecture" title={show === 'pending' ? 'Nothing waiting' : 'No requests yet'}>
            A student's request appears here as soon as they send it.
          </EmptyState>
        ) : (
          <ul className="space-y-3">
            {requests.map((request) => (
              <li key={request.id}>
                <RequestRow
                  request={request}
                  onDecided={(decided) =>
                    setRequests((current) =>
                      (current ?? [])
                        .map((item) => (item.id === decided.id ? { ...item, ...decided } : item))
                        .filter((item) => show === 'all' || item.status === 'pending'),
                    )
                  }
                />
              </li>
            ))}
          </ul>
        )}
      </PageBody>
    </>
  )
}

function RequestRow({
  request,
  onDecided,
}: {
  request: AdminConsiderationRequest
  onDecided: (decided: AdminConsiderationRequest) => void
}) {
  const notify = useToast()
  const [note, setNote] = useState('')
  const [busy, setBusy] = useState<'approve' | 'reject' | null>(null)

  function decide(approve: boolean) {
    setBusy(approve ? 'approve' : 'reject')
    decideRequest(request.id, approve, note).then(
      (decided) => {
        onDecided({ ...request, ...decided })
        notify(approve ? `Approved for ${request.student_name}` : `Not approved for ${request.student_name}`)
      },
      (caught: unknown) => {
        setBusy(null)
        notify(caught instanceof ApiError ? caught.message : 'That could not be saved. Try again.', { tone: 'problem' })
      },
    )
  }

  return (
    <article className="rounded-lg border border-border bg-card px-5 py-4">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0">
          <h2 className="font-semibold">{request.student_name}</h2>
          <MetaLine items={[request.student_email, request.course_code, sinceVerb('Sent', request.created_at)]} />
        </div>
        <Tag tone={TONE[request.status]}>{WORD[request.status]}</Tag>
      </div>
      <div className="mt-3 flex flex-wrap gap-1.5">
        {request.needs.map((need) => (
          <span key={need} className="rounded-md bg-muted px-2.5 py-1 text-sm">
            {NEED_LABEL[need]}
          </span>
        ))}
      </div>
      <p className="mt-2 text-sm text-muted-foreground">{untilLabel(request.until)}</p>
      {request.note && (
        <p className="mt-3 rounded-md border-l-2 border-primary bg-muted/40 px-4 py-2 text-sm">{request.note}</p>
      )}
      {request.decision_note && request.status !== 'pending' && (
        <p className="mt-3 text-sm">
          <span className="font-semibold">Your note: </span>
          {request.decision_note}
        </p>
      )}
      {request.status === 'pending' && (
        <div className="mt-4 flex flex-wrap items-center gap-2">
          <input
            value={note}
            maxLength={300}
            onChange={(event) => setNote(event.target.value)}
            placeholder="A note for the student (optional)"
            aria-label={`Note for ${request.student_name}`}
            className="min-w-0 flex-1 rounded-md border border-input bg-background px-3 py-2 text-sm"
          />
          <button type="button" className={buttonStyles()} disabled={busy !== null} onClick={() => decide(true)}>
            {busy === 'approve' ? 'Approving…' : 'Approve'}
          </button>
          <button type="button" className={buttonStyles({ intent: 'danger' })} disabled={busy !== null} onClick={() => decide(false)}>
            {busy === 'reject' ? 'Saving…' : 'Do not approve'}
          </button>
        </div>
      )}
    </article>
  )
}
