/**
 * The lecturer's Teams updates: the pop-ups C.L.I.P sends them during a class
 * (an alert, a checkpoint closing, engagement low across the class), whether
 * they are muted, and how many of the course's students C.L.I.P can reach in
 * Teams. Updates carry counts and course content, never a student's name.
 */

export type LecturerUpdateKind = 'alert' | 'checkpoint' | 'attention' | 'summary'

export interface LecturerUpdate {
  at: string
  kind: LecturerUpdateKind | string
  text: string
}

export interface TeamsUpdates {
  muted: boolean
  updates: LecturerUpdate[]
  students_on_course: number
  /** Null when Teams notifications are off for this deployment. */
  students_in_teams: number | null
}

export function teamsUpdatesPath(sessionId: string): string {
  return `/meetings/sessions/${encodeURIComponent(sessionId)}/updates`
}

export function teamsUpdatePagePath(sessionId: string): string {
  return `/lecturer/teams/update?sessionId=${encodeURIComponent(sessionId)}`
}

const KIND_LABEL: Record<LecturerUpdateKind, string> = {
  alert: 'Alert',
  checkpoint: 'Checkpoint',
  attention: 'Engagement',
  summary: 'Class summary',
}

export function updateKindLabel(kind: string): string {
  return KIND_LABEL[kind as LecturerUpdateKind] ?? 'Update'
}

/**
 * What to tell the lecturer about students C.L.I.P cannot reach in Teams, or
 * null when there is nothing to say. Only students who have opened C.L.I.P in
 * Teams once get checkpoint pop-ups.
 */
export function reachNotice(updates: Pick<TeamsUpdates, 'students_on_course' | 'students_in_teams'>): string | null {
  const { students_on_course: total, students_in_teams: reached } = updates
  if (reached === null || total === 0 || reached >= total) return null
  const missing = total - reached
  const who = missing === 1 ? '1 student has' : `${missing} students have`
  return `${who} not opened C.L.I.P in Teams yet, so checkpoints will not pop up for them. Ask the class to open it once from the meeting's side panel.`
}

/** "2 min ago", "just now": how long since an update, for a short list. */
export function updateAge(at: string, now: number = Date.now()): string {
  const then = Date.parse(at)
  if (Number.isNaN(then)) return ''
  const seconds = Math.max(0, Math.round((now - then) / 1000))
  if (seconds < 45) return 'just now'
  const minutes = Math.round(seconds / 60)
  if (minutes < 60) return `${minutes} min ago`
  const hours = Math.round(minutes / 60)
  return `${hours} h ago`
}
