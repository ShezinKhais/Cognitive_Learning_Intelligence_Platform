import { useEffect, useRef, useState } from 'react'
import { apiAuthenticatedGet, apiAuthenticatedRequest } from '../../api'
import AutomaticTranscriptPanel from './AutomaticTranscriptPanel'
import { buttonStyles } from '../../components/ui/button'

export interface DraftMinute {
  note_id: string
  occurred_at: string
  text: string
  source_excerpt: string
  source_offset_seconds: number
}
interface TranscriptList {
  enabled: boolean
  items: { id: string; created_at: string }[]
  message: string | null
}

/** Manual drafts stay in memory; automatic drafts use the private server queue. */
export default function TranscriptDraftPanel({ sessionId, publishedIds, onReview }: {
  sessionId: string
  publishedIds: string[]
  onReview: (note: DraftMinute) => void
}) {
  const [list, setList] = useState<TranscriptList | null>(null)
  const [selected, setSelected] = useState('')
  const [confirmed, setConfirmed] = useState(false)
  const [notes, setNotes] = useState<DraftMinute[]>([])
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [warning, setWarning] = useState('')
  const [refresh, setRefresh] = useState(0)
  const controller = useRef<AbortController | null>(null)
  useEffect(() => () => controller.current?.abort(), [])
  useEffect(() => {
    let stopped = false
    void apiAuthenticatedGet<TranscriptList>(`/sessions/${sessionId}/discussion/transcripts`)
      .then(value => { if (!stopped) { setList(value); setSelected(value.items[0]?.id ?? ''); setError(null) } })
      .catch(caught => { if (!stopped) setError(caught instanceof Error ? caught.message : 'Could not list Teams transcripts.') })
    return () => { stopped = true }
  }, [sessionId, refresh])

  async function draft() {
    if (!confirmed || !selected || busy) return
    const abort = new AbortController()
    controller.current = abort
    setBusy(true); setError(null); setNotes([]); setWarning('')
    try {
      const result = await apiAuthenticatedRequest<{ notes: DraftMinute[]; warning: string }>(`/sessions/${sessionId}/discussion/transcript-draft`, {
        method: 'POST', headers: { 'Content-Type': 'application/json' }, signal: abort.signal,
        body: JSON.stringify({ transcript_id: selected, participant_notice_confirmed: confirmed }),
      })
      if (!abort.signal.aborted) { setNotes(result.notes); setWarning(result.warning) }
    } catch (caught) {
      if (!abort.signal.aborted) setError(caught instanceof Error ? caught.message : 'Could not draft minutes. Nothing was published.')
    } finally {
      if (controller.current === abort) { controller.current = null; setBusy(false) }
    }
  }

  return <section className="space-y-3 rounded-lg border border-border p-4" aria-label="Minutes from Teams transcript">
    <AutomaticTranscriptPanel sessionId={sessionId} publishedIds={publishedIds} onReview={onReview} />
    <h3 className="font-semibold">Draft minutes from a Teams transcript</h3>
    <p className="text-sm">After class, start with a transcript made in Teams. C.L.I.P imports text and drafts teaching minutes for your review. This does not start a recording or transcription, and does not import audio or video.</p>
    <p className="text-sm">Participants must be informed and the institution’s transcription and consent requirements met. Speaker labels, email addresses and links are removed before drafting; check for remaining personal details. Raw transcripts are never saved in C.L.I.P. Manual drafts remain in this page; automatic drafts use the private, expiring storage described above.</p>
    {error && <p role="alert">{error}</p>}
    {!list && !error && <p role="status">Checking transcript availability…</p>}
    {list?.message && <p>{list.message}</p>}
    <button type="button" className="underline" disabled={busy} onClick={() => setRefresh(n => n + 1)}>Refresh transcript list</button>
    {list?.enabled && list.items.length > 0 && <>
      <label className="block">Teams transcript
        <select className="ml-3 rounded border p-2" value={selected} disabled={busy} onChange={event => { setSelected(event.target.value); setConfirmed(false); setNotes([]); setWarning('') }}>
          {list.items.map((item, i) => <option key={item.id} value={item.id}>Transcript {i + 1} — {new Date(item.created_at).toLocaleString()}</option>)}
        </select>
      </label>
      <label className="flex gap-2"><input type="checkbox" disabled={busy} checked={confirmed} onChange={event => setConfirmed(event.target.checked)} />
        I confirm participants were informed and the institution’s transcription and consent requirements were met.
      </label>
      <button type="button" className={buttonStyles({ intent: 'secondary' })} disabled={!confirmed || !selected || busy} onClick={() => void draft()}>Generate draft minutes</button>
    </>}
    {busy && <div role="status">Drafting can take a few minutes. Nothing is published automatically. <button type="button" className="underline" onClick={() => { controller.current?.abort(); controller.current = null; setBusy(false) }}>Cancel drafting</button></div>}
    {notes.length > 0 && <>
      <p role="status">{warning} Times are estimated from transcript creation time plus cue offset; correct them if needed.</p>
      <p className="text-sm">Drafts disappear when you leave this page. Published minutes follow session retention. The original Teams transcript stays under your Microsoft 365 policies.</p>
      <ol className="space-y-4">{notes.map(note => <li key={note.note_id} className="rounded border border-border p-3">
        <time dateTime={note.occurred_at}>{new Date(note.occurred_at).toLocaleString()}</time>
        <p className="whitespace-pre-wrap">{note.text}</p>
        <details><summary>Check transcript evidence (offset {Math.floor(note.source_offset_seconds / 60)}:{String(Math.floor(note.source_offset_seconds % 60)).padStart(2, '0')})</summary><blockquote className="whitespace-pre-wrap border-l-2 pl-3">{note.source_excerpt}</blockquote></details>
        <button type="button" className="underline" disabled={publishedIds.includes(note.note_id)} onClick={() => onReview(note)}>{publishedIds.includes(note.note_id) ? 'Already published — edit in published minutes' : 'Review in publishing form'}</button>
      </li>)}</ol>
      <button type="button" className="underline" onClick={() => { setNotes([]); setWarning('') }}>Discard unpublished drafts</button>
    </>}
  </section>
}
