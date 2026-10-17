import { ApiError, apiAuthenticatedGet, apiAuthenticatedRequest, authenticatedFetch, type Page } from '../../api'
import type { TopicDifficulty } from '../intelligence/topicRecovery'

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

export type ReportStatus = 'queued' | 'running' | 'ready' | 'failed'

export interface ReportAlert {
  alert_id: string
  kind: string
  message: string
  topic: string | null
  raised_at: string
  status: string
}

export interface SessionReport {
  session_id: string
  course_code: string
  title: string
  status: SessionStatus
  starts_at: string | null
  ended_at: string | null
  generated_at: string
  participation: {
    students: number
    questions_delivered: number
    answers: number
    missed_answers: number
    attention_prompts: number
  }
  topics: TopicDifficulty[]
  alerts: ReportAlert[]
}

export interface ReportJob {
  report_id: string
  session_id: string
  status: ReportStatus
  requested_at: string
  finished_at: string | null
  message: string | null
  error: string | null
  report: SessionReport | null
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

export function requestReport(id: string): Promise<ReportJob> {
  return apiAuthenticatedRequest<ReportJob>(`${session(id)}/reports`, { method: 'POST' })
}

export function getReport(reportId: string): Promise<ReportJob> {
  return apiAuthenticatedGet<ReportJob>(`/reports/${encodeURIComponent(reportId)}`)
}

/** The report PDF, fetched with the caller's token and opened from memory:
 * a plain link would carry no Authorization header. */
export async function openReportPdf(reportId: string): Promise<void> {
  const response = await authenticatedFetch(`/reports/${encodeURIComponent(reportId)}/pdf`)
  if (!response.ok) {
    throw new ApiError(response.status, 'PDF_UNAVAILABLE', 'The PDF could not be opened.')
  }
  const url = URL.createObjectURL(await response.blob())
  window.open(url, '_blank', 'noopener')
  // Long enough for the new tab to read it.
  setTimeout(() => URL.revokeObjectURL(url), 60_000)
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
