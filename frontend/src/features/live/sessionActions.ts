import { apiAuthenticatedRequest } from '../../api'

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
