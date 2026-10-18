import { ApiError, apiAuthenticatedGet, type Page } from '../../api'

export type SessionStatus = 'prepared' | 'active' | 'ending' | 'ended' | 'cancelled'

export interface SessionSummary {
  id: string
  course_code: string
  title: string
  status: SessionStatus
  starts_at: string | null
  ended_at: string | null
  lecturer_id: string
  participant_count: number
  questions_delivered: number
  paused: boolean
  teams_meeting_id: string | null
}

export interface SessionResponse {
  id: string
  question_id: string
  student_id: string
  selected_option: number | null
  free_text: string | null
  is_correct: boolean | null
  elapsed_ms: number | null
  submitted_at: string
}

const session = (id: string) => `/sessions/${encodeURIComponent(id)}`

export function listSessions(limit = 100): Promise<Page<SessionSummary>> {
  return apiAuthenticatedGet<Page<SessionSummary>>(`/sessions?limit=${limit}`)
}

export function getSession(id: string): Promise<SessionSummary> {
  return apiAuthenticatedGet<SessionSummary>(session(id))
}

/** Every response a session holds, read a page at a time. A student is
 * given only their own. */
export async function listAllResponses(id: string): Promise<SessionResponse[]> {
  const all: SessionResponse[] = []
  for (let offset = 0; ; offset += 200) {
    const page = await apiAuthenticatedGet<Page<SessionResponse>>(
      `${session(id)}/responses?limit=200&offset=${offset}`,
    )
    all.push(...page.items)
    if (all.length >= page.total || page.items.length === 0) return all
  }
}

export interface StudentSummary {
  session_id: string
  student_id: string
  questions_attempted: number
  questions_missed: number
  comprehension_by_topic: Record<string, string>
  /** Next steps, from comprehension and missed questions only, never engagement. */
  action_items?: { kind: 'revisit_topic' | 'review_missed'; text: string; topic: string | null }[]
}

/** A student's own summary, or null while the route is not built yet (501). */
export async function getStudentSummary(sessionId: string, studentId: string): Promise<StudentSummary | null> {
  try {
    return await apiAuthenticatedGet<StudentSummary>(
      `${session(sessionId)}/summary/${encodeURIComponent(studentId)}`,
    )
  } catch (error) {
    if (error instanceof ApiError && error.status === 501) return null
    throw error
  }
}
