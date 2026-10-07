import assert from 'node:assert/strict'
import test from 'node:test'

import {
  difficultyLabel,
  difficultyScoreLabel,
  recoveryMessage,
  type TopicDifficulty,
} from '../src/features/intelligence/topicRecovery.ts'

function topic(
  overrides: Partial<TopicDifficulty> = {},
): TopicDifficulty {
  return {
    topic: 'Neural Networks',
    questions: 3,
    answers: 12,
    mastered: 3,
    partial: 4,
    struggling: 5,
    uncertain: 2,
    score: 0.58,
    level: 'medium',
    expected: 'easy',
    ...overrides,
  }
}

test('topic difficulty labels preserve the AI 1 levels', () => {
  assert.equal(
    difficultyLabel('easy'),
    'Easy',
  )

  assert.equal(
    difficultyLabel('medium'),
    'Medium',
  )

  assert.equal(
    difficultyLabel('hard'),
    'Hard',
  )
})

test('missing topic difficulty does not invent a level', () => {
  assert.equal(
    difficultyLabel(null),
    'Not enough data',
  )
})

test('authoritative topic difficulty score is formatted without changing it', () => {
  assert.equal(
    difficultyScoreLabel(0.72),
    '0.72',
  )

  assert.equal(
    difficultyScoreLabel(0),
    '0.00',
  )

  assert.equal(
    difficultyScoreLabel(1),
    '1.00',
  )
})

test('invalid or missing topic difficulty score is unavailable', () => {
  assert.equal(
    difficultyScoreLabel(null),
    'Unavailable',
  )

  assert.equal(
    difficultyScoreLabel(-0.1),
    'Unavailable',
  )

  assert.equal(
    difficultyScoreLabel(1.1),
    'Unavailable',
  )

  assert.equal(
    difficultyScoreLabel(
      Number.NaN,
    ),
    'Unavailable',
  )
})

test('hard topics are prioritised for recovery', () => {
  assert.equal(
    recoveryMessage(
      topic({
        level: 'hard',
      }),
    ),
    'Prioritise this topic for review.',
  )
})

test('medium topics suggest clarification or follow-up', () => {
  assert.equal(
    recoveryMessage(
      topic({
        level: 'medium',
      }),
    ),
    'Consider a short clarification or follow-up activity.',
  )
})

test('easy topics do not invent a recovery requirement', () => {
  assert.equal(
    recoveryMessage(
      topic({
        level: 'easy',
      }),
    ),
    'No immediate recovery action is indicated.',
  )
})

test('topics without enough data do not receive a difficulty judgement', () => {
  assert.equal(
    recoveryMessage(
      topic({
        level: null,
        score: null,
        answers: 3,
      }),
    ),
    'More responses are needed before judging topic difficulty.',
  )
})