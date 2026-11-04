import { useEffect, useId, useState } from 'react'
import { Download } from 'lucide-react'

import { ApiError } from '../api'
import { buttonStyles } from '../components/ui/button'
import { PageBody, PageHeader, Panel, SkeletonRows, Tag, type Tone } from '../components/ui/primitives'
import { sinceVerb } from '../features/format/relativeTime'
import {
  exportMyData,
  getMyDeletionRequest,
  isOpen,
  requestMyDeletion,
  saveJson,
  type DeletionStatus,
  type MyDeletionRequest,
} from '../features/student/myDataApi'

const STATUS: Record<DeletionStatus, { word: string; tone: Tone; next: string }> = {
  requested: {
    word: 'Waiting for an administrator',
    tone: 'info',
    next: 'Nothing has been erased yet. An administrator checks the request first.',
  },
  approved: {
    word: 'Approved',
    tone: 'mixed',
    next: 'Your data will be erased shortly. You will then be signed out for good.',
  },
  rejected: {
    word: 'Not approved',
    tone: 'poor',
    next: 'Nothing was erased. Ask your administrator why, or ask again.',
  },
  executed: { word: 'Erased', tone: 'good', next: 'Your data has been erased.' },
}

/** A student's rights over their own data: take a copy, or ask for it to be
 * erased. Neither needs the terms to be accepted. */
export default function StudentMyDataPage() {
  return (
    <>
      <PageHeader
        title="My data"
        description="Download a copy of everything C.L.I.P keeps about you, or ask for it to be erased."
      />
      <PageBody>
        <div className="grid max-w-3xl gap-4">
          <ExportPanel />
          <ErasurePanel />
        </div>
      </PageBody>
    </>
  )
}

function ExportPanel() {
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [saved, setSaved] = useState(false)

  function download() {
    setBusy(true)
    setError(null)
    exportMyData().then(
      (data) => {
        saveJson(data, 'my-clip-data.json')
        setSaved(true)
        setBusy(false)
      },
      (caught: unknown) => {
        setError(caught instanceof ApiError ? caught.message : 'Your data could not be downloaded. Try again.')
        setBusy(false)
      },
    )
  }

  return (
    <Panel title="Download a copy">
      <p className="text-sm text-muted-foreground">
        Your account, your answers, the prompts you were sent, your engagement and attention summaries, and any
        requests you have made, as one JSON file.
      </p>
      {error && (
        <p role="alert" className="mt-3 text-sm text-critical">
          {error}
        </p>
      )}
      {saved && !error && (
        <p role="status" className="mt-3 text-sm text-success">
          Saved as my-clip-data.json.
        </p>
      )}
      <button type="button" className={buttonStyles({ className: 'mt-4' })} disabled={busy} onClick={download}>
        <Download size={16} aria-hidden />
        {busy ? 'Preparing…' : 'Download my data'}
      </button>
    </Panel>
  )
}

function ErasurePanel() {
  const [latest, setLatest] = useState<MyDeletionRequest | null | undefined>(undefined)
  const [loadError, setLoadError] = useState<string | null>(null)
  const [asking, setAsking] = useState(false)

  useEffect(() => {
    getMyDeletionRequest().then(setLatest, () => setLoadError('Your request could not be loaded. Reload the page.'))
  }, [])

  if (loadError) {
    return (
      <Panel title="Erase my data">
        <p role="alert" className="text-sm text-critical">
          {loadError}
        </p>
      </Panel>
    )
  }
  if (latest === undefined) {
    return <SkeletonRows label="Loading your request" rows={1} />
  }

  const status = latest ? STATUS[latest.status] : null
  return (
    <Panel
      title="Erase my data"
      description={latest ? sinceVerb('Asked', latest.requested_at) : undefined}
      actions={status && <Tag tone={status.tone}>{status.word}</Tag>}
    >
      {status && <p className="text-sm">{status.next}</p>}
      {!isOpen(latest) &&
        (asking ? (
          <ErasureForm
            onSent={(sent) => {
              setLatest(sent)
              setAsking(false)
            }}
            onCancel={() => setAsking(false)}
          />
        ) : (
          <>
            <p className="mt-2 text-sm text-muted-foreground">
              Erasing removes your account, answers, engagement and summaries from C.L.I.P. It cannot be undone. A
              record that a deletion happened is kept, with your name removed.
            </p>
            <button
              type="button"
              className={buttonStyles({ intent: 'danger', className: 'mt-4' })}
              onClick={() => setAsking(true)}
            >
              Ask to erase my data
            </button>
          </>
        ))}
    </Panel>
  )
}

function ErasureForm({ onSent, onCancel }: { onSent: (sent: MyDeletionRequest) => void; onCancel: () => void }) {
  const [confirmed, setConfirmed] = useState(false)
  const [reason, setReason] = useState('')
  const [sending, setSending] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const reasonId = useId()
  const confirmId = useId()

  function send() {
    setSending(true)
    setError(null)
    requestMyDeletion(reason.trim() || null).then(onSent, (caught: unknown) => {
      setSending(false)
      setError(caught instanceof ApiError ? caught.message : 'The request could not be sent. Try again.')
    })
  }

  return (
    <div className="mt-3 space-y-4">
      <div>
        <label htmlFor={reasonId} className="text-sm font-semibold">
          Reason <span className="font-normal text-muted-foreground">(optional)</span>
        </label>
        <textarea
          id={reasonId}
          value={reason}
          maxLength={500}
          rows={3}
          onChange={(event) => setReason(event.target.value)}
          className="mt-1 w-full rounded-md border border-input bg-background px-3 py-2 text-sm"
        />
      </div>
      <label htmlFor={confirmId} className="flex items-start gap-2 text-sm">
        <input
          id={confirmId}
          type="checkbox"
          className="mt-1"
          checked={confirmed}
          onChange={(event) => setConfirmed(event.target.checked)}
        />
        I understand my data will be erased for good once an administrator approves this.
      </label>
      {error && (
        <p role="alert" className="text-sm text-critical">
          {error}
        </p>
      )}
      <div className="flex flex-wrap gap-2">
        <button
          type="button"
          className={buttonStyles({ intent: 'danger' })}
          disabled={!confirmed || sending}
          onClick={send}
        >
          {sending ? 'Sending…' : 'Send the request'}
        </button>
        <button type="button" className={buttonStyles({ intent: 'secondary' })} onClick={onCancel}>
          Cancel
        </button>
      </div>
    </div>
  )
}
