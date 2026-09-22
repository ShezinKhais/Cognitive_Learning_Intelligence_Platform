
import assert from 'node:assert/strict'
import test from 'node:test'

import {
  initialLiveSessionState,
  liveSessionReducer,
  remainingResponseSeconds,
} from '../src/features/student/liveSessionState.ts'
import {
  buildAuthPayload,
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
      paused: false,
    },
  })

  state = liveSessionReducer(state, {
    type: 'question-delivered',
    payload: question,
  })

  state = liveSessionReducer(state, {
    type: 'select-option',
    option: 1,
  })

  state = liveSessionReducer(state, {
    type: 'answer-sent',
  })

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

  assert.equal(state.checkpoint, null)
  assert.equal(state.completedCheckpoint?.phase, 'submitted')
  assert.equal(state.completedCheckpoint?.feedback?.correct, true)
  assert.equal(state.completedCheckpoint?.feedback?.source_slide, 4)
})

test('an unanswered checkpoint becomes missed when its window elapses', () => {
  let state = initialLiveSessionState('active')

  state = liveSessionReducer(state, {
    type: 'question-delivered',
    payload: question,
  })

  state = liveSessionReducer(state, {
    type: 'response-window-elapsed',
    questionId: 'question-1',
  })

  assert.equal(state.checkpoint, null)
  assert.equal(state.completedCheckpoint?.phase, 'missed')

  state = liveSessionReducer(state, {
    type: 'select-option',
    option: 0,
  })

  assert.equal(state.checkpoint, null)
})

