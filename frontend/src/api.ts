/** Shared API and authentication helpers. */

export const API_BASE = '/api/v1'

const ACCESS_TOKEN_KEY = 'clip_access_token'

export type Role = 'student' | 'lecturer' | 'admin'

export type ConsentType =
  | 'terms'
  | 'engagement_monitoring'
  | 'camera'
  | 'microphone'

export interface Health {
  status: string
  env: string
  version: string
  teams_configured: boolean
}

export interface LoginResponse {
  access_token: string
  token_type: 'bearer'
  expires_in: number
  role: Role
}

export interface CurrentUser {
  id: string
  email: string
  full_name: string
  role: Role
  consents: ConsentType[]
}

export interface ConsentResponse {
  consent_type: ConsentType
  granted: boolean
  recorded_at: string
}

export interface TimetableImportResult {
  rows_read: number
  sessions_created: number
  conflicts: string[]
  unmatched_lecturers: string[]
  unmatched_students: string[]
}

export function apiUrl(path: string): string {
  return `${API_BASE}${path.startsWith('/') ? path : `/${path}`}`
}

export function getAccessToken(): string | null {
  return window.localStorage.getItem(ACCESS_TOKEN_KEY)
}

export function saveAccessToken(token: string): void {
  window.localStorage.setItem(ACCESS_TOKEN_KEY, token)
}

export function clearAccessToken(): void {
  window.localStorage.removeItem(ACCESS_TOKEN_KEY)
}

export class ApiError extends Error {
  status: number
  code: string

  constructor(
    status: number,
    code: string,
    message: string,
  ) {
    super(message)

    this.name = 'ApiError'
    this.status = status
    this.code = code
  }
}

async function readErrorEnvelope(
  response: Response,
): Promise<ApiError> {
  let code = 'HTTP_ERROR'
  let message = `HTTP ${response.status}`

  try {
    const body = await response.json()

    code = body?.error?.code ?? code
    message = body?.error?.message ?? message
  } catch {
    // Non-API responses may not contain JSON.
  }

  return new ApiError(response.status, code, message)
}

async function request<T>(
  path: string,
  options: RequestInit = {},
  authenticated = false,
): Promise<T> {
  const headers = new Headers(options.headers)

  if (authenticated) {
    const token = getAccessToken()

    if (!token) {
      throw new ApiError(
        401,
        'UNAUTHENTICATED',
        'Login is required.',
      )
    }

    headers.set('Authorization', `Bearer ${token}`)
  }

  if (
    options.body &&
    !(options.body instanceof FormData) &&
    !headers.has('Content-Type')
  ) {
    headers.set('Content-Type', 'application/json')
  }

  const response = await fetch(apiUrl(path), {
    ...options,
    headers,
  })

  if (!response.ok) {
    const error = await readErrorEnvelope(response)

    if (response.status === 401) {
      clearAccessToken()
    }

    throw error
  }

  return response.json() as Promise<T>
}

export function apiGet<T>(path: string): Promise<T> {
  return request<T>(path)
}

export function login(
  email: string,
  password: string,
): Promise<LoginResponse> {
  return request<LoginResponse>('/auth/login', {
    method: 'POST',
    body: JSON.stringify({
      email,
      password,
    }),
  })
}

export function getCurrentUser(): Promise<CurrentUser> {
  return request<CurrentUser>('/auth/me', {}, true)
}

export function recordConsent(
  consentType: ConsentType,
  granted: boolean,
): Promise<ConsentResponse> {
  return request<ConsentResponse>(
    '/auth/consent',
    {
      method: 'POST',
      body: JSON.stringify({
        consent_type: consentType,
        granted,
      }),
    },
    true,
  )
}

export function apiUploadFile<T = TimetableImportResult>(
  path: string,
  file: File,
): Promise<T> {
  const formData = new FormData()

  formData.append('file', file)

  return request<T>(
    path,
    {
      method: 'POST',
      body: formData,
    },
    true,
  )
}