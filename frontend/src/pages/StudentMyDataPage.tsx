import { useCallback, useEffect, useId, useRef, useState } from 'react'
import { Download } from 'lucide-react'
import { Link } from 'react-router'

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
    next: 'An administrator still needs to carry out the erasure. You will be signed out when it is complete.',
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
  const [signIn, setSignIn] = useState(false)

  const running = useRef(false)
  async function download() {
    if (running.current) return
    running.current = true
    setBusy(true)
    setError(null)
    setSaved(false)
    setSignIn(false)
    try {
      const data = await exportMyData()
      saveJson(data, 'my-clip-data.json')
      setSaved(true)
    } catch (caught) {
      setSignIn(caught instanceof ApiError && caught.status === 401)
      setError(caught instanceof ApiError ? caught.message : 'Your data could not be downloaded. Try again.')
    } finally {
      running.current = false
      setBusy(false)
    }
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
      {signIn && <SignInAgain />}
      {saved && !error && (
        <p role="status" className="mt-3 text-sm text-success">
          Download started: my-clip-data.json.
        </p>
      )}
      <button type="button" className={buttonStyles({ className: 'mt-4' })} disabled={busy} onClick={download}>
        <Download size={16} aria-hidden />
        {busy ? 'Preparing…' : 'Download my data'}
      </button>
    </Panel>
  )
}

function SignInAgain() {
  return <Link to="/login" state={{ from: '/student/my-data' }} className="mt-2 inline-block underline">Sign in again to open My data</Link>
}

function ErasurePanel() {
  const [latest, setLatest] = useState<MyDeletionRequest | null | undefined>(undefined)
  const [loadError, setLoadError] = useState<string | null>(null)
  const [signIn, setSignIn] = useState(false)
  const [asking, setAsking] = useState(false)
  const [checking, setChecking] = useState(false)
  const pending = useRef<AbortController | null>(null)

  const refresh = useCallback(async () => {
    if (pending.current) return
    const controller = new AbortController()
    pending.current = controller
    setChecking(true)
    try {
      const found = await getMyDeletionRequest(controller.signal)
      if (controller.signal.aborted) return
      setLatest(found); setLoadError(null); setSignIn(false)
      if (isOpen(found)) setAsking(false)
    } catch (caught) {
      if (controller.signal.aborted) return
      setSignIn(caught instanceof ApiError && caught.status === 401)
      setLoadError(caught instanceof ApiError ? caught.message : 'Your request status could not be refreshed. Try again.')
    } finally {
      if (pending.current === controller) { pending.current = null; setChecking(false) }
    }
  }, [])

  useEffect(() => {
    void refresh()
    const onFocus = () => { if (document.visibilityState === 'visible') void refresh() }
    const timer = window.setInterval(onFocus, 30_000)
    window.addEventListener('focus', onFocus)
    return () => { window.clearInterval(timer); window.removeEventListener('focus', onFocus); pending.current?.abort(); pending.current = null }
  }, [refresh])

  const status = latest ? STATUS[latest.status] : null
  return (
    <Panel title="Erase my data"
      description={latest ? sinceVerb('Asked', latest.requested_at) : undefined}
      actions={status && <Tag tone={status.tone}>{status.word}</Tag>}>
      <p className="text-sm text-muted-foreground">Status refreshes every 30 seconds while this page is visible and when you return to it.</p>
      {loadError && <p role="alert" className="mt-3 text-sm text-critical">{loadError} Any previously shown status may be out of date.</p>}
      {signIn && <SignInAgain />}
      <button type="button" className={buttonStyles({ intent: 'secondary', className: 'mt-3' })} disabled={checking} onClick={() => void refresh()}>
        {checking ? 'Checking status…' : 'Refresh request status'}
      </button>
      {latest === undefined && !loadError && <SkeletonRows label="Loading your request" rows={1} />}
      {status && <p className="mt-3 text-sm" role="status">{status.next}</p>}
      {latest !== undefined && !isOpen(latest) && (asking ? (
        <ErasureForm statusUnavailable={!!loadError} onSent={sent => {
          // A status GET started before this POST must not restore an older state.
          pending.current?.abort(); pending.current = null; setChecking(false)
          setLatest(sent); setAsking(false)
        }} onCancel={() => setAsking(false)} />
      ) : <>
        <p className="mt-2 text-sm text-muted-foreground">
          Erasing removes your account, answers, engagement and summaries from C.L.I.P. It cannot be undone.
          A record that a deletion happened is kept, with your name removed. Submitting a request does not erase anything immediately.
        </p>
        <button type="button" className={buttonStyles({ intent: 'danger', className: 'mt-4' })} disabled={checking || !!loadError} onClick={() => setAsking(true)}>Ask to erase my data</button>
      </>)}
    </Panel>
  )
}

function ErasureForm({ onSent, onCancel, statusUnavailable }: { onSent: (sent: MyDeletionRequest) => void; onCancel: () => void; statusUnavailable: boolean }) {
  const [confirmed, setConfirmed] = useState(false)
  const [reason, setReason] = useState('')
  const [sending, setSending] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const reasonId = useId()
  const confirmId = useId()

  const running = useRef(false)
  const [signIn, setSignIn] = useState(false)
  async function send() {
    if (!confirmed || statusUnavailable || running.current) return
    running.current = true
    setSending(true); setError(null); setSignIn(false)
    try {
      onSent(await requestMyDeletion(reason.trim() || null))
    } catch (caught) {
      // The POST may have committed before its reply was lost, or another tab
      // may have filed a request. Re-read status; never auto-repeat the POST.
      const refusal = caught instanceof ApiError && [401, 403, 422, 429].includes(caught.status)
      if (!refusal) {
        try {
          const existing = await getMyDeletionRequest()
          if (existing && isOpen(existing)) { onSent(existing); return }
        } catch { /* Keep the original error and let the student refresh status. */ }
      }
      setSignIn(caught instanceof ApiError && caught.status === 401)
      setError(caught instanceof ApiError ? caught.message : 'The request could not be confirmed. Refresh its status before trying again.')
    } finally {
      running.current = false
      setSending(false)
    }
  }

  return (
    <div className="mt-3 space-y-4">
      <div>
        <label htmlFor={reasonId} className="text-sm font-semibold">
          Reason <span className="font-normal text-muted-foreground">(optional)</span>
        </label>
        <textarea
          id={reasonId}
          disabled={sending}
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
          disabled={sending}
          type="checkbox"
          className="mt-1"
          checked={confirmed}
          onChange={(event) => setConfirmed(event.target.checked)}
        />
        I understand my data will be erased for good after administrator approval and execution.
      </label>
      {error && (
        <p role="alert" className="text-sm text-critical">
          {error}
        </p>
      )}
      {signIn && <SignInAgain />}
      <div className="flex flex-wrap gap-2">
        <button
          type="button"
          className={buttonStyles({ intent: 'danger' })}
          disabled={!confirmed || sending || statusUnavailable}
          onClick={send}
        >
          {sending ? 'Sending…' : 'Send the request'}
        </button>
        <button type="button" className={buttonStyles({ intent: 'secondary' })} disabled={sending} onClick={onCancel}>
          Cancel
        </button>
      </div>
    </div>
  )
}
