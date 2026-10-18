
import assert from 'node:assert/strict'
import { registerHooks } from 'node:module'
import test, { beforeEach } from 'node:test'

registerHooks({
  resolve(specifier, context, nextResolve) {
    if (specifier.startsWith('.') && !/\.[cm]?[jt]sx?$/.test(specifier)) {
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
      setItem: (key: string, value: string) => void store.set(key, value),
      removeItem: (key: string) => void store.delete(key),
    },
  },
})

const { startReportPolling, MAX_REPORT_POLL_ATTEMPTS } =
  await import('../src/features/reports/reportPolling.ts')
const { getSessionReport } =
  await import('../src/features/reports/sessionReportsApi.ts')
const { saveAccessToken } =
  await import('../src/api.ts')

const SESSION = '00000000-0000-4000-8000-000000000001'
const REPORT = '00000000-0000-4000-8000-000000000002'

type ResponseBody = {
  status: string
  session_id: string
  report_id: string
}

const body = (
  status: string,
  session_id = SESSION,
): ResponseBody => ({
  status,
  session_id,
  report_id: REPORT,
})

const response = (value: unknown, status = 200) =>
  new Response(JSON.stringify(value), {
    status,
    headers: { 'Content-Type': 'application/json' },
  })

type Scenario = {
  runNext: () => Promise<number>
  pending: () => number
  calls: () => number
  delays: number[]
  jobs: string[]
  errors: Array<string | null>
  stopped: () => number
  missing: () => number
  unauthorized: () => number
  failures: () => number
  cancel: () => void
  setSession: (id: string) => void
}

function scenario(
  replies: Array<Response | Error | (() => Promise<Response>)>,
): Scenario {
  let currentSession = SESSION
  let failures = 0
  let stopped = 0
  let missing = 0
  let unauthorized = 0
  let calls = 0
  let timerId = 0

  const pendingTimers = new Map<number, () => void>()
  const delays: number[] = []
  const jobs: string[] = []
  const errors: Array<string | null> = []

  globalThis.fetch = (async (
    input: RequestInfo | URL,
    options?: RequestInit,
  ) => {
    const url = String(input)

    // On the merged PR, authentication automatically attempts one token
    // refresh after HTTP 401. Reject that refresh to simulate an expired
    // session, allowing the report page's authentication handler to run.
    // Older branches have no refresh request, so both implementations
    // can be tested without changing production code.
    if (url === '/api/v1/auth/refresh') {
      assert.equal(options?.method, 'POST')
      return response(
        {
          error: {
            code: 'UNAUTHENTICATED',
            message: 'Session expired.',
          },
        },
        401,
      )
    }

    assert.equal(url, `/api/v1/reports/${REPORT}`)
    assert.equal(
      new Headers(options?.headers).get('Authorization'),
      'Bearer test-token',
    )

    const result = replies[calls++]

    if (result instanceof Error) throw result
    if (typeof result === 'function') return result()
    if (!result) throw new Error('Unexpected additional request')

    return result
  }) as typeof fetch

  const cancel = startReportPolling({
    reportId: REPORT,
    sessionId: SESSION,
    currentSessionId: () => currentSession,
    getFailures: () => failures,
    setFailures: count => {
      failures = count
    },
    fetchReport: getSessionReport,
    onJob: job => jobs.push(job.status),
    onError: error => errors.push(error),
    onStop: () => {
      stopped++
    },
    onMissing: () => {
      missing++
    },
    onUnauthenticated: () => {
      unauthorized++
    },
    setTimer: (callback, delayMs) => {
      const id = ++timerId
      delays.push(delayMs)
      pendingTimers.set(id, callback)
      return id
    },
    clearTimer: id => {
      pendingTimers.delete(id)
    },
  })

  return {
    async runNext() {
      const next = pendingTimers.entries().next().value
      assert.ok(next, 'Expected another timer')

      const [id, callback] = next
      pendingTimers.delete(id)
      callback()

      // Allow the report request and any token-refresh request to finish.
      for (let i = 0; i < 30; i++) {
        await Promise.resolve()
      }

      return id
    },
    pending: () => pendingTimers.size,
    calls: () => calls,
    delays,
    jobs,
    errors,
    stopped: () => stopped,
    missing: () => missing,
    unauthorized: () => unauthorized,
    failures: () => failures,
    cancel,
    setSession: id => {
      currentSession = id
    },
  }
}

