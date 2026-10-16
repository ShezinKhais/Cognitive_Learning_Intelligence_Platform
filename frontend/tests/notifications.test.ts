import assert from 'node:assert/strict'
import test from 'node:test'

import { buildNotifications, unreadCount } from '../src/features/notifications/notifications.ts'
import type { SessionSummary } from '../src/features/sessions/sessionsApi.ts'

const NOW = Date.parse('2026-10-16T12:00:00Z')

function session(id: string, status: SessionSummary['status'], ended_at: string | null = null): SessionSummary {
  return {
    id,
    course_code: 'CSIT321',
    title: `Session ${id}`,
    status,
    starts_at: '2026-10-16T10:00:00Z',
    ended_at,
    lecturer_id: 'l',
    participant_count: 0,
    questions_delivered: 0,
    paused: false,
    teams_meeting_id: null,
  }
}

test('a live session tells a student to join and a lecturer to open it', () => {
  const [forStudent] = buildNotifications('student', { sessions: [session('a', 'active')], now: NOW })
  assert.equal(forStudent.to, '/student/session/a')
  const [forLecturer] = buildNotifications('lecturer', { sessions: [session('a', 'active')], now: NOW })
  assert.equal(forLecturer.to, '/lecturer/sessions/a/live')
})

test('only sessions finished this week are mentioned', () => {
  const found = buildNotifications('student', {
    sessions: [session('new', 'ended', '2026-10-15T12:00:00Z'), session('old', 'ended', '2026-09-01T12:00:00Z')],
    now: NOW,
  })
  assert.deepEqual(found.map((n) => n.id), ['ended-new'])
})

test('students are never told about materials, admins about down services', () => {
  const material = {
    id: 'm', filename: 'w7.pdf', content_type: 'application/pdf', size_bytes: 1, status: 'completed' as const,
    page_count: 1, chunk_count: 1, error: null, uploaded_at: '2026-10-16T09:00:00Z',
  }
  assert.equal(buildNotifications('student', { materials: [material], now: NOW }).length, 0)
  assert.equal(buildNotifications('lecturer', { materials: [material], now: NOW })[0].to, '/materials/m/review')
  assert.equal(buildNotifications('lecturer', { down: ['Database'], now: NOW }).length, 0)
  assert.equal(buildNotifications('admin', { down: ['Database'], now: NOW })[0].kind, 'problem')
})

test('read notifications are not counted', () => {
  const found = buildNotifications('student', { sessions: [session('a', 'active'), session('b', 'active')], now: NOW })
  assert.equal(unreadCount(found, new Set(['live-a'])), 1)
})
