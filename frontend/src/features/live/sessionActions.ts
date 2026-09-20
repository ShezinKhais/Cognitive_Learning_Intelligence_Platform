import {
  ApiError,
  apiUrl,
  clearAccessToken,
  getAccessToken,
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

async function errorFromResponse(
  response: Response,
): Promise<ApiError> {
  let code = 'HTTP_ERROR'
  let message = `HTTP ${response.status}`

  try {
    const body = await response.json()

    code =
      body?.error?.code ??
      code

    message =
      body?.error?.message ??
      message
  } catch {
    // Keep the HTTP fallback when the response
    // does not contain the API error envelope.
  }

  return new ApiError(
    response.status,
    code,
    message,
  )
}

export async function runSessionAction(
  sessionId: string,
  action: SessionLifecycleAction,
): Promise<SessionActionResponse> {
  const token = getAccessToken()

  if (!token) {
    throw new ApiError(
      401,
      'UNAUTHENTICATED',
      'Login is required.',
    )
  }

  const response = await fetch(
    apiUrl(
      `/sessions/${encodeURIComponent(
        sessionId,
      )}/${action}`,
    ),
    {
      method: 'POST',
      headers: {
        Authorization: `Bearer ${token}`,
      },
    },
  )

  if (!response.ok) {
    const error =
      await errorFromResponse(response)

    if (response.status === 401) {
      clearAccessToken()
    }

    throw error
  }

  return response.json() as Promise<SessionActionResponse>
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