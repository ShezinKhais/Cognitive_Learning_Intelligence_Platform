import assert from 'node:assert/strict'
import test from 'node:test'

import { CODE_PATTERN, decidedRecently, waiting, type CourseRequest } from '../src/features/courses/courseRequests.ts'
import { buildNotifications } from '../src/features/notifications/notifications.ts'

const NOW = Date.parse('2026-11-08T12:00:00Z')

function request(overrides: Partial<CourseRequest>): CourseRequest {
  return {
    id: 'r1',
    code: 'CSIT399',
    name: 'Graph Theory',
    reason: null,
    status: 'pending',
    requested_by: 'lecturer',
    requester_name: 'Dr Rivera',
    decision_note: null,
    created_at: '2026-11-08T10:00:00Z',
    decided_at: null,
    ...overrides,
  }
}

test('a course code follows the server rule', () => {
  assert.equal(CODE_PATTERN.test('CSIT399'), true)
  assert.equal(CODE_PATTERN.test('CSIT 399'), false)
  assert.equal(CODE_PATTERN.test('C'), false)
})

test('waiting and recently decided requests are told apart', () => {
  const requests = [
    request({ id: 'a' }),
    request({ id: 'b', status: 'approved', decided_at: '2026-11-07T12:00:00Z' }),
    request({ id: 'c', status: 'declined', decided_at: '2026-10-01T12:00:00Z' }),
  ]
  assert.deepEqual(waiting(requests).map((r) => r.id), ['a'])
  assert.deepEqual(decidedRecently(requests, NOW).map((r) => r.id), ['b'])
})

test('an admin is told how many course requests are waiting', () => {
  const one = buildNotifications('admin', { courseRequests: [request({})], now: NOW })
  assert.equal(one[0].title, 'CSIT399 is waiting for approval')
  assert.equal(one[0].detail, 'Asked for by Dr Rivera')
  assert.equal(one[0].to, '/courses')

  const two = buildNotifications('admin', {
    courseRequests: [request({}), request({ id: 'r2', code: 'CSIT400', created_at: '2026-11-08T11:00:00Z' })],
    now: NOW,
  })
  assert.equal(two[0].title, '2 course requests are waiting')
  // A new request changes the id, so it shows as unread again.
  assert.equal(two[0].id, 'course-requests-r2')
})

test('a lecturer is told what was decided this week, with the reason for a decline', () => {
  const told = buildNotifications('lecturer', {
    courseRequests: [
      request({ id: 'ok', status: 'approved', decided_at: '2026-11-08T09:00:00Z' }),
      request({ id: 'no', code: 'CSIT401', status: 'declined', decision_note: 'Taught in CSIT321', decided_at: '2026-11-08T08:00:00Z' }),
      request({ id: 'old', status: 'approved', decided_at: '2026-09-01T09:00:00Z' }),
      request({ id: 'wait' }),
    ],
    now: NOW,
  })
  assert.deepEqual(
    told.map((item) => [item.title, item.detail]),
    [
      ['CSIT399 was added', 'You are its lecturer'],
      ['CSIT401 was declined', 'Taught in CSIT321'],
    ],
  )
})

test('a student is never told about course requests', () => {
  assert.deepEqual(buildNotifications('student', { courseRequests: [request({})], now: NOW }), [])
})
