import assert from 'node:assert/strict'
import test from 'node:test'

// api.ts clears where earlier builds kept the token and calls fetch; both are
// stubbed. The token itself is only ever in memory.
const store = new Map<string, string>([
  ['clip_access_token', 'left-by-an-old-build'],
  ['clip_access_token_expires_at', '1'],
])
Object.assign(globalThis, {
  window: {
    localStorage: {
      getItem: (key: string) => store.get(key) ?? null,
      setItem: (key: string, value: string) => void store.set(key, value),
      removeItem: (key: string) => void store.delete(key),
    },
  },
})

// The backend. The refresh cookie is the browser's, so it is modelled as a
// flag: while it holds, a refresh carrying the header returns a new token.
// Access tokens are good until the next one is issued.
let cookie = false
let valid = new Set<string>()
let refreshes = 0
let issued = 0
let requests: string[] = []
// Refreshes that fail before the backend answers: 'offline' throws, a number
// is that status. Taken in order, then refreshes work again.
let failures: Array<'offline' | number> = []
// Off when timers are mocked, where a real wait would never end.
let slowRefresh = true

function header(init: RequestInit | undefined, name: string): string {
  return new Headers(init?.headers).get(name) ?? ''
}

globalThis.fetch = (async (url: string, init?: RequestInit) => {
  const path = String(url)
  const token = header(init, 'Authorization').replace('Bearer ', '')
  requests.push(`${path} ${token}`)
  if (path.endsWith('/auth/login')) {
    return new Response('{}', { status: 401 })
  }
  if (path.endsWith('/auth/logout')) {
    if (header(init, 'X-CLIP-Refresh') === '1') cookie = false
    return new Response(null, { status: 204 })
  }
  if (path.endsWith('/auth/refresh')) {
    refreshes += 1
    if (slowRefresh) await new Promise((resolve) => setTimeout(resolve, 5))
    const failure = failures.shift()
    if (failure === 'offline') throw new TypeError('Failed to fetch')
    if (failure !== undefined) return new Response('{}', { status: failure })
    // The backend never reads a bearer here.
    if (token) return new Response('{}', { status: 400 })
    if (!cookie || header(init, 'X-CLIP-Refresh') !== '1') return new Response('{}', { status: 401 })
    issued += 1
    const fresh = `fresh-${issued}`
    valid = new Set([fresh])
    return new Response(
      JSON.stringify({ access_token: fresh, token_type: 'bearer', expires_in: 3600, role: 'lecturer' }),
      { status: 200 },
    )
  }
  if (!valid.has(token)) return new Response('{}', { status: 401 })
  return new Response(JSON.stringify({ ok: token }), { status: 200 })
}) as typeof fetch

const {
  ApiError,
  apiAuthenticatedGet,
  clearAccessToken,
  getAccessToken,
  login,
  restoreSession,
  saveAccessToken,
} = await import('../src/api.ts')

const settle = async () => {
  for (let i = 0; i < 10; i += 1) await new Promise((resolve) => setImmediate(resolve))
}

// Signed in with this token; the cookie is still good or not.
function reset(token: string, signedIn: boolean): void {
  cookie = signedIn
  valid = new Set()
  refreshes = 0
  requests = []
  saveAccessToken(token)
}

test('nothing is left where earlier builds kept the token', () => {
  assert.equal(store.has('clip_access_token'), false)
  assert.equal(store.has('clip_access_token_expires_at'), false)
})

test('requests failing together share one refresh and each retry once', async () => {
  reset('expired', true)

  const answers = await Promise.all([
    apiAuthenticatedGet<{ ok: string }>('/sessions/a/engagement'),
    apiAuthenticatedGet<{ ok: string }>('/sessions/a/alerts'),
    apiAuthenticatedGet<{ ok: string }>('/sessions/a/topics'),
  ])

  assert.equal(refreshes, 1)
  const token = getAccessToken()
  assert.ok(token?.startsWith('fresh-'))
  assert.deepEqual(answers.map((a) => a.ok), [token, token, token])
  clearAccessToken()
})

test('a refresh the backend refuses signs the user out', async () => {
  reset('stale', false)

  await assert.rejects(
    apiAuthenticatedGet('/auth/me'),
    (error: unknown) => error instanceof ApiError && error.status === 401,
  )
  assert.equal(refreshes, 1)
  assert.equal(getAccessToken(), null)
  // One try, one refresh, no retry with nothing, then the cookie is dropped.
  assert.deepEqual(
    requests.map((line) => line.split(' ')[0]),
    ['/api/v1/auth/me', '/api/v1/auth/refresh', '/api/v1/auth/logout'],
  )
})

