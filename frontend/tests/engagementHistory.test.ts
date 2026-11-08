import assert from 'node:assert/strict'
import test from 'node:test'

import { answerTrend, coursesOf, percent, quietReason } from '../src/features/sessions/engagementHistory.ts'
import type { SessionEngagement } from '../src/features/sessions/engagementHistoryApi.ts'

function row(code: string, answer: number | null): SessionEngagement {
  return {
    session_id: Math.random().toString(),
    title: 't',
    course_code: code,
    held_at: '2026-10-01T09:00:00Z',
    present: 10,
    checkpoints: 2,
    answer_rate: answer,
    correct_rate: null,
    on_screen: null,
  }
}

test('percent says when there is nothing to show', () => {
  assert.equal(percent(null), 'No data')
  assert.equal(percent(0.456), '46%')
})

test('the reason names missed classes before a low answer rate', () => {
  const base = { student_id: 's', name: 'n', course_code: 'C', sessions_considered: 4 }
  assert.equal(quietReason({ ...base, sessions_missed: 3, answer_rate: null }), 'Missed 3 of the last 4 classes')
  assert.equal(
    quietReason({ ...base, sessions_missed: 0, answer_rate: 0.25 }),
    'Answered 25% of checkpoints in the last 4 classes',
  )
})

test('courses keep their first order and appear once', () => {
  assert.deepEqual(coursesOf([row('B', 1), row('A', 1), row('B', 1)]), ['B', 'A'])
})

test('the trend compares the newest class with the average of the rest', () => {
  assert.equal(answerTrend([row('A', 0.9), row('A', 0.5), row('A', 0.7)]), 0.3)
  assert.equal(answerTrend([row('A', 0.5), row('A', null)]), null)
})
