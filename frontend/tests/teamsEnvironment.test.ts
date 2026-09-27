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

test('allows Teams mock only when explicitly enabled and requested in development', () => {
  assert.equal(
    isTeamsMockAllowed({
      production: false,
      mockEnabled: true,
      mockRequested: true,
    }),
    true,
  )
})

test('does not enable Teams mock when the environment flag is disabled', () => {
  assert.equal(
    isTeamsMockAllowed({
      production: false,
      mockEnabled: false,
      mockRequested: true,
    }),
    false,
  )
})

test('does not enable Teams mock without an explicit request', () => {
  assert.equal(
    isTeamsMockAllowed({
      production: false,
      mockEnabled: true,
      mockRequested: false,
    }),
    false,
  )
})

test('blocks Teams mock in production even when enabled and requested', () => {
  assert.equal(
    isTeamsMockAllowed({
      production: true,
      mockEnabled: true,
      mockRequested: true,
    }),
    false,
  )
})

test('blocks a crafted Teams mock request in production', () => {
  assert.equal(
    isTeamsMockAllowed({
      production: true,
      mockEnabled: false,
      mockRequested: true,
    }),
    false,
  )
})

test('keeps Teams mock disabled when no mock controls are enabled', () => {
  assert.equal(
    isTeamsMockAllowed({
      production: false,
      mockEnabled: false,
      mockRequested: false,
    }),
    false,
  )
})
