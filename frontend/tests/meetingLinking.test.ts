import assert from 'node:assert/strict'
import test from 'node:test'

import { linkableSessions } from '../src/features/live/meetingLinking.ts'
import type { SessionSummary } from '../src/features/sessions/sessionsApi.ts'

function session(id: string, overrides: Partial<SessionSummary>): SessionSummary {
  return {
    id,
    course_code: 'CSIT321',
    title: id,
    status: 'prepared',
    starts_at: null,
    ended_at: null,
    lecturer_id: 'l',
    participant_count: 0,
    questions_delivered: 0,
    paused: false,
    teams_meeting_id: null,
    ...overrides,
  }
}

test('only unfinished sessions no meeting holds can be linked, soonest first', () => {
  const found = linkableSessions([
    session('later', { starts_at: '2026-11-05T10:00:00Z' }),
    session('ended', { status: 'ended' }),
    session('held', { teams_meeting_id: 'another-meeting' }),
    session('unscheduled', {}),
    session('live', { status: 'active', starts_at: '2026-11-04T09:00:00Z' }),
    session('cancelled', { status: 'cancelled' }),
  ])
  assert.deepEqual(found.map((s) => s.id), ['live', 'later', 'unscheduled'])
})
