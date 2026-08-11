import type { CurrentUser } from '../../api'

/**
 * The authenticated user comes from the shared `/auth/me` contract.
 *
 * The role can be student, lecturer or admin. The student workspace must
 * therefore check the role at runtime instead of assuming every user is a
 * student.
 */
export type StudentUser = CurrentUser

export type SessionStatus =
  | 'prepared'
  | 'active'
  | 'ending'
  | 'ended'
  | 'cancelled'

/**
 * Matches the frozen SessionOut schema in backend/openapi.json.
 *
 * Only id, course_code, title, lecturer_id and status are required by the
 * contract. The remaining properties may be missing from a response.
 */
export interface StudentSession {
  id: string
  course_code: string
  title: string
  lecturer_id: string
  status: SessionStatus
  starts_at?: string | null
  ended_at?: string | null
  teams_meeting_id?: string | null
  participant_count?: number
  questions_delivered?: number
}

/**
 * Matches the paginated response returned by GET /api/v1/sessions.
 */
export interface Page<T> {
  items: T[]
  total: number
  limit: number
  offset: number
}

export type StudentSessionPage = Page<StudentSession>
