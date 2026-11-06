import { useEffect, useState } from 'react'
import { Link2, Play } from 'lucide-react'

import { ApiError, apiAuthenticatedGet, apiAuthenticatedRequest } from '../../api'
import { buttonStyles } from '../../components/ui/button'
import { listSessions, type SessionSummary } from '../sessions/sessionsApi'
import type { Course } from '../governance/accountsApi'
import { meetingClassPath, meetingClassSuggestionPath, meetingSessionPath } from '../../teams/lecturerMeeting'
import { linkableSessions } from './meetingLinking'

interface ClassSuggestion {
  meeting_title: string | null
  course_code: string | null
  title: string
  courses: Course[]
}

const FIELD = 'mt-1 w-full rounded-md border border-input bg-background px-3 py-2 text-sm'

/**
 * Shown in the lecturer's meeting side panel when no session is linked to the
 * meeting yet. Picking one links it (PUT /meetings/{id}), so the bot starts
 * and ends it with the meeting and the panel can show it.
 */
export default function MeetingSessionPicker({
  meetingId,
  onLinked,
}: {
  meetingId: string
  onLinked: (sessionId: string) => void
}) {
  const [sessions, setSessions] = useState<SessionSummary[] | null>(null)
  const [linking, setLinking] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  // Is this a class? For a meeting nobody prepared a session for: the course
  // and title are guessed from the meeting's title, and yes starts it here.
  const [suggestion, setSuggestion] = useState<ClassSuggestion | null>(null)
  const [courseCode, setCourseCode] = useState('')
  const [title, setTitle] = useState('')
  const [notAClass, setNotAClass] = useState(false)
  const [starting, setStarting] = useState(false)

  useEffect(() => {
    let cancelled = false
    apiAuthenticatedGet<ClassSuggestion>(meetingClassSuggestionPath(meetingId)).then(
      (found) => {
        if (cancelled) return
        setSuggestion(found)
        setCourseCode(found.course_code ?? '')
        setTitle(found.title)
      },
      () => {},
    )
    return () => {
      cancelled = true
    }
  }, [meetingId])

  async function startClass() {
    if (!courseCode.trim() || !title.trim()) return
    setStarting(true)
    setError(null)
    try {
      const session = await apiAuthenticatedRequest<{ id: string }>(meetingClassPath(meetingId), {
        method: 'POST',
        body: JSON.stringify({ course_code: courseCode.trim(), title: title.trim() }),
      })
      onLinked(session.id)
    } catch (caught) {
      setError(caught instanceof ApiError ? caught.message : 'The class could not be started. Try again.')
    } finally {
      setStarting(false)
    }
  }

  useEffect(() => {
    let cancelled = false
    listSessions().then(
      (page) => !cancelled && setSessions(linkableSessions(page.items)),
      () => !cancelled && setError('Your sessions could not be loaded. Close and reopen the panel.'),
    )
    return () => {
      cancelled = true
    }
  }, [])

  async function link(sessionId: string) {
    setLinking(sessionId)
    setError(null)
    try {
      await apiAuthenticatedRequest(meetingSessionPath(meetingId), {
        method: 'PUT',
        body: JSON.stringify({ session_id: sessionId }),
      })
      onLinked(sessionId)
    } catch (caught) {
      setError(caught instanceof ApiError ? caught.message : 'The session could not be linked. Try again.')
    } finally {
      setLinking(null)
    }
  }

  return (
    <main className="min-h-screen bg-background px-3 py-4">
      <div className="mx-auto max-w-md">
        <h1 className="text-lg font-bold">C.L.I.P in this meeting</h1>
        <p className="mt-1 text-sm text-muted-foreground">
          It then starts and ends with the meeting, and its controls appear here.
        </p>

        {error && (
          <p role="alert" className="mt-3 text-sm text-critical">
            {error}
          </p>
        )}

        {suggestion && !notAClass && (
          <section aria-label="Is this a class?" className="mt-4 rounded-lg border border-primary/40 bg-card p-3">
            <h2 className="font-semibold">Is this a class?</h2>
            <p className="mt-0.5 text-sm text-muted-foreground">
              {suggestion.meeting_title
                ? 'Not prepared in advance? Start it here. The course and title come from the meeting.'
                : 'Not prepared in advance? Start it here and C.L.I.P records engagement from now.'}
            </p>
            <label className="mt-3 block text-sm font-semibold">
              Course
              {suggestion.courses.length > 0 ? (
                <select className={FIELD} value={courseCode} onChange={(event) => setCourseCode(event.target.value)}>
                  {courseCode && !suggestion.courses.some((course) => course.code === courseCode) && (
                    <option value={courseCode}>{courseCode}</option>
                  )}
                  {suggestion.courses.map((course) => (
                    <option key={course.id} value={course.code}>
                      {course.code}: {course.name}
                    </option>
                  ))}
                </select>
              ) : (
                <input className={FIELD} value={courseCode} maxLength={20} onChange={(event) => setCourseCode(event.target.value)} />
              )}
            </label>
            <label className="mt-2 block text-sm font-semibold">
              Title
              <input className={FIELD} value={title} maxLength={200} onChange={(event) => setTitle(event.target.value)} />
            </label>
            <div className="mt-3 flex flex-wrap gap-2">
              <button
                type="button"
                disabled={starting || linking !== null || !courseCode.trim() || !title.trim()}
                onClick={() => void startClass()}
                className={buttonStyles()}
              >
                <Play size={15} aria-hidden />
                {starting ? 'Starting…' : 'Yes, start the class'}
              </button>
              <button type="button" onClick={() => setNotAClass(true)} className={buttonStyles({ intent: 'quiet' })}>
                Not a class
              </button>
            </div>
          </section>
        )}
        {notAClass && (
          <p className="mt-4 text-sm text-muted-foreground">
            C.L.I.P stays off for this meeting. Pick a prepared session below if you change your mind.
          </p>
        )}

        {sessions === null && !error && <p className="mt-4 text-sm text-muted-foreground">Loading your sessions…</p>}

        {sessions?.length === 0 && (
          <p className="mt-4 text-sm text-muted-foreground">
            You have no other prepared session for this meeting.
          </p>
        )}

        {sessions && sessions.length > 0 && (
          <ul className="mt-4 space-y-2">
            {sessions.map((session) => (
              <li key={session.id} className="rounded-lg border border-border bg-card p-3">
                <p className="text-xs font-semibold text-muted-foreground">{session.course_code}</p>
                <p className="line-clamp-2 font-semibold">{session.title}</p>
                <button
                  type="button"
                  disabled={linking !== null}
                  onClick={() => void link(session.id)}
                  className={buttonStyles({ intent: 'secondary', className: 'mt-2' })}
                >
                  <Link2 size={15} aria-hidden />
                  {linking === session.id ? 'Linking…' : 'Use in this meeting'}
                </button>
              </li>
            ))}
          </ul>
        )}
      </div>
    </main>
  )
}
