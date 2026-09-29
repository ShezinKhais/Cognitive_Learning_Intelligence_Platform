import {
  apiAuthenticatedGet,
  apiAuthenticatedRequest,
} from '../../api'

export type SessionLifecycleAction =
  | 'start'
  | 'pause'
  | 'resume'
  | 'end'

export interface SessionActionResponse {
  id: string
  course_code: string
  title: string
  lecturer_id: string
  status:
    | 'prepared'
    | 'active'
    | 'ending'
    | 'ended'
    | 'cancelled'
  starts_at: string | null
  ended_at: string | null
  teams_meeting_id: string | null
  participant_count: number
  questions_delivered: number
  paused: boolean
}

export interface CreateSessionPayload {
  course_code: string
  title: string
  starts_at?: string | null
}

export type ReadinessIssueCode =
  | 'no_material'
  | 'material_processing'
  | 'no_approved_questions'
  | 'material_failed'

export interface ReadinessIssue {
  code: ReadinessIssueCode
  message: string
  material_id: string | null
}

export interface SessionReadiness {
  session_id: string
  ready: boolean
  blockers: ReadinessIssue[]
  warnings: ReadinessIssue[]
  materials_total: number
  materials_processing: number
  materials_failed: number
  deliverable_questions: number
  checked_at: string
}

export function createSession(
  payload: CreateSessionPayload,
): Promise<SessionActionResponse> {
  return apiAuthenticatedRequest<SessionActionResponse>(
    '/sessions',
    {
      method: 'POST',
      body: JSON.stringify(payload),
    },
  )
}

export function getSessionReadiness(
  sessionId: string,
): Promise<SessionReadiness> {
  return apiAuthenticatedGet<SessionReadiness>(
    `/sessions/${encodeURIComponent(
      sessionId,
    )}/readiness`,
  )
}

export function runSessionAction(
  sessionId: string,
  action: SessionLifecycleAction,
): Promise<SessionActionResponse> {
  return apiAuthenticatedRequest<SessionActionResponse>(
    `/sessions/${encodeURIComponent(
      sessionId,
    )}/${action}`,
    {
      method: 'POST',
    },
  )
}

export function startSession(
  sessionId: string,
): Promise<SessionActionResponse> {
  return runSessionAction(
    sessionId,
    'start',
  )
}

export function pauseSession(
  sessionId: string,
): Promise<SessionActionResponse> {
  return runSessionAction(
    sessionId,
    'pause',
  )
}

export function resumeSession(
  sessionId: string,
): Promise<SessionActionResponse> {
  return runSessionAction(
    sessionId,
    'resume',
  )
}

export function endSession(
  sessionId: string,
): Promise<SessionActionResponse> {
  return runSessionAction(
    sessionId,
    'end',
  )
}