beforeEach(() => {
  store.clear()
  saveAccessToken('test-token')
})

test('polls through queued and running to ready, then stops scheduling', async () => {
  const s = scenario([
    response(body('queued')),
    response(body('running')),
    response(body('ready')),
  ])

  assert.deepEqual(s.delays, [2000])

  await s.runNext()
  await s.runNext()
  await s.runNext()

  assert.deepEqual(s.jobs, ['queued', 'running', 'ready'])
  assert.deepEqual(s.delays, [2000, 2000, 2000])
  assert.equal(s.pending(), 0)
  assert.equal(s.failures(), 0)

  s.cancel()
})

test('stops polling when queued and running responses exceed the attempt limit', async () => {
  const replies = Array.from({ length: MAX_REPORT_POLL_ATTEMPTS }, (_, index) =>
    response(body(index % 2 === 0 ? 'queued' : 'running')),
  )

  const s = scenario(replies)

  for (let i = 0; i < MAX_REPORT_POLL_ATTEMPTS; i++) {
    await s.runNext()
  }

  assert.equal(s.calls(), MAX_REPORT_POLL_ATTEMPTS)
  assert.equal(s.jobs.length, MAX_REPORT_POLL_ATTEMPTS)
  assert.equal(s.stopped(), 1)
  assert.equal(s.pending(), 0)
  assert.match(
    s.errors.at(-1) ?? '',
    /Automatic status checks have stopped/,
  )

  s.cancel()
})
test('temporary HTTP failures apply bounded backoff and stop after four failures', async () => {
  const failures = Array.from(
    { length: 4 },
    () => response({ error: { message: 'Temporary outage' } }, 503),
  )

  const s = scenario(failures)

  for (let i = 0; i < 4; i++) {
    await s.runNext()
  }

  assert.deepEqual(s.delays, [2000, 4000, 8000, 10000])
  assert.equal(s.calls(), 4)
  assert.equal(s.failures(), 4)
  assert.equal(s.stopped(), 1)
  assert.equal(s.pending(), 0)
  assert.match(
    s.errors.at(-1) ?? '',
    /Automatic status checks have stopped/,
  )

  s.cancel()
})

test('403 stops polling immediately without retrying', async () => {
  const s = scenario([
    response(
      { error: { code: 'FORBIDDEN', message: 'Access denied.' } },
      403,
    ),
  ])

  await s.runNext()

  assert.equal(s.stopped(), 1)
  assert.equal(s.calls(), 1)
  assert.equal(s.pending(), 0)
  assert.match(s.errors.at(-1) ?? '', /Access denied/)

  s.cancel()
})

test('404 removes an expired report and stops polling', async () => {
  const s = scenario([
    response({ error: { code: 'NOT_FOUND' } }, 404),
  ])

  await s.runNext()

  assert.equal(s.missing(), 1)
  assert.equal(s.stopped(), 1)
  assert.equal(s.pending(), 0)

  s.cancel()
})

test('401 invokes the authentication handler after a rejected token refresh', async () => {
  const s = scenario([
    response({ error: { code: 'UNAUTHENTICATED' } }, 401),
  ])

  await s.runNext()

  assert.equal(s.unauthorized(), 1)
  assert.equal(s.calls(), 1)
  assert.equal(s.pending(), 0)
  assert.equal(store.get('clip_access_token'), undefined)

  s.cancel()
})

test('a cancelled poll cannot process a late API response', async () => {
  let resolveResponse!: (value: Response) => void

  const delayed = new Promise<Response>(resolve => {
    resolveResponse = resolve
  })

  const s = scenario([() => delayed])

  await s.runNext()
  s.cancel()

  resolveResponse(response(body('ready')))

  for (let i = 0; i < 30; i++) {
    await Promise.resolve()
  }

  assert.deepEqual(s.jobs, [])
  assert.equal(s.pending(), 0)
})

test('session changes and mismatched API sessions cannot update the visible report', async () => {
  const stale = scenario([response(body('ready'))])
  stale.setSession('another-session')

  await stale.runNext()

  assert.equal(stale.calls(), 0)
  assert.deepEqual(stale.jobs, [])
  stale.cancel()

  const mismatched = scenario([
    response(body('ready', 'different-session')),
  ])

  await mismatched.runNext()

  assert.deepEqual(mismatched.jobs, [])
  assert.equal(mismatched.stopped(), 1)
  assert.equal(mismatched.pending(), 0)

  mismatched.cancel()
})
