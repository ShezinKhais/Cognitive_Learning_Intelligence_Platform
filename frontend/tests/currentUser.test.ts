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

let calls = 0
let consents: string[] = []
globalThis.fetch = (async (url: string) => {
  if (String(url).endsWith('/auth/consent')) {
    consents = ['terms']
    return new Response(JSON.stringify({ consent_type: 'terms', granted: true }), { status: 200 })
  }
  calls += 1
  return new Response(
    JSON.stringify({ id: 'u', email: 'e', full_name: 'n', role: 'lecturer', consents }),
    { status: 200 },
  )
}) as typeof fetch

const { getCurrentUser, recordConsent, saveAccessToken } = await import('../src/api.ts')

test('landing checks identity once, not once per guard', async () => {
  saveAccessToken('token-a')
  calls = 0
  await Promise.all([getCurrentUser(), getCurrentUser()])
  await getCurrentUser()
  assert.equal(calls, 1)
})

test('a new token or a consent change is never answered from before', async () => {
  saveAccessToken('token-b')
  calls = 0
  consents = []
  const before = await getCurrentUser()
  assert.deepEqual(before.consents, [])

  await recordConsent('terms', true)
  const after = await getCurrentUser()
  assert.deepEqual(after.consents, ['terms'])

  saveAccessToken('token-c')
  await getCurrentUser()
  assert.equal(calls, 3)
})
