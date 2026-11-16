export interface MeetingSession {
  id: string
  teams_meeting_id?: string | null
}

export function meetingSessionPath(meetingId: string): string {
  return `/meetings/${encodeURIComponent(meetingId)}`
}

export function lecturerLiveSessionPath(sessionId: string): string {
  return `/lecturer/sessions/${encodeURIComponent(sessionId)}/live`
}

export function meetingClassSuggestionPath(meetingId: string): string {
  return `${meetingSessionPath(meetingId)}/class-suggestion`
}

export function meetingClassPath(meetingId: string): string {
  return `${meetingSessionPath(meetingId)}/class`
}

/**
 * Whether an open lecturer panel should keep asking this meeting for its
 * session. Only the meeting has to be known: the panel asks whether or not it
 * already holds one.
 *
 * A panel that resolved a session keeps it for as long as it is open, but the
 * meeting can move on underneath it. The class ends and the lecturer starts
 * the next one from the app, and link_meeting replaces the meeting's link. A
 * panel that stopped asking once it had a session sits on the finished one.
 */
export function shouldWatchMeetingSession(
  teamsReady: boolean,
  meetingId: string | null,
): boolean {
  return teamsReady && Boolean(meetingId)
}

/**
 * Whether a lookup's answer should replace the session the panel is showing.
 *
 * Only a real session id that differs from the current one. A repeat of what
 * is already shown must not be adopted, or the panel would remount on every
 * poll and throw away what it is doing.
 */
export function shouldAdoptMeetingSession(
  currentSessionId: string | null,
  resolvedSessionId: string | null | undefined,
): boolean {
  return Boolean(resolvedSessionId) && resolvedSessionId !== currentSessionId
}