test('a reload signs back in with the cookie, and the token stays in memory', async () => {
  reset('anything', true)
  clearAccessToken()
  await settle()
  cookie = true
  requests = []

  const token = await restoreSession()

  assert.ok(token?.startsWith('fresh-'))
  assert.equal(getAccessToken(), token)
  assert.equal(store.size, 0)
  // A second caller uses the token already held.
  assert.equal(await restoreSession(), token)
  assert.equal(refreshes, 1)
  clearAccessToken()
})

test('with no cookie a reload is signed out, not an error', async () => {
  reset('anything', false)
  clearAccessToken()
  await settle()

  assert.equal(await restoreSession(), null)
})

test('an unreachable backend at reload is an error, not a sign-out', async () => {
  reset('anything', true)
  clearAccessToken()
  await settle()
  cookie = true
  failures = ['offline']

  await assert.rejects(
    restoreSession(),
    (error: unknown) => error instanceof ApiError && error.status === 503,
  )
  assert.equal(cookie, true)
})

test('signing out drops the cookie, so a reload does not sign back in', async () => {
  reset('anything', true)

  clearAccessToken()
  await settle()

  assert.equal(getAccessToken(), null)
  assert.equal(cookie, false)
  assert.equal(await restoreSession(), null)
})

test('a refresh still on its way when the user signs out does not sign them back in', async () => {
  reset('kept', true)
  clearAccessToken()
  cookie = true
  // A reload's refresh, then sign-out before it is answered. The backend
  // answers the refresh first, while the cookie still holds.
  const restoring = restoreSession()
  clearAccessToken()
  cookie = true
  assert.equal(await restoring, null)
  assert.equal(getAccessToken(), null)
})

test('a wrong password does not sign anyone out', async () => {
  reset('anything', true)
  requests = []

  await assert.rejects(login('a@b.c', 'wrong'))

  assert.deepEqual(requests, ['/api/v1/auth/login '])
  assert.equal(getAccessToken(), 'anything')
  assert.equal(cookie, true)
  clearAccessToken()
})

test('the token is refreshed before it expires, without waiting for a 401', async () => {
  cookie = true
  refreshes = 0
  // Inside the five minutes before expiry, so the refresh is due at once.
  saveAccessToken('about-to-expire', 60)

  await new Promise((resolve) => setTimeout(resolve, 30))

  assert.equal(refreshes, 1)
  assert.ok(getAccessToken()?.startsWith('fresh-'))
  clearAccessToken()
})

test('a refresh that fails while the token is valid is tried again until one works', async (t) => {
  t.mock.timers.enable({ apis: ['setTimeout', 'Date'], now: 1_000_000 })
  slowRefresh = false
  cookie = true
  refreshes = 0
  failures = ['offline', 503]

  // Two minutes left, so the refresh is due at once.
  saveAccessToken('due', 120)
  t.mock.timers.tick(0)
  await settle()
  assert.equal(refreshes, 1)
  assert.equal(getAccessToken(), 'due')

  t.mock.timers.tick(30_000)
  await settle()
  assert.equal(refreshes, 2)
  assert.equal(getAccessToken(), 'due')

  t.mock.timers.tick(30_000)
  await settle()
  assert.equal(refreshes, 3)
  assert.ok(getAccessToken()?.startsWith('fresh-'))

  clearAccessToken()
  slowRefresh = true
})

test('a failed refresh is not retried once the token has expired', async (t) => {
  t.mock.timers.enable({ apis: ['setTimeout', 'Date'], now: 2_000_000 })
  slowRefresh = false
  cookie = true
  refreshes = 0
  failures = ['offline', 'offline', 'offline']

  // Forty seconds left: one try now, one retry at 30s, none after expiry.
  saveAccessToken('nearly-gone', 40)
  t.mock.timers.tick(0)
  await settle()
  t.mock.timers.tick(30_000)
  await settle()
  t.mock.timers.tick(10_000)
  await settle()
  t.mock.timers.tick(60_000)
  await settle()

  assert.equal(refreshes, 3)
  failures = []
  clearAccessToken()
  slowRefresh = true
})
