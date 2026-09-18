import assert from 'node:assert/strict'
import test from 'node:test'

import type { CurrentUser } from '../src/api.ts'
import {
  hasRequiredConsent,
  intendedPathForRole,
} from '../src/authRouting.ts'

function user(
  role: CurrentUser['role'],
  consents: CurrentUser['consents'],
): CurrentUser {
  return {
    id: 'test-user',
    email: 'test@clip.example.com',
    full_name: 'Test User',
    role,
    consents,
  }
}

test('terms consent is the only required consent', () => {
  assert.equal(hasRequiredConsent(user('student', [])), false)
  assert.equal(hasRequiredConsent(user('admin', [])), false)
  assert.equal(hasRequiredConsent(user('lecturer', [])), false)
  assert.equal(hasRequiredConsent(user('student', ['terms'])), true)
  assert.equal(hasRequiredConsent(user('lecturer', ['terms'])), true)
  assert.equal(
    hasRequiredConsent(
      user('student', [
        'camera',
        'microphone',
        'engagement_monitoring',
      ]),
    ),
    false,
  )
})

test('students return only to student pages', () => {
  assert.equal(intendedPathForRole('student'), '/student')
  assert.equal(
    intendedPathForRole('student', '/student/session/123'),
    '/student/session/123',
  )
  assert.equal(
    intendedPathForRole('student', '/admin'),
    '/student',
  )
})

test('administrators return only to admin pages', () => {
  assert.equal(intendedPathForRole('admin'), '/admin')
  assert.equal(
    intendedPathForRole('admin', '/admin/roster'),
    '/admin/roster',
  )
  assert.equal(
    intendedPathForRole('admin', '/student'),
    '/admin',
  )
})

test('lecturers return only to lecturer pages', () => {
  assert.equal(
    intendedPathForRole('lecturer'),
    '/lecturer/materials',
  )
  assert.equal(
    intendedPathForRole('lecturer', '/lecturer/materials'),
    '/lecturer/materials',
  )
  assert.equal(
    intendedPathForRole('lecturer', '/admin'),
    '/lecturer/materials',
  )
})
