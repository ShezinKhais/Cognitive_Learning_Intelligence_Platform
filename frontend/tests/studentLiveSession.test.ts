import assert from 'node:assert/strict'
import test from 'node:test'

import {
  initialLiveSessionState,
  liveSessionReducer,
  remainingResponseSeconds,
} from '../src/features/student/liveSessionState.ts'
import {
  parseLiveQuestion,
  parseServerEvent,
  parseSessionState,
} from '../src/features/student/liveSessionProtocol.ts'

const question = {
  question_id: 'question-1',
  prompt: 'Which option is correct?',
  options: ['First', 'Second'],
  closes_at: '2026-09-20T10:00:30.000Z',
  window_seconds: 30,
  source_slide: 4,
}

test('a student can receive, answer and get feedback for a checkpoint', () => {
  let state = initialLiveSessionState('prepared')

  state = liveSessionReducer(state, {
    type: 'session-state',
    payload: {
      session_id: 'session-1',
      status: 'active',
      participant_count: 24,
      active_question_id: null,
      questions_delivered: 0,
    },
  })
  state = liveSessionReducer(state, {
    type: 'question-delivered',
    payload: question,
  })
  state = liveSessionReducer(state, { type: 'select-option', option: 1 })
  state = liveSessionReducer(state, { type: 'answer-sent' })

  assert.equal(state.sessionStatus, 'active')
  assert.equal(state.participantCount, 24)
  assert.equal(state.checkpoint?.selectedOption, 1)
  assert.equal(state.checkpoint?.phase, 'submitting')

  state = liveSessionReducer(state, {
    type: 'answer-receipt',
    payload: {
      question_id: 'question-1',
      accepted: true,
      received_at: '2026-09-20T10:00:12.000Z',
      reason: null,
    },
  })
  state = liveSessionReducer(state, {
    type: 'feedback-result',
    payload: {
      question_id: 'question-1',
      correct: true,
      explanation: 'The second option matches the source material.',
      source_slide: 4,
    },
  })

  assert.equal(state.checkpoint?.phase, 'submitted')
  assert.equal(state.checkpoint?.feedback?.correct, true)
  assert.equal(state.checkpoint?.feedback?.source_slide, 4)
})

test('an unanswered checkpoint becomes missed when its window elapses', () => {
  let state = initialLiveSessionState('active')
  state = liveSessionReducer(state, { type: 'question-delivered', payload: question })
  state = liveSessionReducer(state, {
    type: 'response-window-elapsed',
    questionId: 'question-1',
  })

  assert.equal(state.checkpoint?.phase, 'missed')

  state = liveSessionReducer(state, { type: 'select-option', option: 0 })
  assert.equal(state.checkpoint?.selectedOption, null)
})

test('a sent answer is not marked missed while its receipt is recovering', () => {
  let state = initialLiveSessionState('active')
  state = liveSessionReducer(state, { type: 'question-delivered', payload: question })
  state = liveSessionReducer(state, { type: 'select-option', option: 0 })
  state = liveSessionReducer(state, { type: 'answer-sent' })
  state = liveSessionReducer(state, {
    type: 'question-closed',
    payload: {
      question_id: 'question-1',
      reason: 'window_elapsed',
      respondents: 20,
      eligible: 24,
    },
  })

  assert.equal(state.checkpoint?.phase, 'submitting')
  assert.equal(state.checkpoint?.closed?.reason, 'window_elapsed')
})

test('a private attention prompt clears only when its matching id is acknowledged', () => {
  let state = initialLiveSessionState('active')
  state = liveSessionReducer(state, {
    type: 'attention-prompt',
    payload: {
      prompt_id: 'prompt-1',
      message: 'Tap to confirm you are following.',
      expires_at: '2026-09-20T10:01:00.000Z',
      escalation: 1,
    },
  })
  state = liveSessionReducer(state, {
    type: 'attention-prompt-cleared',
    promptId: 'another-prompt',
  })
  assert.equal(state.attentionPrompt?.prompt_id, 'prompt-1')

  state = liveSessionReducer(state, {
    type: 'attention-prompt-cleared',
    promptId: 'prompt-1',
  })
  assert.equal(state.attentionPrompt, null)
})

test('an ended session clears the live participant count', () => {
  let state = initialLiveSessionState('active')

  state = liveSessionReducer(state, {
    type: 'session-state',
    payload: {
      session_id: 'session-1',
      status: 'active',
      participant_count: 1,
      active_question_id: null,
      questions_delivered: 1,
    },
  })

  assert.equal(state.participantCount, 1)

  state = liveSessionReducer(state, {
    type: 'session-state',
    payload: {
      session_id: 'session-1',
      status: 'ended',
      participant_count: 1,
      active_question_id: null,
      questions_delivered: 1,
    },
  })

  assert.equal(state.sessionStatus, 'ended')
  assert.equal(state.participantCount, 0)
})

test('the countdown is derived from the server close time and clamps at zero', () => {
  assert.equal(
    remainingResponseSeconds('2026-09-20T10:00:30.000Z', Date.parse('2026-09-20T10:00:00.000Z')),
    30,
  )
  assert.equal(
    remainingResponseSeconds('2026-09-20T10:00:30.000Z', Date.parse('2026-09-20T10:00:31.000Z')),
    0,
  )
})
test('protocol guards accept the frozen event shapes and reject malformed payloads', () => {
  assert.deepEqual(
    parseServerEvent({
      type: 'question.delivered',
      seq: 7,
      ts: '2026-09-20T10:00:00.000Z',
      data: question,
    }),
    {
      type: 'question.delivered',
      seq: 7,
      ts: '2026-09-20T10:00:00.000Z',
      data: question,
    },
  )
  assert.deepEqual(parseLiveQuestion(question), question)
  assert.equal(parseLiveQuestion({ ...question, window_seconds: -1 }), null)
  assert.equal(parseServerEvent({ type: 'question.delivered', seq: '7' }), null)
  assert.equal(
    parseSessionState({
      session_id: 'session-1',
      status: 'unknown',
      participant_count: 1,
      active_question_id: null,
      questions_delivered: 0,
    }),
    null,
  )
})
