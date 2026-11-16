import { groupOf } from '../sessions/format'
import type { StudentSession } from './types'

/**
 * The session a Teams meeting panel should show.
 *
 * A panel opened from a notification card carries ?sessionId= for the class
 * the card was about. That is the right answer while the class is running and
 * the wrong one once it has finished: the lecturer starts the next class in
 * the same meeting, link_meeting moves the meeting's link, and a requested id
 * that still matched would pin the panel to the old class for as long as it
 * stayed open, however often the list was refreshed.
 *
 * So the requested session wins only while it is unfinished. After that the
 * meeting's own session wins. The finished one is still returned when the
 * meeting has nothing else, so the student is told their class is over rather
 * than shown an empty panel.
 */
export function panelSession(
  sessions: readonly StudentSession[],
  requestedSessionId: string | null,
  meetingId: string | null,
): StudentSession | undefined {
  const requested = requestedSessionId
    ? sessions.find((candidate) => candidate.id === requestedSessionId)
    : undefined

  if (requested && groupOf(requested.status) !== 'finished') {
    return requested
  }

  const ofMeeting = meetingId
    ? sessions.find((candidate) => candidate.teams_meeting_id === meetingId)
    : undefined

  return ofMeeting ?? requested
}
