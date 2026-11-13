import { useEffect, useState } from 'react'

import { useStudentApp } from '../features/student/StudentAppContext'
import type { StudentSession } from '../features/student/types'
import { useTeams } from '../teams/TeamsProvider'
import { LiveSessionPanel } from './StudentLiveSessionPage'

// How often an open panel asks again whether the lecturer has linked the
// meeting to a session. Also checked when the panel regains focus.
const LINK_RECHECK_MS = 10_000

export default function TeamsMeetingPage() {
  const teams = useTeams()
  const { sessions, refreshSessions } = useStudentApp()
  const requestedSessionId = new URLSearchParams(window.location.search).get('sessionId')
  const meetingId = teams.context?.meetingId ?? null
  const [recheckFailed, setRecheckFailed] = useState(false)

  const session = sessions.find(
    (candidate) =>
      (
        requestedSessionId &&
        candidate.id === requestedSessionId
      ) || (
        meetingId &&
        candidate.teams_meeting_id === meetingId
      ),
  ) ?? breakoutFallback(sessions, meetingId)

  // The lecturer may link the session after this panel opened. Until a
  // session appears, keep asking, so nobody has to close and reopen it.
  const waiting = teams.status === 'ready' && Boolean(meetingId) && !session
  useEffect(() => {
    if (!waiting) {
      return
    }
    let stopped = false
    const recheck = () => {
      refreshSessions().then(
        () => !stopped && setRecheckFailed(false),
        () => !stopped && setRecheckFailed(true),
      )
    }
    const timer = window.setInterval(recheck, LINK_RECHECK_MS)
    window.addEventListener('focus', recheck)
    return () => {
      stopped = true
      window.clearInterval(timer)
      window.removeEventListener('focus', recheck)
    }
  }, [waiting, refreshSessions])

  if (teams.status === 'initializing') {
    return <PanelStatus title="Connecting to Microsoft Teams" />
  }

  if (teams.status === 'error') {
    return (
      <PanelStatus
        title="Microsoft Teams unavailable"
        message={teams.error ?? 'The Teams context could not be loaded.'}
        isError
      />
    )
  }

  if (!teams.context && !requestedSessionId) {
    return (
      <PanelStatus
        title="Open this page in Teams"
        message="For local testing, add ?teamsMock=1&meetingId=YOUR_MEETING_ID to the URL."
      />
    )
  }

  if (teams.context && !['sidePanel', 'task'].includes(teams.context.frameContext)) {
    return (
      <PanelStatus
        title="Open the in-meeting panel"
        message="Open C.L.I.P from the meeting side panel or a checkpoint notification."
      />
    )
  }

  if (!session && waiting) {
    return (
      <PanelStatus
        title="Waiting for your lecturer"
        message={
          recheckFailed
            ? 'C.L.I.P could not be reached. It will keep trying.'
            : 'Your lecturer has not started C.L.I.P for this meeting yet. This panel opens the class as soon as they do.'
        }
      />
    )
  }

  if (!session) {
    return (
      <PanelStatus
        title="C.L.I.P session not found"
        message="This Teams meeting is not linked to a session assigned to your account."
        isError
      />
    )
  }

  // The checkpoint pop-up over the meeting shows only the question, so the
  // student answers and is back to the lecture in one step.
  const inDialog =
    teams.context?.frameContext === 'task' ||
    new URLSearchParams(window.location.search).get('view') === 'dialog'
  return <LiveSessionPanel session={session} compact dialog={inDialog} />
}

/**
 * A Teams breakout room is a meeting of its own, with its own meeting id, so
 * no session is linked to it. A student whose course has exactly one class
 * running is in that class, so the panel keeps showing it there.
 */
function breakoutFallback(sessions: StudentSession[], meetingId: string | null): StudentSession | undefined {
  if (!meetingId) return undefined
  const running = sessions.filter((candidate) => candidate.status === 'active')
  return running.length === 1 ? running[0] : undefined
}

function PanelStatus({
  title,
  message,
  isError = false,
}: {
  title: string
  message?: string
  isError?: boolean
}) {
  return (
    <main className="grid min-h-screen place-items-center bg-background p-4">
      <section
        role={isError ? 'alert' : 'status'}
        className="w-full max-w-sm rounded-xl border border-border bg-card p-5"
      >
        <h1 className={`text-lg font-semibold ${isError ? 'text-critical' : ''}`}>
          {title}
        </h1>
        {message && (
          <p className="mt-2 text-sm text-muted-foreground">{message}</p>
        )}
      </section>
    </main>
  )
}
