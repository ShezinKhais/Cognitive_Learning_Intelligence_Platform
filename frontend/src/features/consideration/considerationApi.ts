import { apiAuthenticatedRequest } from '../../api'

export type ConsiderationNeed = 'camera' | 'gaze' | 'pace' | 'prompts'
export type ConsiderationStatus = 'pending' | 'approved' | 'rejected' | 'withdrawn'

export interface ConsiderationRequest {
  id: string
  needs: ConsiderationNeed[]
  /** Last day it applies (YYYY-MM-DD), or null for the term. */
  until: string | null
  note: string | null
  status: ConsiderationStatus
  created_at: string
  reviewed_at: string | null
  decision_note: string | null
}

export interface AdminConsiderationRequest extends ConsiderationRequest {
  student_name: string
  student_email: string
  course_code: string
}

export interface Page<T> {
  items: T[]
  total: number
  limit: number
  offset: number
}

/** What each need is, and what C.L.I.P does about it. */
export const NEEDS: { key: ConsiderationNeed; label: string; effect: string }[] = [
  { key: 'camera', label: 'I cannot use a camera in class', effect: 'Attention will not read your camera at all.' },
  { key: 'gaze', label: 'Eye-tracking does not work for me', effect: 'Where you look is never counted.' },
  { key: 'pace', label: 'I need more time to answer', effect: 'How fast you answer is never counted.' },
  { key: 'prompts', label: 'Check-in prompts disrupt me', effect: 'You will not get private check-in prompts.' },
]

export const NEED_LABEL = Object.fromEntries(NEEDS.map((need) => [need.key, need.label])) as Record<
  ConsiderationNeed,
  string
>

const MINE = '/me/consideration'
const ADMIN = '/admin/consideration-requests'
const json = (body: unknown): RequestInit => ({
  method: 'POST',
  headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify(body),
})

export function getMyRequest(): Promise<{ current: ConsiderationRequest | null }> {
  return apiAuthenticatedRequest(MINE)
}

export function sendRequest(body: { needs: ConsiderationNeed[]; until: string | null; note: string | null }): Promise<ConsiderationRequest> {
  return apiAuthenticatedRequest(MINE, json(body))
}

export function withdrawRequest(): Promise<ConsiderationRequest> {
  return apiAuthenticatedRequest(`${MINE}/withdraw`, { method: 'POST' })
}

export function listRequests(show: 'pending' | 'all'): Promise<Page<AdminConsiderationRequest>> {
  return apiAuthenticatedRequest(`${ADMIN}?show=${show}&limit=200&offset=0`)
}

export function decideRequest(id: string, approve: boolean, note: string): Promise<ConsiderationRequest> {
  return apiAuthenticatedRequest(
    `${ADMIN}/${encodeURIComponent(id)}/${approve ? 'approve' : 'reject'}`,
    json({ note: note.trim() || null }),
  )
}

/** "Until 14 Nov" or "For the rest of term". */
export function untilLabel(until: string | null): string {
  if (!until) return 'For the rest of term'
  const day = new Date(`${until}T00:00:00`)
  return `Until ${day.toLocaleDateString('en-AU', { day: 'numeric', month: 'short', year: 'numeric' })}`
}
