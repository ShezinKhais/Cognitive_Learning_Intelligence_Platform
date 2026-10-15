import assert from 'node:assert/strict'
import test from 'node:test'

// api.ts reads the token from localStorage and calls fetch; both are stubbed.
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

// Without Web Locks, so the sharing tested here is this tab's own.
Object.defineProperty(globalThis, 'navigator', { value: {}, configurable: true })

// The backend: a token is good until it is refreshed, and refreshing a token
// the backend no longer accepts is a 401.
let valid = new Set<string>()
let refreshes = 0
let issued = 0
let requests: string[] = []

function bearer(init?: RequestInit): string {
  return new Headers(init?.headers).get('Authorization')?.replace('Bearer ', '') ?? ''
}

globalThis.fetch = (async (url: string, init?: RequestInit) => {
  const path = String(url)
  const token = bearer(init)
  requests.push(`${path} ${token}`)
  if (path.endsWith('/auth/login')) {
    return new Response('{}', { status: 401 })
  }
  if (path.endsWith('/auth/refresh')) {
    refreshes += 1
    await new Promise((resolve) => setTimeout(resolve, 5))
    if (!valid.has(token)) return new Response('{}', { status: 401 })
    valid.delete(token)
    issued += 1
    const fresh = `fresh-${issued}`
    valid.add(fresh)
    return new Response(
      JSON.stringify({ access_token: fresh, token_type: 'bearer', expires_in: 3600, role: 'lecturer' }),
      { status: 200 },
    )
  }
  if (!token.startsWith('fresh-')) return new Response('{}', { status: 401 })
  return new Response(JSON.stringify({ ok: token }), { status: 200 })
}) as typeof fetch

const {
  ApiError,
  apiAuthenticatedGet,
  clearAccessToken,
  getAccessToken,
  login,
  saveAccessToken,
} = await import('../src/api.ts')

function reset(token: string, refreshable: boolean): void {
  valid = new Set(refreshable ? [token] : [])
  refreshes = 0
  requests = []
  saveAccessToken(token)
}

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
  // One try, one refresh, no retry with nothing.
  assert.equal(requests.length, 2)
})

test('login is never refreshed or retried', async () => {
  reset('anything', true)
  clearAccessToken()

  await assert.rejects(login('a@b.c', 'wrong'))
  assert.deepEqual(requests, ['/api/v1/auth/login '])
})

test('the token is refreshed before it expires, without waiting for a 401', async () => {
  valid = new Set(['about-to-expire'])
  refreshes = 0
  // Inside the five minutes before expiry, so the refresh is due at once.
  saveAccessToken('about-to-expire', 60)

  await new Promise((resolve) => setTimeout(resolve, 30))

  assert.equal(refreshes, 1)
  assert.ok(getAccessToken()?.startsWith('fresh-'))
  clearAccessToken()
})
