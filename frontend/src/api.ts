/** Shared API and authentication helpers. */

export const API_BASE = '/api/v1'

const ACCESS_TOKEN_KEY = 'clip_access_token'
const ACCESS_TOKEN_EXPIRES_KEY = 'clip_access_token_expires_at'

// A token is swapped for a fresh one this long before it expires, so a class
// that runs past the token's lifetime is not ended by a sign-in. The sign-in
// itself still ends when the backend's cap says so.
const REFRESH_BEFORE_MS = 5 * 60 * 1000

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

export function saveAccessToken(token: string, expiresIn?: number): void {
  forgetCurrentUser()
  window.localStorage.setItem(ACCESS_TOKEN_KEY, token)
  if (expiresIn === undefined) {
    window.localStorage.removeItem(ACCESS_TOKEN_EXPIRES_KEY)
  } else {
    window.localStorage.setItem(ACCESS_TOKEN_EXPIRES_KEY, String(Date.now() + expiresIn * 1000))
  }
  scheduleRefresh()
}

export function clearAccessToken(): void {
  forgetCurrentUser()
  window.localStorage.removeItem(ACCESS_TOKEN_KEY)
  window.localStorage.removeItem(ACCESS_TOKEN_EXPIRES_KEY)
  scheduleRefresh()
}

let refreshTimer: ReturnType<typeof setTimeout> | undefined

function scheduleRefresh(): void {
  if (refreshTimer !== undefined) clearTimeout(refreshTimer)
  refreshTimer = undefined
  const expiresAt = Number(window.localStorage.getItem(ACCESS_TOKEN_EXPIRES_KEY))
  if (!getAccessToken() || !expiresAt) return
  const wait = Math.max(0, expiresAt - REFRESH_BEFORE_MS - Date.now())
  refreshTimer = setTimeout(() => void refreshAccessToken(), wait)
}

let refreshing: Promise<string | null> | null = null

/**
 * Swap the current token for a fresh one, and return it, or null when the
 * user has to sign in again. Every caller waiting at once shares one request,
 * so the live page's polls do not each refresh, and tabs take turns, so two
 * never send the same token.
 */
export function refreshAccessToken(): Promise<string | null> {
  refreshing ??= renewToken().finally(() => {
    refreshing = null
  })
  return refreshing
}

async function renewToken(): Promise<string | null> {
  const before = getAccessToken()
  const exchange = async (): Promise<string | null> => {
    const current = getAccessToken()
    // Another tab refreshed while this one waited its turn.
    if (!current || current !== before) return current
    let response: Response
    try {
      response = await fetch(apiUrl('/auth/refresh'), {
        method: 'POST',
        headers: { Authorization: `Bearer ${current}` },
      })
    } catch {
      // Offline for a moment: the token is kept, and a later 401 tries again.
      return null
    }
    if (!response.ok) {
      if (response.status === 401) clearAccessToken()
      return null
    }
    const renewed = (await response.json()) as LoginResponse
    saveAccessToken(renewed.access_token, renewed.expires_in)
    return renewed.access_token
  }
  const locks = typeof navigator === 'undefined' ? undefined : navigator.locks
  return locks ? locks.request('clip-token-refresh', exchange) : exchange()
}

// Another tab's refresh moves this tab's timer too.
window.addEventListener?.('storage', (event) => {
  if (event.key === ACCESS_TOKEN_KEY || event.key === ACCESS_TOKEN_EXPIRES_KEY) scheduleRefresh()
})
scheduleRefresh()

/**
 * fetch with the caller's token. A 401 is answered by one refresh and one
 * retry, since the token may have run out while the tab slept, before the
 * user is sent to sign in.
 */
export async function authenticatedFetch(
  path: string,
  options: RequestInit = {},
): Promise<Response> {
  const token = getAccessToken()
  if (!token) {
    throw new ApiError(401, 'UNAUTHENTICATED', 'Login is required.')
  }
  const send = (bearer: string) => {
    const headers = new Headers(options.headers)
    headers.set('Authorization', `Bearer ${bearer}`)
    return fetch(apiUrl(path), { ...options, headers })
  }
  const response = await send(token)
  if (response.status !== 401) return response
  const latest = getAccessToken()
  const renewed = latest && latest !== token ? latest : await refreshAccessToken()
  return renewed ? send(renewed) : response
}

