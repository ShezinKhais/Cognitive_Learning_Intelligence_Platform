import assert from 'node:assert/strict'
import test from 'node:test'

import { initialLiveSessionState, liveSessionReducer, type LiveSessionAction } from '../src/features/student/liveSessionState.ts'

const question = {
  question_id: 'pending-answer', prompt: 'A checkpoint', options: ['First', 'Second'],
  closes_at: new Date(Date.now() + 60_000).toISOString(), window_seconds: 60, source_slide: 3,
}
const terminalEvents: LiveSessionAction[] = [
  { type: 'session-ended' },
  ...(['ended', 'cancelled'] as const).map(status => ({
    type: 'session-state' as const,
    payload: { session_id: 'session', status, paused: false, participant_count: 1,
      active_question_id: null, questions_delivered: 1 },
  })),
]

function answering() {
  return liveSessionReducer(initialLiveSessionState('active'), { type: 'question-delivered', payload: question })
}

for (const end of terminalEvents) {
  const label = end.type === 'session-ended' ? 'terminal socket close' : end.payload.status
  for (const phase of ['answering', 'submitting', 'unconfirmed', 'rejected'] as const) {
    test(`${label} closes a ${phase} checkpoint without claiming an unconfirmed answer was lost`, () => {
      let state = answering()
      state = { ...state, checkpoint: { ...state.checkpoint!, phase, selectedOption: 1 } }
      state = liveSessionReducer(state, end)
      assert.equal(state.checkpoint, null)
      assert.equal(state.completedCheckpoint?.phase,
        phase === 'answering' ? 'missed' : phase === 'submitting' ? 'unconfirmed' : phase)
      assert.equal(state.completedCheckpoint?.selectedOption, 1)
      assert.deepEqual(state.answeredIds, [])
      state = liveSessionReducer(state, { type: 'connection', status: 'connected' })
      assert.equal(state.checkpoint, null, 'reconnection cannot reopen the completed checkpoint')
    })
  }

  for (const accepted of [true, false]) {
    test(`${label} accepts a late ${accepted ? 'accepted' : 'rejected'} receipt without reopening the question`, () => {
      let state = liveSessionReducer(answering(), { type: 'answer-sent' })
      state = liveSessionReducer(state, end)
      state = liveSessionReducer(state, { type: 'answer-receipt', payload: {
        question_id: question.question_id, accepted, received_at: new Date().toISOString(),
        reason: accepted ? null : 'The session has ended.',
      } })
      assert.equal(state.checkpoint, null)
      assert.equal(state.completedCheckpoint?.phase, accepted ? 'submitted' : 'rejected')
      assert.deepEqual(state.answeredIds, accepted ? [question.question_id] : [])
    })
  }

  test(`${label} keeps late feedback and counts an answer even when its receipt was missed`, () => {
    let state = liveSessionReducer(answering(), { type: 'answer-sent' })
    state = liveSessionReducer(state, end)
    const feedback: LiveSessionAction = { type: 'feedback-result', payload: {
      question_id: question.question_id, correct: false, explanation: 'Revisit slide 3.', source_slide: 3,
    } }
    state = liveSessionReducer(state, feedback)
    state = liveSessionReducer(state, feedback)
    state = liveSessionReducer(state, { type: 'answer-receipt', payload: {
      question_id: question.question_id, accepted: false, received_at: new Date().toISOString(),
      reason: 'The session has ended.',
    } })
    assert.equal(state.checkpoint, null)
    assert.equal(state.completedCheckpoint?.phase, 'submitted')
    assert.equal(state.completedCheckpoint?.feedback?.explanation, 'Revisit slide 3.')
    assert.deepEqual(state.answeredIds, [question.question_id])
  })

  test(`${label} ignores delayed questions and attention prompts`, () => {
    let state = liveSessionReducer(initialLiveSessionState('active'), { type: 'attention-prompt', payload: {
      prompt_id: 'old-prompt', message: 'Are you here?', expires_at: new Date(Date.now() + 60_000).toISOString(), escalation: 1,
    } })
    state = liveSessionReducer(state, end)
    assert.equal(state.attentionPrompt, null)
    state = liveSessionReducer(state, { type: 'question-delivered', payload: question })
    state = liveSessionReducer(state, { type: 'attention-prompt', payload: {
      prompt_id: 'late-prompt', message: 'Are you here?', expires_at: new Date(Date.now() + 60_000).toISOString(), escalation: 1,
    } })
    assert.equal(state.checkpoint, null)
    assert.equal(state.attentionPrompt, null)
  })
}

test('the socket closing after cancellation preserves the cancelled outcome', () => {
  let state = initialLiveSessionState('cancelled')
  state = liveSessionReducer(state, { type: 'session-ended' })
  assert.equal(state.sessionStatus, 'cancelled')
})

test('feedback received before its receipt counts the answer once in a live session', () => {
  let state = liveSessionReducer(answering(), { type: 'answer-sent' })
  state = liveSessionReducer(state, { type: 'feedback-result', payload: {
    question_id: question.question_id, correct: true, explanation: null, source_slide: 3,
  } })
  state = liveSessionReducer(state, { type: 'answer-receipt', payload: {
    question_id: question.question_id, accepted: true, received_at: new Date().toISOString(), reason: null,
  } })
  assert.equal(state.completedCheckpoint?.phase, 'submitted')
  assert.deepEqual(state.answeredIds, [question.question_id])
})
