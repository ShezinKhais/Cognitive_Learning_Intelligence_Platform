import { useEffect, useState } from 'react'
import { Link2 } from 'lucide-react'

import { ApiError, apiAuthenticatedRequest } from '../../api'
import { buttonStyles } from '../../components/ui/button'
import { listSessions, type SessionSummary } from '../sessions/sessionsApi'
import { meetingSessionPath } from '../../teams/lecturerMeeting'
import { linkableSessions } from './meetingLinking'

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
        <h1 className="text-lg font-bold">Choose the session for this meeting</h1>
        <p className="mt-1 text-sm text-muted-foreground">
          It then starts and ends with the meeting, and its controls appear here.
        </p>

        {error && (
          <p role="alert" className="mt-3 text-sm text-critical">
            {error}
          </p>
        )}

        {sessions === null && !error && <p className="mt-4 text-sm text-muted-foreground">Loading your sessions…</p>}

        {sessions?.length === 0 && (
          <p className="mt-4 text-sm">
            You have no prepared session. Prepare one on the lecturer dashboard, then reopen this panel.
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
