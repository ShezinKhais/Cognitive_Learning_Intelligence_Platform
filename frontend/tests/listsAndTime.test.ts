import assert from 'node:assert/strict'
import test from 'node:test'

import { countBy, filterMaterials, filterSessions, materialState, matches } from '../src/features/format/listFilters.ts'
import { formatElapsed, formatRelative, sinceVerb } from '../src/features/format/relativeTime.ts'
import {
  badgeLabel,
  buildNotifications,
  groupByDay,
  MAX_NOTIFICATIONS,
  type AppNotification,
} from '../src/features/notifications/notifications.ts'
import type { SessionSummary } from '../src/features/sessions/sessionsApi.ts'

// 12:00 in Dubai.
const NOW = Date.parse('2026-10-16T08:00:00Z')
const ago = (ms: number) => new Date(NOW - ms).toISOString()
const MIN = 60_000
const HOUR = 60 * MIN

test('relative times read the way a person says them', () => {
  assert.equal(formatRelative(ago(20_000), NOW), 'Just now')
  assert.equal(formatRelative(ago(5 * MIN), NOW), '5 min ago')
  assert.equal(formatRelative(ago(3 * HOUR), NOW), '3 h ago')
  assert.equal(formatRelative(ago(24 * HOUR), NOW), 'Yesterday')
  assert.equal(formatRelative(ago(3 * 24 * HOUR), NOW), '3 days ago')
  assert.match(formatRelative('2026-09-01T08:00:00Z', NOW), /^1 Sept?$/)
  assert.equal(formatRelative(null, NOW), '')
  assert.equal(formatRelative('not a date', NOW), '')
})

test('yesterday is by the calendar in Dubai, not 24 hours', () => {
  // 23:30 the evening before, Dubai time: twelve and a half hours ago.
  assert.equal(formatRelative('2026-10-15T19:30:00Z', NOW), 'Yesterday')
})

test('after a verb a leading word is lowered and a month is not', () => {
  assert.equal(sinceVerb('Ended', ago(20_000), NOW), 'Ended just now')
  assert.equal(sinceVerb('Ended', ago(24 * HOUR), NOW), 'Ended yesterday')
  assert.match(sinceVerb('Uploaded', '2026-09-01T08:00:00Z', NOW), /^Uploaded 1 Sept?$/)
  assert.equal(sinceVerb('Ended', null, NOW), '')
})

test('elapsed time is minutes and seconds, then hours', () => {
  assert.equal(formatElapsed(0), '0:00')
  assert.equal(formatElapsed(65), '1:05')
  assert.equal(formatElapsed(3725), '1:02:05')
  assert.equal(formatElapsed(-5), '0:00')
})

test('every word of a search must match, in any order and any case', () => {
  assert.ok(matches('week 7', 'Week 7: Threat modelling', 'CSIT321'))
  assert.ok(matches('csit321 threat', 'Week 7: Threat modelling', 'CSIT321'))
  assert.ok(matches('  ', 'anything'))
  assert.ok(matches('resume', 'Résumé writing'))
  assert.ok(!matches('week 8', 'Week 7: Threat modelling', 'CSIT321'))
})

function session(id: string, status: SessionSummary['status'], title = `Session ${id}`): SessionSummary {
  return {
    id, course_code: 'CSIT321', title, status, starts_at: null, ended_at: null, lecturer_id: 'l',
    participant_count: 0, questions_delivered: 0, paused: false, teams_meeting_id: null,
  }
}

test('sessions filter by state and search together', () => {
  const all = [session('a', 'active', 'Week 7'), session('b', 'prepared', 'Week 8'), session('c', 'ended', 'Week 6')]
  assert.deepEqual(filterSessions(all, '', 'live').map((s) => s.id), ['a'])
  assert.deepEqual(filterSessions(all, 'week', 'finished').map((s) => s.id), ['c'])
  assert.deepEqual(filterSessions(all, 'week 8', 'all').map((s) => s.id), ['b'])
  assert.deepEqual(filterSessions(all, 'week 8', 'live'), [])
})

test('materials filter by state, counting pending as processing', () => {
  const all = [
    { status: 'completed' as const, filename: 'w7.pdf', course_code: 'CSIT321' },
    { status: 'pending' as const, filename: 'w8.pptx', course_code: null },
    { status: 'failed' as const, filename: 'broken.docx', course_code: 'CSIT321' },
  ]
  assert.deepEqual(filterMaterials(all, '', 'processing').map((m) => m.filename), ['w8.pptx'])
  assert.deepEqual(filterMaterials(all, 'csit321', 'all').map((m) => m.filename), ['w7.pdf', 'broken.docx'])
  assert.deepEqual(countBy(all, materialState), { ready: 1, processing: 1, failed: 1 })
})

test('the badge stops counting at 99', () => {
  assert.equal(badgeLabel(7), '7')
  assert.equal(badgeLabel(99), '99')
  assert.equal(badgeLabel(273), '99+')
})

test('notifications are capped and grouped by day', () => {
  const many = Array.from({ length: 50 }, (_, i) => ({ ...session(`s${i}`, 'active'), starts_at: ago(i * MIN) }))
  assert.equal(buildNotifications('lecturer', { sessions: many, now: NOW }).length, MAX_NOTIFICATIONS)

  const item = (id: string, at: string): AppNotification => ({ id, kind: 'live', title: id, detail: '', to: '/', action: '', at })
  const groups = groupByDay([item('now', ago(MIN)), item('last-night', '2026-10-15T19:30:00Z'), item('monday', ago(3 * 24 * HOUR))], NOW)
  assert.deepEqual(
    groups.map((group) => [group.label, group.items.map((i) => i.id)]),
    [['Today', ['now']], ['Yesterday', ['last-night']], ['Earlier this week', ['monday']]],
  )
})
