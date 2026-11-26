import assert from 'node:assert/strict'
import test from 'node:test'

import {
  chatReducer,
  initialChatState,
  historyFor,
} from '../src/features/chat/chatState.ts'
import type { ChatExchange } from '../src/features/chat/chatTypes.ts'

function saved(id: string): ChatExchange {
  return {
    id,
    question: `Question ${id}`,
    answer: `Answer ${id}`,
    phase: 'completed',
    citations: [],
    followUps: [],
    explanation: null,
  }
}

test('restores earlier exchanges in chronological order', () => {
  const state = chatReducer(initialChatState, {
    type: 'history-loaded',
    exchanges: [saved('first'), saved('second')],
  })
  assert.deepEqual(state.exchanges.map((item) => item.id), ['first', 'second'])
  assert.deepEqual(historyFor(state.exchanges).map((item) => item.question), [
    'Question first',
    'Question second',
  ])
})

test('history load does not erase an active stream or draft', () => {
  let state = chatReducer(initialChatState, {
    type: 'submit-started',
    id: 'current',
    question: 'New question',
  })
  state = chatReducer(state, { type: 'draft-changed', value: 'A draft' })
  state = chatReducer(state, {
    type: 'history-loaded',
    exchanges: [saved('earlier')],
  })

  assert.deepEqual(state.exchanges.map((item) => item.id), [
    'earlier',
    'current',
  ])
  assert.equal(state.activeId, 'current')
  assert.equal(state.draft, 'A draft')
})

test('repeated restoration does not duplicate existing exchanges', () => {
  let state = chatReducer(initialChatState, {
    type: 'history-loaded',
    exchanges: [saved('one')],
  })
  state = chatReducer(state, {
    type: 'history-loaded',
    exchanges: [saved('one')],
  })
  assert.equal(state.exchanges.length, 1)
})

test('changing classes resets exchanges and draft', () => {
  let state = chatReducer(initialChatState, {
    type: 'history-loaded',
    exchanges: [saved('previous-class')],
  })
  state = chatReducer(state, {
    type: 'draft-changed',
    value: 'Old draft',
  })
  state = chatReducer(state, { type: 'history-reset' })
  assert.deepEqual(state, initialChatState)
})
