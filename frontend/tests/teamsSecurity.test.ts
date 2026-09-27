import assert from 'node:assert/strict'
import test from 'node:test'

import {
  teamsContentSecurityPolicy,
  teamsFrameAncestors,
} from '../src/teams/teamsSecurity.ts'

test('Teams frame ancestors allow only CLIP and Microsoft Teams hosts', () => {
  assert.deepEqual(teamsFrameAncestors(), [
    "'self'",
    'https://teams.microsoft.com',
    'https://*.teams.microsoft.com',
    'https://*.cloud.microsoft',
  ])
})

test('Teams CSP does not allow arbitrary frame ancestors', () => {
  const policy = teamsContentSecurityPolicy()

  assert.match(policy, /frame-ancestors/)
  assert.doesNotMatch(policy, /frame-ancestors \*/)
  assert.doesNotMatch(policy, /http:/)
})

test('Teams CSP blocks embedded objects', () => {
  assert.match(
    teamsContentSecurityPolicy(),
    /object-src 'none'/,
  )
})

test('Teams CSP restricts the document base URL to its own origin', () => {
  assert.match(
    teamsContentSecurityPolicy(),
    /base-uri 'self'/,
  )
})