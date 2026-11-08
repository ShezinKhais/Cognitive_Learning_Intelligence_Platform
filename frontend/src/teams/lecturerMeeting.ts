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
