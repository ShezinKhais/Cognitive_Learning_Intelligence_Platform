/** Lecturers asking for new courses, and admins deciding. */

export type CourseRequestStatus = 'pending' | 'approved' | 'declined'

export interface CourseRequest {
  id: string
  code: string
  name: string
  reason: string | null
  status: CourseRequestStatus
  requested_by: string
  requester_name: string | null
  decision_note: string | null
  created_at: string
  decided_at: string | null
}

export const STATUS_LABEL: Record<CourseRequestStatus, string> = {
  pending: 'Waiting for an admin',
  approved: 'Approved',
  declined: 'Declined',
}

export const STATUS_TONE: Record<CourseRequestStatus, 'mixed' | 'good' | 'poor'> = {
  pending: 'mixed',
  approved: 'good',
  declined: 'poor',
}

/** The same rule the server applies to a course code. */
export const CODE_PATTERN = /^[A-Za-z0-9_-]{2,20}$/

export function waiting(requests: readonly CourseRequest[]): CourseRequest[] {
  return requests.filter((request) => request.status === 'pending')
}

/** A lecturer's requests an admin has decided within the last week. */
export function decidedRecently(
  requests: readonly CourseRequest[],
  now: number = Date.now(),
): CourseRequest[] {
  const week = 7 * 24 * 60 * 60 * 1000
  return requests.filter(
    (request) => request.status !== 'pending' && !!request.decided_at && now - Date.parse(request.decided_at) < week,
  )
}
