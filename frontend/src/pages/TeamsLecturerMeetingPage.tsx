import { useEffect, useRef, useState } from 'react'

import { ApiError, apiAuthenticatedGet } from '../api'
import LecturerMeetingPanel from '../features/live/LecturerMeetingPanel'
import MeetingSessionPicker from '../features/live/MeetingSessionPicker'
import {
  meetingSessionPath,
  meetingSessionWatcher,
  shouldAdoptMeetingSession,
  shouldWatchMeetingSession,
  type MeetingSession,
} from '../teams/lecturerMeeting'
import { useTeams } from '../teams/TeamsProvider'
import { closeTeamsDialog } from '../teams/teamsClient'

// How often an open panel asks again whether a session has appeared for this
// meeting. Also checked when the panel regains focus. The student panel in
// TeamsMeetingPage uses the same interval.
const LINK_RECHECK_MS = 10_000

/**
 * Resolves the lecturer's Microsoft Teams meeting surface to its session and
 * shows the compact lecturer panel, which links to the full workspace.
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

  const query = new URLSearchParams(window.location.search)
  const hintedSessionId = query.get('sessionId')
  // The pop-up C.L.I.P opens for the organiser as they join a meeting with
  // no class. Teams may not give a dialog the meeting's context, so the
  // meeting comes with it; the backend still checks they organised it.
  const inDialog = query.get('view') === 'dialog'
  const hintedMeetingId = query.get('meetingId')

  const [sessionId, setSessionId] = useState<string | null>(null)
  // What the recheck below compares against, read outside a state updater.
  const shownSessionId = useRef<string | null>(null)
  useEffect(() => {
    shownSessionId.current = sessionId
  }, [sessionId])
  const [isLoading, setIsLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  // The meeting has no session of the lecturer's yet: offer to link one.
  const [unlinked, setUnlinked] = useState(false)

  const meetingId = teams.context?.meetingId ?? hintedMeetingId ?? null

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
        setUnlinked(false)

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
          if (caught instanceof ApiError && caught.status === 404) {
            setUnlinked(true)
            return
          }
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

  /*
   * The meeting can move on while this panel is open, and nothing tells it.
   * The class is started from the app, or the class ends and the next one is
   * started, and link_meeting replaces what the meeting holds. The effect
   * above only runs when the meeting id or the Teams status changes, neither
   * of which happens then, so the panel would keep showing a session that is
   * no longer the meeting's, or sit on the picker forever.
   *
   * So keep asking, and adopt the answer only when it is a different session.
   * This never clears isLoading or unlinked and never reacts to a failure:
   * it only ever moves the panel onto a session that exists. Clearing them
   * would remount MeetingSessionPicker on every poll and throw away a class
   * title the lecturer was part way through typing.
   */
  const watching = shouldWatchMeetingSession(teams.status === 'ready', meetingId)
  useEffect(() => {
    if (!watching || !meetingId) {
      return
    }

    const watcher = meetingSessionWatcher(
      () => apiAuthenticatedGet<MeetingSession>(meetingSessionPath(meetingId)),
      (found) => {
        if (!shouldAdoptMeetingSession(shownSessionId.current, found)) {
          return
        }
        shownSessionId.current = found
        setUnlinked(false)
        setError(null)
        setSessionId(found)
      },
    )
    const recheck = () => watcher.recheck()

    const timer = window.setInterval(recheck, LINK_RECHECK_MS)
    window.addEventListener('focus', recheck)
    return () => {
      watcher.stop()
      window.clearInterval(timer)
      window.removeEventListener('focus', recheck)
    }
  }, [watching, meetingId])

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

  if (unlinked && meetingId && !sessionId) {
    return (
      <MeetingSessionPicker
        meetingId={meetingId}
        onLinked={(linked) => {
          // From the pop-up, the class is set up: back to the call.
          if (inDialog && closeTeamsDialog()) return
          setUnlinked(false)
          setSessionId(linked)
        }}
      />
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

  return <LecturerMeetingPanel sessionId={sessionId} />
}