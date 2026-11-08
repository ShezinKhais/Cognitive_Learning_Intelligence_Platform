import { apiAuthenticatedGet, apiAuthenticatedRequest } from '../../api'
import type { Course } from '../governance/accountsApi'
import type { CourseRequest, CourseRequestStatus } from './courseRequests'

const send = (method: string, body?: unknown): RequestInit => ({
  method,
  headers: { 'Content-Type': 'application/json' },
  body: body === undefined ? undefined : JSON.stringify(body),
})

/** A lecturer's own requests, or every request for an admin, newest first. */
export function listCourseRequests(status?: CourseRequestStatus): Promise<CourseRequest[]> {
  const query = status ? `?status=${encodeURIComponent(status)}` : ''
  return apiAuthenticatedGet(`/courses/requests${query}`)
}

export function requestCourse(request: { code: string; name: string; reason?: string }): Promise<CourseRequest> {
  return apiAuthenticatedRequest('/courses/requests', send('POST', request))
}

export function approveCourseRequest(id: string, name?: string): Promise<CourseRequest> {
  return apiAuthenticatedRequest(
    `/admin/course-requests/${encodeURIComponent(id)}/approve`,
    send('POST', name ? { name } : {}),
  )
}

export function declineCourseRequest(id: string, note?: string): Promise<CourseRequest> {
  return apiAuthenticatedRequest(
    `/admin/course-requests/${encodeURIComponent(id)}/decline`,
    send('POST', note ? { note } : {}),
  )
}

export function renameCourse(code: string, name: string): Promise<Course> {
  return apiAuthenticatedRequest(`/admin/courses/${encodeURIComponent(code)}`, send('PATCH', { name }))
}