test('a sent answer is not marked missed while its receipt is recovering', () => {
  let state = initialLiveSessionState('active')

  state = liveSessionReducer(state, {
    type: 'question-delivered',
    payload: question,
  })

  state = liveSessionReducer(state, {
    type: 'select-option',
    option: 0,
  })

  state = liveSessionReducer(state, {
    type: 'answer-sent',
  })

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

test('a replayed checkpoint preserves the student response and rejection state', () => {
  let state = initialLiveSessionState('active')

  state = liveSessionReducer(state, {
    type: 'question-delivered',
    payload: question,
  })

  state = liveSessionReducer(state, {
    type: 'select-option',
    option: 1,
  })

  state = liveSessionReducer(state, {
    type: 'answer-receipt',
    payload: {
      question_id: question.question_id,
      accepted: false,
      received_at: '2026-09-20T10:00:12.000Z',
      reason: 'retry',
    },
  })

  state = liveSessionReducer(state, {
    type: 'question-delivered',
    payload: {
      ...question,
      prompt: 'A replay must not replace this content.',
      closes_at: '2026-09-20T10:01:00.000Z',
    },
  })

  assert.equal(state.checkpoint?.selectedOption, 1)
  assert.equal(state.checkpoint?.phase, 'rejected')
  assert.equal(state.checkpoint?.receipt?.reason, 'retry')
  assert.equal(state.checkpoint?.question.prompt, question.prompt)
  assert.equal(
    state.checkpoint?.question.closes_at,
    '2026-09-20T10:01:00.000Z',
  )
})

test('a different checkpoint resets the previous answer state', () => {
  let state = initialLiveSessionState('active')

  state = liveSessionReducer(state, {
    type: 'question-delivered',
    payload: question,
  })

  state = liveSessionReducer(state, {
    type: 'select-option',
    option: 1,
  })

  state = liveSessionReducer(state, {
    type: 'question-delivered',
    payload: {
      ...question,
      question_id: 'question-2',
    },
  })

  assert.equal(
    state.checkpoint?.question.question_id,
    'question-2',
  )
  assert.equal(state.checkpoint?.selectedOption, null)
  assert.equal(state.checkpoint?.phase, 'answering')
})

test('a terminal reconnect marks the session ended without a forbidden state', () => {
  let state = initialLiveSessionState('active', true)

  state = liveSessionReducer(state, {
    type: 'question-delivered',
    payload: question,
  })

  state = liveSessionReducer(state, {
    type: 'session-ended',
  })

  assert.equal(state.connection, 'ended')
  assert.equal(state.sessionStatus, 'ended')
  assert.equal(state.paused, false)
  assert.equal(state.participantCount, 0)
  assert.equal(state.checkpoint, null)
  assert.equal(state.completedCheckpoint?.phase, 'missed')
})

test('a completed checkpoint stays closed when its delivery is replayed', () => {
  let state = initialLiveSessionState('active')

  state = liveSessionReducer(state, {
    type: 'question-delivered',
    payload: question,
  })

  state = liveSessionReducer(state, {
    type: 'response-window-elapsed',
    questionId: question.question_id,
  })

  state = liveSessionReducer(state, {
    type: 'question-delivered',
    payload: {
      ...question,
      closes_at: '2026-09-20T10:01:00.000Z',
    },
  })

  assert.equal(state.checkpoint, null)
  assert.equal(state.completedCheckpoint?.phase, 'missed')
  assert.equal(
    state.completedCheckpoint?.question.closes_at,
    '2026-09-20T10:01:00.000Z',
  )
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

test('the countdown is derived from the server close time and clamps at zero', () => {
  assert.equal(
    remainingResponseSeconds(
      '2026-09-20T10:00:30.000Z',
      Date.parse('2026-09-20T10:00:00.000Z'),
    ),
    30,
  )

  assert.equal(
    remainingResponseSeconds(
      '2026-09-20T10:00:30.000Z',
      Date.parse('2026-09-20T10:00:31.000Z'),
    ),
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

  assert.equal(
    parseLiveQuestion({
      ...question,
      window_seconds: -1,
    }),
    null,
  )

  assert.equal(
    parseServerEvent({
      type: 'question.delivered',
      seq: '7',
    }),
    null,
  )

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

  assert.deepEqual(
    parseSessionState({
      session_id: 'session-1',
      status: 'active',
      participant_count: 1,
      active_question_id: null,
      questions_delivered: 2,
      paused: true,
    }),
    {
      session_id: 'session-1',
      status: 'active',
      participant_count: 1,
      active_question_id: null,
      questions_delivered: 2,
      paused: true,
    },
  )

  assert.equal(
    parseSessionState({
      session_id: 'session-1',
      status: 'active',
      participant_count: 1,
      active_question_id: null,
      questions_delivered: 2,
      paused: 'yes',
    }),
    null,
  )
})

test('fresh authentication omits replay fields until a real cursor exists', () => {
  assert.deepEqual(
    buildAuthPayload(
      'token',
      'session-1',
      {
        lastSeq: null,
        streamId: null,
      },
    ),
    {
      token: 'token',
      session_id: 'session-1',
    },
  )

  assert.deepEqual(
    buildAuthPayload(
      'token',
      'session-1',
      {
        lastSeq: 12,
        streamId: 'stream-1',
      },
    ),
    {
      token: 'token',
      session_id: 'session-1',
      last_seq: 12,
      stream_id: 'stream-1',
    },
  )
})

// NEW TEST 1:
// If confirmation is missing, the answer must stop
// displaying the "submitting" status.

test('a missing receipt changes the answer to unconfirmed', () => {
  let state = initialLiveSessionState('active')

  state = liveSessionReducer(state, {
    type: 'question-delivered',
    payload: question,
  })

  state = liveSessionReducer(state, {
    type: 'select-option',
    option: 1,
  })

  state = liveSessionReducer(state, {
    type: 'answer-sent',
  })

  assert.equal(state.checkpoint?.phase, 'submitting')

  state = liveSessionReducer(state, {
    type: 'answer-confirmation-unknown',
    questionId: question.question_id,
  })

  assert.equal(state.checkpoint?.phase, 'unconfirmed')
  assert.equal(state.checkpoint?.selectedOption, 1)
})

// NEW TEST 2:
// If internet disconnects while an answer is submitting,
// the answer must become unconfirmed.

test('disconnecting while submitting preserves the answer', () => {
  let state = initialLiveSessionState('active')

  state = liveSessionReducer(state, {
    type: 'question-delivered',
    payload: question,
  })

  state = liveSessionReducer(state, {
    type: 'select-option',
    option: 1,
  })

  state = liveSessionReducer(state, {
    type: 'answer-sent',
  })

  state = liveSessionReducer(state, {
    type: 'connection',
    status: 'offline',
  })

  assert.equal(state.connection, 'offline')
  assert.equal(state.checkpoint?.phase, 'unconfirmed')
  assert.equal(state.checkpoint?.selectedOption, 1)
})

// NEW TEST 3:
// A confirmation that arrives later must still be accepted.

test('a late receipt confirms an unconfirmed answer', () => {
  let state = initialLiveSessionState('active')

  state = liveSessionReducer(state, {
    type: 'question-delivered',
    payload: question,
  })

  state = liveSessionReducer(state, {
    type: 'select-option',
    option: 1,
  })

  state = liveSessionReducer(state, {
    type: 'answer-sent',
  })

  state = liveSessionReducer(state, {
    type: 'answer-confirmation-unknown',
    questionId: question.question_id,
  })

  state = liveSessionReducer(state, {
    type: 'answer-receipt',
    payload: {
      question_id: question.question_id,
      accepted: true,
      received_at: '2026-09-20T10:00:12.000Z',
      reason: null,
    },
  })

  assert.equal(state.checkpoint, null)
  assert.equal(state.completedCheckpoint?.phase, 'submitted')
  assert.equal(state.completedCheckpoint?.selectedOption, 1)
})

// NEW TEST 4:
// A receipt for another question must not change
// the current student's answer.

test('a receipt for another question does not change the current answer', () => {
  let state = initialLiveSessionState('active')

  state = liveSessionReducer(state, {
    type: 'question-delivered',
    payload: question,
  })

  state = liveSessionReducer(state, {
    type: 'select-option',
    option: 1,
  })

  state = liveSessionReducer(state, {
    type: 'answer-sent',
  })

  state = liveSessionReducer(state, {
    type: 'answer-confirmation-unknown',
    questionId: question.question_id,
  })

  state = liveSessionReducer(state, {
    type: 'answer-receipt',
    payload: {
      question_id: 'a-different-question',
      accepted: true,
      received_at: '2026-09-20T10:00:12.000Z',
      reason: null,
    },
  })

  assert.equal(state.checkpoint?.phase, 'unconfirmed')
  assert.equal(state.checkpoint?.selectedOption, 1)
  assert.equal(state.completedCheckpoint, null)
})
