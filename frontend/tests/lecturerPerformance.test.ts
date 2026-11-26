import assert from 'node:assert/strict'
import test from 'node:test'

import { averageStudentAccuracy } from '../src/features/live/lecturerPerformance.ts'

test('averages each student equally even when answer counts differ', () => {
  const result = averageStudentAccuracy([
    { student_id: 'a', is_correct: true },
    { student_id: 'a', is_correct: true },
    { student_id: 'a', is_correct: true },
    { student_id: 'b', is_correct: false },
  ])
  assert.deepEqual(result, { average: 50, students: 2 })
})

test('excludes unmarked answers and students without marked answers', () => {
  const result = averageStudentAccuracy([
    { student_id: 'a', is_correct: true },
    { student_id: 'a', is_correct: null },
    { student_id: 'b', is_correct: null },
    { student_id: 'c', is_correct: false },
  ])
  assert.deepEqual(result, { average: 50, students: 2 })
})

test('returns null when no answers have been marked', () => {
  assert.equal(averageStudentAccuracy([]), null)
  assert.equal(averageStudentAccuracy([
    { student_id: 'a', is_correct: null },
  ]), null)
})

test('handles one student and fractional percentages', () => {
  const one = averageStudentAccuracy([
    { student_id: 'a', is_correct: true },
    { student_id: 'a', is_correct: false },
    { student_id: 'a', is_correct: false },
  ])
  assert.ok(one)
  assert.equal(one.students, 1)
  assert.ok(Math.abs(one.average - 100 / 3) < 0.000001)
})
