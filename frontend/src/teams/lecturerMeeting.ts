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
/**
 * Asks the meeting repeatedly, and ignores an answer it has overtaken.
 *
 * The interval and the focus listener both ask, so two lookups can be in
 * flight at once. They are not answered in the order they were sent: a slow
 * answer about the meeting as it was can arrive after a later one has already
 * moved the panel on, and would drag it back to the class that has finished.
 *
 * Each lookup takes a ticket, and only the newest ticket may adopt. A
 * superseded answer is about a state the meeting has already left, so there is
 * nothing in it worth having.
 */
export function meetingSessionWatcher(
  lookup: () => Promise<{ id?: string | null }>,
  adopt: (sessionId: string) => void,
): { recheck: () => void; stop: () => void } {
  let latest = 0
  let stopped = false

  return {
    recheck(): void {
      latest += 1
      const ticket = latest
      void lookup().then(
        (session) => {
          if (stopped || ticket !== latest || !session?.id) {
            return
          }
          adopt(session.id)
        },
        // Still unlinked, or the lookup failed. Keep what is on screen and
        // ask again; the first resolve already reported anything worse.
        () => undefined,
      )
    },
    stop(): void {
      stopped = true
    },
  }
}

export function shouldAdoptMeetingSession(
  currentSessionId: string | null,
  resolvedSessionId: string | null | undefined,
): boolean {
  return Boolean(resolvedSessionId) && resolvedSessionId !== currentSessionId
}
