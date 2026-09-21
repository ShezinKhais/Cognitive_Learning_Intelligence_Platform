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

export interface CreateSessionPayload {
  course_code: string
  title: string
  starts_at?: string | null
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

async function authenticatedRequest<T>(
  path: string,
  options: RequestInit,
): Promise<T> {
  const token = getAccessToken()

  if (!token) {
    throw new ApiError(
      401,
      'UNAUTHENTICATED',
      'Login is required.',
    )
  }

  const headers =
    new Headers(options.headers)

  headers.set(
    'Authorization',
    `Bearer ${token}`,
  )

  if (
    options.body &&
    !headers.has('Content-Type')
  ) {
    headers.set(
      'Content-Type',
      'application/json',
    )
  }

  const response = await fetch(
    apiUrl(path),
    {
      ...options,
      headers,
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

  return response.json() as Promise<T>
}

export function createSession(
  payload: CreateSessionPayload,
): Promise<SessionActionResponse> {
  return authenticatedRequest<SessionActionResponse>(
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
  return authenticatedRequest<SessionActionResponse>(
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
