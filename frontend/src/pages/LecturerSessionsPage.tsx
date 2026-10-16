import { useEffect, useState, type FormEvent } from 'react'
import { Plus } from 'lucide-react'
import { Link, useNavigate } from 'react-router'

import { ApiError, clearAccessToken } from '../api'
import { cn } from '../components/ui/cn'
import { buttonStyles } from '../components/ui/button'
import { EmptyState, PageBody, PageHeader, Panel, Tag } from '../components/ui/primitives'
import { createSession } from '../features/live/sessionActions'
import { formatWhen, groupSessions, statusLabel, statusTone } from '../features/sessions/format'
import { listSessions, type SessionSummary } from '../features/sessions/sessionsApi'

type Load = { state: 'loading' } | { state: 'error'; message: string } | { state: 'ready'; sessions: SessionSummary[] }

function signInAgain(): void {
  clearAccessToken()
  window.location.assign('/login')
}

export default function LecturerSessionsPage() {
  const [load, setLoad] = useState<Load>({ state: 'loading' })
  const [creating, setCreating] = useState(false)

  useEffect(() => {
    let cancelled = false
    listSessions()
      .then((page) => !cancelled && setLoad({ state: 'ready', sessions: page.items }))
      .catch((error: unknown) => {
        if (cancelled) return
        if (error instanceof ApiError && error.status === 401) return signInAgain()
        setLoad({
          state: 'error',
          message: error instanceof ApiError ? error.message : 'Sessions could not be loaded. Check your connection.',
        })
      })
    return () => {
      cancelled = true
    }
  }, [])

  const sessions = load.state === 'ready' ? load.sessions : []
  const groups = groupSessions(sessions)

  return (
    <>
      <PageHeader
        title="Sessions"
        description="Prepare a class, run it live, and read how it went."
        actions={
          <button type="button" className={buttonStyles()} onClick={() => setCreating((open) => !open)} aria-expanded={creating}>
            <Plus size={16} aria-hidden />
            New session
          </button>
        }
      />
      <PageBody>
        {creating && <CreateSession onCancel={() => setCreating(false)} />}

        {load.state === 'loading' && <p className="text-muted-foreground" role="status">Loading your sessions…</p>}
        {load.state === 'error' && (
          <p role="alert" className="rounded-md border border-critical/30 bg-critical/5 px-4 py-3 text-critical">
            {load.message}
          </p>
        )}

        {load.state === 'ready' && sessions.length === 0 && !creating && (
          <EmptyState
            title="No sessions yet"
            action={
              <button type="button" className={buttonStyles()} onClick={() => setCreating(true)}>
                Create your first session
              </button>
            }
          >
            A session is one class. Create it with the course code of the material you prepared, then open it to go
            live.
          </EmptyState>
        )}

        {groups.live.length > 0 && <SessionList heading="Live now" sessions={groups.live} />}
        {groups.prepared.length > 0 && <SessionList heading="Prepared" sessions={groups.prepared} />}
        {groups.finished.length > 0 && <SessionList heading="Finished" sessions={groups.finished} />}
      </PageBody>
    </>
  )
}

function SessionList({ heading, sessions }: { heading: string; sessions: SessionSummary[] }) {
  return (
    <section className="mb-10" aria-labelledby={`group-${heading}`}>
      <h2 id={`group-${heading}`} className="mb-3 text-lg font-bold">
        {heading} <span className="font-normal text-muted-foreground">{sessions.length}</span>
      </h2>
      <ul className="divide-y divide-border overflow-hidden rounded-lg border border-border bg-card">
        {sessions.map((session) => (
          <li key={session.id}>
            <SessionRow session={session} />
          </li>
        ))}
      </ul>
    </section>
  )
}

function SessionRow({ session }: { session: SessionSummary }) {
  const finished = session.status === 'ended' || session.status === 'cancelled'
  const live = `/lecturer/sessions/${session.id}/live`
  const report = `/lecturer/sessions/${session.id}/report`
  return (
    <div className="grid gap-3 px-5 py-4 sm:grid-cols-[1fr_auto] sm:items-center">
      <div className="min-w-0">
        <div className="flex flex-wrap items-center gap-2">
          <Tag tone={statusTone(session)}>{statusLabel(session)}</Tag>
          <span className="text-sm font-semibold text-muted-foreground">{session.course_code}</span>
        </div>
        <Link to={finished ? report : live} className="mt-1 block truncate text-[1.05rem] font-bold hover:underline">
          {session.title}
        </Link>
        <p className="mt-0.5 text-sm text-muted-foreground">
          {formatWhen(session.ended_at ?? session.starts_at)}
          {session.questions_delivered > 0 &&
            `, ${session.questions_delivered} ${session.questions_delivered === 1 ? 'question' : 'questions'} asked`}
          {session.participant_count > 0 && `, ${session.participant_count} joined`}
        </p>
      </div>
      <div className="flex flex-wrap gap-2">
        {!finished && (
          <Link to={live} className={buttonStyles({ intent: session.status === 'active' ? 'primary' : 'secondary' })}>
            {session.status === 'active' ? 'Open live view' : 'Open workspace'}
          </Link>
        )}
        {session.status !== 'prepared' && session.status !== 'cancelled' && (
          <Link to={report} className={buttonStyles({ intent: finished ? 'primary' : 'quiet' })}>
            Report
          </Link>
        )}
      </div>
    </div>
  )
}

function CreateSession({ onCancel }: { onCancel: () => void }) {
  const navigate = useNavigate()
  const [courseCode, setCourseCode] = useState('')
  const [title, setTitle] = useState('')
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState<string | null>(null)

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    const course = courseCode.trim()
    const name = title.trim()
    if (!course) return setError('Enter the course code for this session.')
    if (!name) return setError('Enter a title for this session.')
    setSaving(true)
    setError(null)
    try {
      const session = await createSession({ course_code: course, title: name })
      navigate(`/lecturer/sessions/${session.id}/live`)
    } catch (caught: unknown) {
      if (caught instanceof ApiError && caught.status === 401) return signInAgain()
      setError(
        caught instanceof ApiError ? caught.message : 'The session could not be created. Check your connection and try again.',
      )
    } finally {
      setSaving(false)
    }
  }

  const field =
    'mt-1.5 w-full rounded-md border border-input bg-input-background px-3 py-2.5 disabled:cursor-not-allowed disabled:opacity-60'

  return (
    <Panel
      className="mb-10 max-w-2xl"
      title="New session"
      description="Use the course code of the material you prepared, so its approved questions are ready to send."
    >
      <form className="grid gap-4 sm:grid-cols-[12rem_1fr]" onSubmit={submit}>
        <label className="text-sm font-semibold">
          Course code
          <input
            value={courseCode}
            onChange={(event) => setCourseCode(event.target.value)}
            placeholder="CSIT321"
            autoComplete="off"
            disabled={saving}
            className={field}
          />
        </label>
        <label className="text-sm font-semibold">
          Title
          <input
            value={title}
            onChange={(event) => setTitle(event.target.value)}
            placeholder="Week 7: Threat modelling"
            autoComplete="off"
            disabled={saving}
            className={field}
          />
        </label>
        {error && (
          <p role="alert" className="text-sm text-critical sm:col-span-2">
            {error}
          </p>
        )}
        <div className="flex gap-2 sm:col-span-2">
          <button type="submit" disabled={saving} className={cn(buttonStyles())}>
            {saving ? 'Creating…' : 'Create and open'}
          </button>
          <button type="button" onClick={onCancel} className={buttonStyles({ intent: 'quiet' })}>
            Cancel
          </button>
        </div>
      </form>
    </Panel>
  )
}
