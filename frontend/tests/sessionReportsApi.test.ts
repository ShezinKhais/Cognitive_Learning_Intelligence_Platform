
import assert from 'node:assert/strict'
import { registerHooks } from 'node:module'
import test, { beforeEach } from 'node:test'

// The production frontend uses Vite, which resolves extensionless TS imports.
// Node's built-in test runner needs this resolver for the real API module.
registerHooks({
  resolve(specifier, context, nextResolve) {
    if (
      specifier.startsWith('.') &&
      !/\.[cm]?[jt]sx?$/.test(specifier)
    ) {
      try {
        return nextResolve(specifier, context)
      } catch (error) {
        if (
          error instanceof Error &&
          'code' in error &&
          error.code === 'ERR_MODULE_NOT_FOUND'
        ) {
          return nextResolve(`${specifier}.ts`, context)
        }
        throw error
      }
    }
    return nextResolve(specifier, context)
  },
})

const store = new Map<string, string>()

Object.assign(globalThis, {
  window: {
    localStorage: {
      getItem: (key: string) => store.get(key) ?? null,
      setItem: (key: string, value: string) => {
        store.set(key, value)
      },
      removeItem: (key: string) => {
        store.delete(key)
      },
    },
  },
})

const {
  requestSessionReport,
  getSessionReport,
  downloadSessionReportPdf,
} = await import('../src/features/reports/sessionReportsApi.ts')

const { ApiError, saveAccessToken } =
  await import('../src/api.ts')

const SESSION_ID = '00000000-0000-4000-8000-000000000001'
const REPORT_ID = '00000000-0000-4000-8000-000000000002'

type FetchCall = {
  url: string
  options: RequestInit
}

let calls: FetchCall[] = []

function mockFetch(
  handler: (url: string, options: RequestInit) => Response | Promise<Response>,
): void {
  globalThis.fetch = (async (
    input: RequestInfo | URL,
    init?: RequestInit,
  ) => {
    const url = String(input)
    const options = init ?? {}
    calls.push({ url, options })
    return handler(url, options)
  }) as typeof fetch
}

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  })
}

function job(status: 'queued' | 'running' | 'ready' | 'failed') {
  return {
    report_id: REPORT_ID,
    session_id: SESSION_ID,
    status,
    requested_at: '2026-10-16T10:00:00Z',
    finished_at: null,
    error: null,
    message: null,
    report: null,
  }
}

function authorization(call: FetchCall): string | null {
  return new Headers(call.options.headers).get('Authorization')
}

beforeEach(() => {
  store.clear()
  calls = []
})

test('requesting a report sends an authenticated POST to the session route', async () => {
  saveAccessToken('lecturer-token')
  mockFetch(() => jsonResponse(job('queued'), 202))

  const result = await requestSessionReport(SESSION_ID)

  assert.equal(result.status, 'queued')
  assert.equal(calls.length, 1)
  assert.equal(
    calls[0].url,
    `/api/v1/sessions/${SESSION_ID}/reports`,
  )
  assert.equal(calls[0].options.method, 'POST')
  assert.equal(authorization(calls[0]), 'Bearer lecturer-token')
})

test('report generation is blocked locally without an access token', async () => {
  mockFetch(() => {
    throw new Error('Fetch must not be called')
  })

  await assert.rejects(
    requestSessionReport(SESSION_ID),
    (error: unknown) =>
      error instanceof ApiError &&
      error.status === 401 &&
      error.code === 'UNAUTHENTICATED',
  )

  assert.equal(calls.length, 0)
})

test('report status retrieval uses the protected report endpoint', async () => {
  saveAccessToken('lecturer-token')
  mockFetch(() => jsonResponse(job('running')))

  const result = await getSessionReport(REPORT_ID)

  assert.equal(result.status, 'running')
  assert.equal(calls.length, 1)
  assert.equal(calls[0].url, `/api/v1/reports/${REPORT_ID}`)
  assert.equal(calls[0].options.method ?? 'GET', 'GET')
  assert.equal(authorization(calls[0]), 'Bearer lecturer-token')
})

test('the report API preserves backend authorization errors', async () => {
  saveAccessToken('lecturer-token')
  mockFetch(() =>
    jsonResponse(
      { error: { code: 'NOT_FOUND', message: 'Report not found.' } },
      404,
    ),
  )

  await assert.rejects(
    getSessionReport(REPORT_ID),
    (error: unknown) =>
      error instanceof ApiError &&
      error.status === 404 &&
      error.code === 'NOT_FOUND' &&
      error.message === 'Report not found.',
  )
})

