import assert from 'node:assert/strict'
import test from 'node:test'

import { canAccessStaffTeamsSurface } from '../src/teams/staffTeamsAccess.ts'

test('allows an authenticated and consented lecturer', () => {
  assert.equal(
    canAccessStaffTeamsSurface({
      clipRole: 'lecturer',
      hasConsent: true,
    }),
    true,
  )
})

test('allows an authenticated and consented administrator', () => {
  assert.equal(
    canAccessStaffTeamsSurface({
      clipRole: 'admin',
      hasConsent: true,
    }),
    true,
  )
})

test('never grants the staff surface to a student', () => {
  assert.equal(
    canAccessStaffTeamsSurface({
      clipRole: 'student',
      hasConsent: true,
    }),
    false,
  )
})

test('blocks a lecturer until C.L.I.P consent is satisfied', () => {
  assert.equal(
    canAccessStaffTeamsSurface({
      clipRole: 'lecturer',
      hasConsent: false,
    }),
    false,
  )
})

test('blocks an administrator until C.L.I.P consent is satisfied', () => {
  assert.equal(
    canAccessStaffTeamsSurface({
      clipRole: 'admin',
      hasConsent: false,
    }),
    false,
  )
})