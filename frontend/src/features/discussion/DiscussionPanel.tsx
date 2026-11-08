import { useEffect, useRef, useState } from 'react'

import { ApiError, apiAuthenticatedGet, apiAuthenticatedRequest } from '../../api'
import { buttonStyles } from '../../components/ui/button'
import { SocraticChatPanel } from '../chat/SocraticChatPanel'
import TranscriptDraftPanel from './TranscriptDraftPanel'
import LiveTranscriptionControls from './LiveTranscriptionControls'

interface Note {
  note_id: string
  occurred_at: string
  text: string
  updated_at: string
  origin?: string
}
interface Discussion {
  notes: Note[]
  latest_recorded_at: string | null
  session_status: string
  live_transcription_active?: boolean
}

function localTime() {
  const date = new Date()
  return new Date(date.getTime() - date.getTimezoneOffset() * 60_000).toISOString().slice(0, 16)
}

/** Published minutes are visible live and retained for post-session catch-up. */
export default function DiscussionPanel({ sessionId, publisher = false, chatEnabled = import.meta.env.VITE_SOCRATIC_CHAT_ENABLED === 'true' }: { sessionId: string; publisher?: boolean; chatEnabled?: boolean }) {
  const editor = useRef<HTMLTextAreaElement>(null)
  const [data, setData] = useState<Discussion | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [refresh, setRefresh] = useState(0)
  const [range, setRange] = useState('all')
  const [since, setSince] = useState<string | undefined>()
  const [until, setUntil] = useState<string | undefined>()
  const [text, setText] = useState('')
  const [time, setTime] = useState(localTime)
  const [confirmed, setConfirmed] = useState(false)
  const [saving, setSaving] = useState(false)
  const [editing, setEditing] = useState<string | null>(null)
  const [removing, setRemoving] = useState<string | null>(null)
  const [pendingId, setPendingId] = useState<string | null>(null)

  useEffect(() => {
    let stopped = false
    let pending = false
    const check = async () => {
      if (pending) return
      pending = true
      try {
        const found = await apiAuthenticatedGet<Discussion>(`/sessions/${sessionId}/discussion`)
        if (!stopped) {
          setData(found)
          setError(null)
        }
      } catch (caught) {
        if (!stopped) setError(caught instanceof ApiError ? caught.message : 'Could not refresh discussion notes.')
      } finally { pending = false }
    }
    void check()
    const timer = window.setInterval(() => void check(), 5_000)
    return () => { stopped = true; window.clearInterval(timer) }
  }, [sessionId, refresh])

  function selectRange(value: string) {
    setRange(value)
    // Anchor the window so follow-ups keep the same discussion context.
    const end = data?.session_status === 'ended' && data.latest_recorded_at
      ? new Date(data.latest_recorded_at) : new Date()
    setUntil(value === 'all' ? undefined : end.toISOString())
    setSince(value === 'all' ? undefined : new Date(end.getTime() - Number(value) * 60_000).toISOString())
  }

  async function publish() {
    if (!text.trim() || !confirmed || saving) return
    const id = editing ?? pendingId ?? crypto.randomUUID()
    setPendingId(id)
    setSaving(true)
    try {
      await apiAuthenticatedRequest(`/sessions/${sessionId}/discussion/${id}`, {
        method: 'PUT', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ text, occurred_at: new Date(time).toISOString(), shareable_confirmed: confirmed }),
      })
      setText(''); setConfirmed(false); setEditing(null); setPendingId(null)
      setTime(localTime()); setRefresh(n => n + 1)
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : 'The note could not be published. Try again.')
    } finally { setSaving(false) }
  }

  async function remove(id: string) {
    setSaving(true)
    try {
      await apiAuthenticatedRequest(`/sessions/${sessionId}/discussion/${id}`, { method: 'DELETE' })
      setRemoving(null)
      if (editing === id) { setEditing(null); setText(''); setConfirmed(false); setPendingId(null) }
      setRefresh(n => n + 1)
    } catch {
      setError('The note could not be removed. Try again.')
    } finally { setSaving(false) }
  }

  return (
    <section className="my-6 space-y-4 rounded-xl border border-border bg-card p-4" aria-label="Session catch-up">
      <h2 className="text-lg font-semibold">{publisher ? 'Discussion minutes and live speech' : 'Catch up on this session'}</h2>
      <p className="text-sm text-muted-foreground">
        Reviewed minutes and automatic transcripts may cover only part of the discussion. Updates are checked every 5 seconds.
        {data?.latest_recorded_at && ` Latest recorded discussion: ${new Date(data.latest_recorded_at).toLocaleString()}.`}
      </p>
      {error && <p role="alert">{error} <button className="underline" onClick={() => setRefresh(n => n + 1)}>Try again</button></p>}
      {data?.live_transcription_active && <p role="status">Live lecturer microphone transcription is on. Automatic text may contain errors and is available to the chatbot as it arrives.</p>}
      {publisher && <LiveTranscriptionControls sessionId={sessionId} onUpdate={() => setRefresh(n => n + 1)} />}
      {publisher && (
        <form className="space-y-3" onSubmit={event => { event.preventDefault(); void publish() }}>
          <label className="block">Discussion time
            <input className="block rounded border p-2" type="datetime-local" required value={time} onChange={e => setTime(e.target.value)} />
          </label>
          <label className="block">Minutes to share with the course
            <textarea ref={editor} className="block w-full rounded border p-2" rows={4} required maxLength={2000} value={text} onChange={e => setText(e.target.value)} />
          </label>
          <p className="text-sm">Record teaching points and anonymized questions. Remove student names, personal details and assessment solutions.</p>
          <label className="flex gap-2"><input type="checkbox" checked={confirmed} onChange={e => setConfirmed(e.target.checked)} />
            I reviewed these minutes and confirm they are suitable to share with this course.
          </label>
          <button className={buttonStyles()} disabled={saving || !confirmed || !text.trim()}>{saving ? 'Saving…' : editing ? 'Save changes' : 'Publish note'}</button>
          {editing && <button type="button" className="ml-3 underline" onClick={() => { setEditing(null); setPendingId(null); setText(''); setConfirmed(false); setTime(localTime()) }}>Cancel edit</button>}
        </form>
      )}
      {publisher && <TranscriptDraftPanel sessionId={sessionId} publishedIds={data?.notes.map(note => note.note_id) ?? []} onReview={note => {
        setEditing(null); setPendingId(note.note_id); setText(note.text); setConfirmed(false)
        const date = new Date(note.occurred_at)
        setTime(new Date(date.getTime() - date.getTimezoneOffset() * 60_000).toISOString().slice(0, 16))
        editor.current?.focus()
      }} />}
      {!data && !error && <p role="status">Loading discussion notes…</p>}
      {data?.notes.length === 0 && <p>No discussion notes have been published. Check again after your lecturer adds them or enables live transcription.</p>}
      {data && data.notes.length > 0 && (
        <details>
          <summary className="cursor-pointer font-semibold">Read session record ({data.notes.length})</summary>
          <ol className="max-h-96 space-y-4 overflow-y-auto py-3">
            {data.notes.map(note => (
              <li key={note.note_id} id={`discussion-${note.note_id}`}>
                <time dateTime={note.occurred_at} className="font-semibold">{new Date(note.occurred_at).toLocaleString()}</time>
                <p className="text-xs font-semibold">{note.origin === 'live_transcript' ? 'Automatic live transcript — unreviewed' : 'Lecturer-reviewed minutes'}</p>
                <p className="whitespace-pre-wrap">{note.text}</p>
                {publisher && <div className="flex gap-3">
                  <button disabled={saving} className="underline" onClick={() => {
                    setEditing(note.note_id); setPendingId(null); setText(note.text); setConfirmed(false)
                    const date = new Date(note.occurred_at)
                    setTime(new Date(date.getTime() - date.getTimezoneOffset() * 60_000).toISOString().slice(0, 16))
                  }}>Edit</button>
                  {removing === note.note_id ? <>
                    <button disabled={saving} className="underline" onClick={() => void remove(note.note_id)}>Confirm removal</button>
                    <button disabled={saving} className="underline" onClick={() => setRemoving(null)}>Keep note</button>
                  </> : <button disabled={saving} className="underline" onClick={() => setRemoving(note.note_id)}>Remove published note</button>}
                </div>}
              </li>
            ))}
          </ol>
        </details>
      )}
      {!publisher && chatEnabled && data && data.notes.length > 0 && (
        <>
          <label className="block">Discussion to ask about
            <select className="ml-3 rounded border p-2" value={range} onChange={e => selectRange(e.target.value)}>
              <option value="all">All recorded notes</option>
              <option value="10">Last 10 recorded minutes</option><option value="30">Last 30 recorded minutes</option>
            </select>
          </label>
          {data.session_status === 'active' && range !== 'all' && <p className="text-xs">This live time window moves forward each time you ask.</p>}
          <SocraticChatPanel key={`${sessionId}-${since ?? 'all'}`} sessionId={sessionId} compact discussion discussionSince={since} discussionUntil={until} discussionRollingMinutes={data.session_status === 'active' && range !== 'all' ? Number(range) : undefined} />
        </>
      )}
    </section>
  )
}
