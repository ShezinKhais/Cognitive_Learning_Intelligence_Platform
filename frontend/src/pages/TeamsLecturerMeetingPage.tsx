import { useEffect, useState } from 'react'
import { Navigate } from 'react-router'

import { apiAuthenticatedGet } from '../api'
import {
  lecturerLiveSessionPath,
  meetingSessionPath,
  type MeetingSession,
} from '../teams/lecturerMeeting'
import { useTeams } from '../teams/TeamsProvider'

/**
 * Resolves the lecturer's Microsoft Teams meeting surface to the existing
 * C.L.I.P lecturer workspace.
 *
 * Microsoft Teams supplies meeting context only. It does not authorize
 * access to the lecturer workspace. C.L.I.P authentication, consent and
 * role checks remain authoritative.
 *
 * In Microsoft Teams, the meeting ID is resolved through the authenticated
 * C.L.I.P meeting endpoint. For standalone/mock development, ?sessionId=
 * remains available as an optional routing hint.
 */
export default function TeamsLecturerMeetingPage() {
  const teams = useTeams()

  const hintedSessionId =
    new URLSearchParams(window.location.search).get('sessionId')

  const [sessionId, setSessionId] = useState<string | null>(null)
  const [isLoading, setIsLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  const meetingId = teams.context?.meetingId ?? null

  useEffect(() => {
    if (teams.status === 'initializing') {
      return
    }

    /*
     * A real Teams meeting context takes priority over the optional
     * standalone/mock session hint.
     */
    if (teams.status === 'ready' && meetingId) {
      const resolvedMeetingId = meetingId
      let active = true

      async function resolveMeetingSession(): Promise<void> {
        setIsLoading(true)
        setError(null)

        try {
          const session = await apiAuthenticatedGet<MeetingSession>(
            meetingSessionPath(resolvedMeetingId),
          )

          if (!active) {
            return
          }

          if (!session.id) {
            throw new Error(
              'The meeting lookup did not return a C.L.I.P session.',
            )
          }

          setSessionId(session.id)
        } catch (caught: unknown) {
          if (!active) {
            return
          }

          setSessionId(null)
          setError(
            caught instanceof Error
              ? caught.message
              : 'C.L.I.P could not resolve this Teams meeting.',
          )
        } finally {
          if (active) {
            setIsLoading(false)
          }
        }
      }

      void resolveMeetingSession()

      return () => {
        active = false
      }
    }

    /*
     * Standalone/mock fallback. This is only a routing hint; the existing
     * C.L.I.P authentication, role and backend authorization still apply.
     */
    if (hintedSessionId) {
      setSessionId(hintedSessionId)
      setError(null)
      setIsLoading(false)
      return
    }

    setSessionId(null)
    setError(
      'C.L.I.P could not determine the Microsoft Teams meeting.',
    )
    setIsLoading(false)
  }, [hintedSessionId, meetingId, teams.status])

  if (teams.status === 'initializing' || isLoading) {
    return (
      <main className="grid min-h-screen place-items-center bg-background p-6">
        <section
          role="status"
          className="w-full max-w-md rounded-xl border border-border bg-card p-6"
        >
          <h1 className="text-xl font-semibold">
            Opening lecturer session
          </h1>

          <p className="mt-2 text-sm text-muted-foreground">
            C.L.I.P is resolving this Microsoft Teams meeting.
          </p>
        </section>
      </main>
    )
  }

  if (error || !sessionId) {
    return (
      <main className="grid min-h-screen place-items-center bg-background p-6">
        <section
          role="status"
          className="w-full max-w-md rounded-xl border border-border bg-card p-6"
        >
          <h1 className="text-xl font-semibold">
            Lecturer meeting session unavailable
          </h1>

          <p className="mt-2 text-sm text-muted-foreground">
            {error ??
              'No authorised C.L.I.P session is linked to this Teams meeting.'}
          </p>
        </section>
      </main>
    )
  }

  return (
    <Navigate
      to={lecturerLiveSessionPath(sessionId)}
      replace
    />
  )
}