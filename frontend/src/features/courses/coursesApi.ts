import { apiAuthenticatedGet, apiAuthenticatedRequest } from '../../api'
import type { Course } from '../governance/accountsApi'

export interface RosterPerson {
  id: string
  name: string
  email: string
  /** For a student: this is their home course. */
  home_course: boolean
}

export interface CourseRoster {
  course: Course
  lecturers: RosterPerson[]
  students: RosterPerson[]
}

const send = (method: string, body?: unknown): RequestInit => ({
  method,
  headers: { 'Content-Type': 'application/json' },
  body: body === undefined ? undefined : JSON.stringify(body),
})

const path = (code: string) => `/courses/${encodeURIComponent(code)}`

/** Every course for an admin; the courses they teach for a lecturer. */
export function myCourses(): Promise<Course[]> {
  return apiAuthenticatedGet('/courses/mine')
}

export function getRoster(code: string): Promise<CourseRoster> {
  return apiAuthenticatedGet(`${path(code)}/roster`)
}

export function addStudent(code: string, email: string): Promise<CourseRoster> {
  return apiAuthenticatedRequest(`${path(code)}/students`, send('POST', { email }))
}

export function removeStudent(code: string, userId: string): Promise<CourseRoster> {
  return apiAuthenticatedRequest(`${path(code)}/students/${encodeURIComponent(userId)}`, send('DELETE'))
}

export function setLecturers(code: string, lecturerIds: string[]): Promise<CourseRoster> {
  return apiAuthenticatedRequest(`${path(code)}/lecturers`, send('PUT', { lecturer_ids: lecturerIds }))
}

export type BulkOutcome =
  | 'add'
  | 'create'
  | 'already'
  | 'no_account'
  | 'not_student'
  | 'inactive'
  | 'invalid'
  | 'duplicate'

export interface BulkRosterResult {
  applied: boolean
  lines: { line: number; email: string; name: string | null; outcome: BulkOutcome }[]
  counts: Partial<Record<BulkOutcome, number>>
  roster: CourseRoster | null
}

/** Preview (confirm false) or apply a pasted class list for a course. */
export function bulkAddStudents(
  code: string,
  body: { text: string; confirm: boolean; create_missing: boolean },
): Promise<BulkRosterResult> {
  return apiAuthenticatedRequest(`${path(code)}/students:bulk`, send('POST', body))
}
