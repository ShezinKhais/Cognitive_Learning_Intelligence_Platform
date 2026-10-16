import assert from 'node:assert/strict'
import test from 'node:test'
import {
  comprehensionText,
  needsReview,
  reviewError,
} from '../src/features/review/reviewDisplay.ts'
import type { ReviewAnswer } from '../src/features/review/reviewTypes.ts'

const answer: ReviewAnswer = {
  id: 'r',
  question: 'Why?',
  answer: 'Because',
  topic: null,
  is_correct: null,
  label: null,
  confidence: null,
  submitted_at: '',
}

test('unmarked answers remain unavailable, not wrong', () => {
  assert.equal(needsReview(answer), false)
  assert.equal(comprehensionText(answer), 'Classification unavailable')
})
test('wrong and partially understood answers offer source review', () => {
  for (const changed of [
    { is_correct: false },
    { label: 'partial' as const },
    { label: 'struggling' as const },
  ]) {
    assert.equal(needsReview({ ...answer, ...changed }), true)
  }
  assert.equal(
    needsReview({ ...answer, label: 'mastered', is_correct: true }),
    false,
  )
})
test('low confidence is uncertainty, not a definitive comprehension judgement', () => {
  assert.match(
    comprehensionText({ ...answer, label: 'struggling', confidence: 0.2 }),
    /Uncertain/,
  )
  assert.equal(
    comprehensionText({ ...answer, label: 'mastered', confidence: 0.9 }),
    'Mastered',
  )
})
test('MCQ correctness remains distinct from an unavailable AI label', () => {
  assert.equal(
    comprehensionText({ ...answer, is_correct: true }),
    'Correct answer',
  )
  assert.equal(
    comprehensionText({ ...answer, is_correct: false }),
    'Review this answer',
  )
})
test('errors explain authentication, authorization, pending integration and unavailable sessions', () => {
  assert.match(reviewError(401), /Sign in/)
  assert.match(reviewError(403), /consent/)
  assert.match(reviewError(404), /may not have ended/)
  assert.match(reviewError(501), /not available on this server/)
  assert.match(reviewError(500), /try again/)
})
