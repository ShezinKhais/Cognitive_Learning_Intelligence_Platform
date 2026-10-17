/** Shared API and authentication helpers. */

export const API_BASE = '/api/v1'

// A token is swapped for a fresh one this long before it expires, so a class
// that runs past the token's lifetime is not ended by a sign-in. The sign-in
// itself still ends when the backend's cap says so.
const REFRESH_BEFORE_MS = 5 * 60 * 1000
// A refresh that failed for any reason but a refused token (offline, a
// restart) is tried again this often until the token expires. Once it has
// expired the backend will not renew it, so waiting for a 401 is too late.
const REFRESH_RETRY_MS = 30 * 1000

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

// The access token lives in this tab's memory and nowhere else, so a script
// injected into the page finds nothing in storage to carry away. What keeps
// a user signed in across reloads and tabs is the refresh cookie, which is
// httpOnly: the browser sends it to /auth/refresh and no script can read it.
let accessToken: string | null = null
let accessTokenExpiresAt = 0

// Where earlier builds kept the token. Cleared on load, so a token left there
// by one is not lying around for anything to read.
const LEGACY_TOKEN_KEYS = ['clip_access_token', 'clip_access_token_expires_at']
try {
  for (const key of LEGACY_TOKEN_KEYS) window.localStorage?.removeItem(key)
} catch {
  // Storage blocked: nothing was kept there either.
}

export function getAccessToken(): string | null {
  return accessToken
}

export function saveAccessToken(token: string, expiresIn?: number): void {
  forgetCurrentUser()
  accessToken = token
  accessTokenExpiresAt = expiresIn === undefined ? 0 : Date.now() + expiresIn * 1000
  scheduleRefresh()
}

function forgetAccessToken(): void {
  forgetCurrentUser()
  accessToken = null
  accessTokenExpiresAt = 0
  scheduleRefresh()
}

// Other tabs hold their own token in memory. Signing out in one tells the
// rest, so none carries on as the user who just left.
// Only in a page: under Node, as in the tests, an open channel keeps the
// process from exiting.
const authChannel =
  typeof BroadcastChannel === 'undefined' || typeof document === 'undefined'
    ? undefined
    : new BroadcastChannel('clip-auth')
authChannel?.addEventListener('message', (event: MessageEvent) => {
  if (event.data === 'signed-out') forgetAccessToken()
})

/**
 * Sign out: forget the token here and in every other tab, and ask the
 * backend to drop the refresh cookie so a reload does not sign back in.
 */
export function clearAccessToken(): void {
  forgetAccessToken()
  authChannel?.postMessage('signed-out')
  void fetch(apiUrl('/auth/logout'), { method: 'POST', headers: REFRESH_HEADERS }).catch(() => {
    // Offline: the cookie ends with the sign-in anyway.
  })
}

// Refresh and sign-out must carry this. Another site cannot add it without a
// CORS preflight, which the backend refuses, so the cookie alone does nothing.
const REFRESH_HEADERS = { 'X-CLIP-Refresh': '1' }

let refreshTimer: ReturnType<typeof setTimeout> | undefined

function scheduleRefresh(retry = false): void {
  if (refreshTimer !== undefined) clearTimeout(refreshTimer)
  refreshTimer = undefined
  if (!accessToken || !accessTokenExpiresAt) return
  const left = accessTokenExpiresAt - Date.now()
  if (retry && left <= 0) return
  const wait = retry
    ? Math.min(REFRESH_RETRY_MS, left)
    : Math.max(0, left - REFRESH_BEFORE_MS)
  refreshTimer = setTimeout(() => void refreshAccessToken(), wait)
}

type Renewal = { token: string } | 'refused' | 'unreachable'

let refreshing: Promise<Renewal> | null = null

function renew(): Promise<Renewal> {
  refreshing ??= renewToken().finally(() => {
    refreshing = null
  })
  return refreshing
}

/**
 * Get a fresh token with the refresh cookie, and return it, or null when the
 * user has to sign in again or the backend could not be reached. Every caller
 * waiting at once shares one request, so the live page's polls do not each
 * refresh.
 */
export async function refreshAccessToken(): Promise<string | null> {
  const renewal = await renew()
  return typeof renewal === 'object' ? renewal.token : null
}

async function renewToken(): Promise<Renewal> {
  let response: Response
  try {
    response = await fetch(apiUrl('/auth/refresh'), {
      method: 'POST',
      headers: REFRESH_HEADERS,
    })
  } catch {
    // Offline for a moment: the token is kept and the refresh tried again.
    scheduleRefresh(true)
    return 'unreachable'
  }
  if (response.status === 401) {
    forgetAccessToken()
    return 'refused'
  }
  if (!response.ok) {
    scheduleRefresh(true)
    return 'unreachable'
  }
  const renewed = (await response.json()) as LoginResponse
  saveAccessToken(renewed.access_token, renewed.expires_in)
  return { token: renewed.access_token }
}

/**
 * The token for this tab, fetched with the refresh cookie when the tab has
 * none yet, as after a reload or in a new tab. Null means nobody is signed
 * in. Throws when the backend cannot be reached, so the page can say so
 * rather than send someone who is signed in to the sign-in page.
 */
export async function restoreSession(): Promise<string | null> {
  if (accessToken) return accessToken
  const renewal = await renew()
  if (renewal === 'unreachable') {
    throw new ApiError(503, 'UNREACHABLE', 'Could not reach C.L.I.P. Check your connection and reload.')
  }
  return renewal === 'refused' ? null : renewal.token
}

/**
 * fetch with the caller's token. A 401 is answered by one refresh and one
 * retry, since the token may have run out while the tab slept, before the
 * user is sent to sign in. The retry sends the body again, which holds for
 * every caller today (JSON and FormData); a stream could not be re-sent.
 */
export async function authenticatedFetch(
  path: string,
  options: RequestInit = {},
): Promise<Response> {
  const token = accessToken ?? (await restoreSession())
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
  const latest = accessToken
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

    // A wrong password at sign-in is a 401 too, and must not sign out the
    // user's other tabs.
    if (response.status === 401 && authenticated) {
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
