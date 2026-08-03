/**
 * Base path for the API.
 *
 * Kept in one place so a version bump is a single edit rather than a search for
 * hardcoded URLs. TypeScript cannot check a wrong URL string, so a typo here is
 * only caught at runtime.
 */
export const API_BASE = '/api/v1'

export function apiUrl(path: string): string {
  return `${API_BASE}${path.startsWith('/') ? path : `/${path}`}`
}

export interface Health {
  status: string
  env: string
  version: string
  teams_configured: boolean
}

export class ApiError extends Error {
  // Assigned explicitly rather than as constructor parameter properties, which
  // this tsconfig disallows under erasableSyntaxOnly.
  status: number
  code: string

  constructor(status: number, code: string, message: string) {
    super(message)
    this.status = status
    this.code = code
  }
}

/**
 * Fetch JSON, translating the API's error envelope into a typed error.
 *
 * Every failure returns {error: {code, message, detail}, request_id}, so
 * callers get the stable code rather than having to parse a message.
 */
async function readErrorEnvelope(response: Response): Promise<ApiError> {
  let code = 'HTTP_ERROR'
  let message = `HTTP ${response.status}`
  try {
    const body = await response.json()
    code = body?.error?.code ?? code
    message = body?.error?.message ?? message
  } catch {
    // Not every failure has a JSON body: a proxy or a dead server will not.
  }
  return new ApiError(response.status, code, message)
}

export async function apiGet<T>(path: string): Promise<T> {
  const response = await fetch(apiUrl(path))

  if (!response.ok) {
    throw await readErrorEnvelope(response)
  }

  return response.json() as Promise<T>
}

/**
 * Upload result for /admin/timetable and /admin/roster. Mirrors the backend's
 * frozen TimetableImportResult schema exactly, since the two routes share it.
 */
export interface TimetableImportResult {
  rows_read: number
  sessions_created: number
  conflicts: string[]
  unmatched_lecturers: string[]
  unmatched_students: string[]
}

/**
 * POST a CSV/XLSX file to an /admin route as multipart form data.
 * Shared by the timetable and roster uploads, since both take one `file`
 * field and return the same TimetableImportResult shape.
 */
export async function apiUploadFile(
  path: string,
  file: File,
): Promise<TimetableImportResult> {
  const formData = new FormData()
  formData.append('file', file)

  const response = await fetch(apiUrl(path), { method: 'POST', body: formData })

  if (!response.ok) {
    throw await readErrorEnvelope(response)
  }

  return response.json() as Promise<TimetableImportResult>
}
