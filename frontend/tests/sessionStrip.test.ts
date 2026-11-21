import assert from 'node:assert/strict'
import test from 'node:test'

import type { QuestionBreakdown, SessionResponse } from '../src/features/sessions/sessionsApi.ts'
import { describeQuestion, stripFromDeliveries, stripFromResponses } from '../src/features/sessions/strip.ts'

let next = 0
function answer(question: string, at: string, correct: boolean | null): SessionResponse {
  next += 1
  return {
    id: `r${next}`,
    question_id: question,
    student_id: `s${next}`,
    selected_option: correct === null ? null : 0,
    free_text: correct === null ? 'words' : null,
    is_correct: correct,
    elapsed_ms: 1000,
    submitted_at: at,
  }
}

test('questions come in the order the class first answered them', () => {
  const strip = stripFromResponses([
    answer('second', '2026-10-16T10:05:00Z', true),
    answer('first', '2026-10-16T10:01:00Z', true),
    answer('second', '2026-10-16T10:04:30Z', false),
  ])
  assert.deepEqual(strip.map((q) => [q.questionId, q.position]), [['first', 1], ['second', 2]])
})

test('each answer counts as right, wrong or not marked yet', () => {
  const [question] = stripFromResponses([
    answer('q', '2026-10-16T10:00:00Z', true),
    answer('q', '2026-10-16T10:00:01Z', true),
    answer('q', '2026-10-16T10:00:02Z', false),
    answer('q', '2026-10-16T10:00:03Z', null),
  ])
  assert.deepEqual([question.right, question.wrong, question.unmarked], [2, 1, 1])
  assert.equal(describeQuestion(question), 'Question 1: 4 answers, 2 right, 1 wrong, 1 not marked yet')
})

test('a session with no answers has an empty strip', () => {
  assert.deepEqual(stripFromResponses([]), [])
})

test('free text only says how many are waiting', () => {
  const [question] = stripFromResponses([answer('q', '2026-10-16T10:00:00Z', null)])
  assert.equal(describeQuestion(question), 'Question 1: 1 answer, 1 not marked yet')
})


test('recorded deliveries preserve zero-response checkpoints and their positions', () => {
  const checkpoint = {
    prompt: 'A checkpoint',
    type: 'mcq',
    options: null,
    correct_option: null,
    topic: null,
    eligible: 4,
    option_counts: null,
    median_seconds: null,
  } satisfies Partial<QuestionBreakdown>
  const strip = stripFromDeliveries([
    { ...checkpoint, number: 1, question_id: 'missed', answers: 0, correct: 0, marked: 0 },
    { ...checkpoint, number: 2, question_id: 'answered', answers: 4, correct: 2, marked: 3 },
  ])
  assert.deepEqual(strip, [
    { questionId: 'missed', position: 1, right: 0, wrong: 0, unmarked: 0 },
    { questionId: 'answered', position: 2, right: 2, wrong: 1, unmarked: 1 },
  ])
  assert.equal(describeQuestion(strip[0]), 'Question 1: 0 answers')
})