// Landing on / checks who the user is, then the page it redirects to checks
// again. For a moment the first answer is reused, so that is one request
// rather than two. It is dropped whenever the token or the consents change.
const CURRENT_USER_REUSE_MS = 2000
let currentUserCache: { token: string; at: number; user: Promise<CurrentUser> } | null = null

function forgetCurrentUser(): void {
  currentUserCache = null
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

  if (
    options.body &&
    !(options.body instanceof FormData) &&
    !headers.has('Content-Type')
  ) {
    headers.set('Content-Type', 'application/json')
  }

  const response = authenticated
    ? await authenticatedFetch(path, { ...options, headers })
    : await fetch(apiUrl(path), { ...options, headers })

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

export function apiAuthenticatedGet<T>(path: string): Promise<T> {
  return request<T>(path, {}, true)
}

export function apiAuthenticatedRequest<T>(
  path: string,
  options: RequestInit = {},
): Promise<T> {
  return request<T>(
    path,
    options,
    true,
  )
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
  const token = getAccessToken()
  const now = Date.now()
  if (
    token &&
    currentUserCache?.token === token &&
    now - currentUserCache.at < CURRENT_USER_REUSE_MS
  ) {
    return currentUserCache.user
  }

  const user = request<CurrentUser>('/auth/me', {}, true)
  if (token) {
    const entry = { token, at: now, user }
    currentUserCache = entry
    // A failed check is never reused.
    user.catch(() => {
      if (currentUserCache === entry) forgetCurrentUser()
    })
  }
  return user
}

export function recordConsent(
  consentType: ConsentType,
  granted: boolean,
): Promise<ConsentResponse> {
  // The user's consents are changing, so an answer from before, or one taken
  // while this request was in flight, would be stale.
  forgetCurrentUser()
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
  ).finally(forgetCurrentUser)
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

export type QuestionType = 'mcq' | 'free_text'

export type QuestionStatus = 'draft' | 'approved' | 'rejected' | 'staged' | 'delivered'

// What a lecturer may set. Delivered is set by the session that sends the
// question, never by review, and the API refuses it here.
export type ReviewDecision = Exclude<QuestionStatus, 'delivered'>

export type Difficulty = 'easy' | 'medium' | 'hard'

export interface Question {
  id: string
  material_id: string
  type: QuestionType
  status: QuestionStatus
  difficulty: Difficulty
  prompt: string
  options: string[] | null
  correct_option: number | null
  topic: string | null
  source_slide: number | null
  source_excerpt: string | null
}

export interface Page<T> {
  items: T[]
  total: number
  limit: number
  offset: number
}

export function listQuestions(
  materialId: string,
  limit = 50,
  offset = 0,
): Promise<Page<Question>> {
  return request<Page<Question>>(
    `/materials/${materialId}/questions?limit=${limit}&offset=${offset}`,
    {},
    true,
  )
}

export interface ReviewQuestionPayload {
  status: ReviewDecision
  prompt?: string
  options?: string[]
  correct_option?: number
  difficulty?: Difficulty
}

export function reviewQuestion(
  materialId: string,
  questionId: string,
  payload: ReviewQuestionPayload,
): Promise<Question> {
  return request<Question>(
    `/materials/${materialId}/questions/${questionId}`,
    {
      method: 'PATCH',
      body: JSON.stringify(payload),
    },
    true,
  )
}

// Replaces a draft with a newly generated one from the same page. The old
// draft comes back rejected on the next list; the new one is returned here.
export function regenerateQuestion(materialId: string, questionId: string): Promise<Question> {
  return request<Question>(
    `/materials/${materialId}/questions/${questionId}:regenerate`,
    { method: 'POST' },
    true,
  )
}

export interface QuestionBulkReviewResult {
  updated: Question[]
  skipped_ids: string[]
}

export function bulkReviewQuestions(
  materialId: string,
  questionIds: string[],
  status: ReviewDecision,
): Promise<QuestionBulkReviewResult> {
  return request<QuestionBulkReviewResult>(
    `/materials/${materialId}/questions:bulk`,
    {
      method: 'POST',
      body: JSON.stringify({ question_ids: questionIds, status }),
    },
    true,
  )
}