test('the report API clears an invalid token on HTTP 401', async () => {
  saveAccessToken('expired-token')
  mockFetch(() =>
    jsonResponse(
      { error: { code: 'UNAUTHENTICATED', message: 'Session expired.' } },
      401,
    ),
  )

  await assert.rejects(
    getSessionReport(REPORT_ID),
    (error: unknown) =>
      error instanceof ApiError && error.status === 401,
  )

  assert.equal(store.get('clip_access_token'), undefined)
})

test('the report API handles non-JSON server errors safely', async () => {
  saveAccessToken('lecturer-token')
  mockFetch(() => new Response('Unavailable', { status: 503 }))

  await assert.rejects(
    getSessionReport(REPORT_ID),
    (error: unknown) =>
      error instanceof ApiError &&
      error.status === 503 &&
      error.code === 'HTTP_ERROR' &&
      error.message === 'HTTP 503',
  )
})

test('the PDF endpoint returns binary data and its attachment filename', async () => {
  saveAccessToken('lecturer-token')
  const pdfBytes = Uint8Array.from([37, 80, 68, 70, 45, 49, 46, 55])

  mockFetch(() =>
    new Response(pdfBytes, {
      status: 200,
      headers: {
        'Content-Type': 'application/pdf',
        'Content-Disposition':
          'attachment; filename="lecture-session.pdf"',
        'Cache-Control': 'no-store',
      },
    }),
  )

  const result = await downloadSessionReportPdf(REPORT_ID)

  assert.equal(result.filename, 'lecture-session.pdf')
  assert.deepEqual(
    new Uint8Array(await result.blob.arrayBuffer()),
    pdfBytes,
  )
  assert.equal(calls[0].url, `/api/v1/reports/${REPORT_ID}/pdf`)
  assert.equal(authorization(calls[0]), 'Bearer lecturer-token')
})

test('PDF downloads use a safe fallback filename', async () => {
  saveAccessToken('lecturer-token')
  mockFetch(() =>
    new Response('%PDF-test', {
      status: 200,
      headers: { 'Content-Type': 'application/pdf' },
    }),
  )

  const result = await downloadSessionReportPdf(REPORT_ID)
  assert.equal(result.filename, 'clip-session-report.pdf')
})

test('PDF downloads are blocked locally without authentication', async () => {
  mockFetch(() => {
    throw new Error('Fetch must not be called')
  })

  await assert.rejects(
    downloadSessionReportPdf(REPORT_ID),
    (error: unknown) =>
      error instanceof ApiError &&
      error.status === 401 &&
      error.code === 'UNAUTHENTICATED',
  )

  assert.equal(calls.length, 0)
})

test('PDF requests preserve backend 403 authorization failures', async () => {
  saveAccessToken('student-token')
  mockFetch(() =>
    jsonResponse(
      { error: { code: 'FORBIDDEN', message: 'Access denied.' } },
      403,
    ),
  )

  await assert.rejects(
    downloadSessionReportPdf(REPORT_ID),
    (error: unknown) =>
      error instanceof ApiError &&
      error.status === 403 &&
      error.code === 'FORBIDDEN',
  )
})

test('PDF requests preserve the backend not-ready response', async () => {
  saveAccessToken('lecturer-token')
  mockFetch(() =>
    jsonResponse(
      { error: { code: 'REPORT_NOT_READY', message: 'Not ready.' } },
      409,
    ),
  )

  await assert.rejects(
    downloadSessionReportPdf(REPORT_ID),
    (error: unknown) =>
      error instanceof ApiError &&
      error.status === 409 &&
      error.code === 'REPORT_NOT_READY',
  )
})

test('PDF downloads clear expired credentials on HTTP 401', async () => {
  saveAccessToken('expired-token')
  mockFetch(() =>
    jsonResponse(
      { error: { code: 'UNAUTHENTICATED', message: 'Login required.' } },
      401,
    ),
  )

  await assert.rejects(
    downloadSessionReportPdf(REPORT_ID),
    (error: unknown) =>
      error instanceof ApiError && error.status === 401,
  )

  assert.equal(store.get('clip_access_token'), undefined)
})
