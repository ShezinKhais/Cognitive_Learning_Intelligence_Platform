import assert from 'node:assert/strict'
import test from 'node:test'

import {
  getTeamsEnvironment,
  isTeamsMockAllowed,
} from '../src/teams/teamsEnvironment.ts'

test('reports production and development environments correctly', () => {
  assert.equal(getTeamsEnvironment(false), 'development')
  assert.equal(getTeamsEnvironment(true), 'production')
})

test('allows Teams mock only when explicitly enabled in development', () => {
  assert.equal(
    isTeamsMockAllowed({
      production: false,
      mockEnabled: true,
    }),
    true,
  )
})

test('does not enable Teams mock by default in development', () => {
  assert.equal(
    isTeamsMockAllowed({
      production: false,
      mockEnabled: false,
    }),
    false,
  )
})

test('blocks Teams mock in production even when mock is enabled', () => {
  assert.equal(
    isTeamsMockAllowed({
      production: true,
      mockEnabled: true,
    }),
    false,
  )
})

test('keeps Teams mock disabled in production when the flag is disabled', () => {
  assert.equal(
    isTeamsMockAllowed({
      production: true,
      mockEnabled: false,
    }),
    false,
  )
})