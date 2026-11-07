import { useEffect, useState } from 'react'
import { apiAuthenticatedRequest } from '../../api'
import { buttonStyles } from '../../components/ui/button'
import type { DraftMinute } from './TranscriptDraftPanel'

interface Status {
  configured: boolean
  enabled: boolean
  subscribed: boolean
  message: string
  pending: number
  failed: number
  drafts: { transcript_id: string; notes: DraftMinute[]; expires_at: string; warning: string }[]
}

export default function AutomaticTranscriptPanel({ sessionId, publishedIds, onReview }: {
  sessionId: string
  publishedIds: string[]
  onReview: (note: DraftMinute) => void
}) {
  const [status, setStatus] = useState<Status | null>(null)
  const [confirmed, setConfirmed] = useState(false)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [refresh, setRefresh] = useState(0)
  useEffect(() => {
    const controller = new AbortController()
    let pending = false
    async function load() {
      if (pending) return
      pending = true
      try {
        const value = await apiAuthenticatedRequest<Status>(`/sessions/${sessionId}/discussion/automatic-transcripts`, { signal: controller.signal })
        if (!controller.signal.aborted) { setStatus(value); setError(null) }
      } catch (caught) {
        if (!controller.signal.aborted) setError(caught instanceof Error ? caught.message : 'Could not check automatic transcript fetching.')
      } finally { pending = false }
    }
    void load()
    const timer = window.setInterval(() => void load(), 15_000)
    return () => { controller.abort(); window.clearInterval(timer) }
  }, [sessionId, refresh])

  async function change(enabled: boolean) {
    setBusy(true); setError(null)
    try {
      await apiAuthenticatedRequest(`/sessions/${sessionId}/discussion/automatic-transcripts`, {
        method: 'PUT', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ enabled, participant_notice_confirmed: confirmed }),
      })
      setConfirmed(false); setRefresh(n => n + 1)
    } catch (caught) { setError(caught instanceof Error ? caught.message : 'Could not update automatic fetching.') }
    finally { setBusy(false) }
  }

  async function discard(id: string) {
    setBusy(true)
    try {
      await apiAuthenticatedRequest(`/sessions/${sessionId}/discussion/automatic-transcripts/drafts/${encodeURIComponent(id)}`, { method: 'DELETE' })
      setRefresh(n => n + 1)
    } catch { setError('Could not discard the private draft. Try again.') }
    finally { setBusy(false) }
  }

  return <section className="space-y-3 rounded-lg border border-border p-4" aria-label="Automatic Teams transcript fetching">
    <h3 className="font-semibold">Automatic post-meeting minutes</h3>
    <p className="text-sm">Enable for this linked meeting before starting transcription in Teams. When Teams makes the transcript available after class, C.L.I.P fetches text and drafts private minutes automatically. Checkpoints and live microphone catch-up continue separately.</p>
    <p className="text-sm">This does not start Teams transcription or recording. No recording files are downloaded. Private summaries and short evidence excerpts are saved for up to 7 days for lecturer review; students and their chatbot receive only minutes you publish.</p>
    {error && <p role="alert">{error}</p>}
    {!status && !error && <p role="status">Checking automatic fetching…</p>}
    {status && <>
      {!status.configured && <p>Automatic fetching is disabled by the administrator.</p>}
      <p role="status">{status.message} {status.enabled && (status.subscribed ? 'Graph subscription is active.' : 'Graph subscription is not active yet; fallback checks remain available.')}</p>
      {status.configured && !status.enabled && <>
        <label className="flex gap-2"><input type="checkbox" checked={confirmed} onChange={e => setConfirmed(e.target.checked)} />I confirm participants were informed and institutional transcription and consent requirements were met, including private draft storage.</label>
        <button type="button" className={buttonStyles({ intent: 'secondary' })} disabled={!confirmed || busy} onClick={() => void change(true)}>Enable automatic transcript fetching</button>
      </>}
      {status.enabled && <button type="button" disabled={busy} className="underline" onClick={() => void change(false)}>Disable fetching and discard private drafts</button>}
      {status.pending > 0 && <p role="status">{status.pending} transcript draft(s) waiting or processing. You can leave this page.</p>}
      {status.failed > 0 && <p role="alert">{status.failed} transcript draft(s) could not be generated after retries. Check AI/Graph setup or use manual import below.</p>}
      {status.drafts.map(draft => <div key={draft.transcript_id} className="space-y-3 rounded border p-3">
        <p>{draft.warning} Private draft expires {new Date(draft.expires_at).toLocaleString()}.</p>
        <ol className="space-y-3">{draft.notes.map(note => <li key={note.note_id}>
          <time dateTime={note.occurred_at}>{new Date(note.occurred_at).toLocaleString()}</time>
          <p className="whitespace-pre-wrap">{note.text}</p>
          <details><summary>Check transcript evidence</summary><blockquote>{note.source_excerpt}</blockquote></details>
          <button type="button" disabled={busy || publishedIds.includes(note.note_id)} className="underline" onClick={() => onReview(note)}>{publishedIds.includes(note.note_id) ? 'Already published' : 'Review in publishing form'}</button>
        </li>)}</ol>
        <button type="button" disabled={busy} className="underline" onClick={() => void discard(draft.transcript_id)}>Discard this private draft</button>
      </div>)}
    </>}
    <button type="button" className="underline" disabled={busy} onClick={() => setRefresh(n => n + 1)}>Refresh automatic fetching</button>
  </section>
}
