import assert from 'node:assert/strict'
import test from 'node:test'

import {
  chatReducer,
  initialChatState,
} from '../src/features/chat/chatState.ts'
import {
  parseChatStreamEvent,
  parseNdjsonLine,
} from '../src/features/chat/chatProtocol.ts'

function start(id = 'request-1') {
  return chatReducer(initialChatState, {
    type: 'submit-started',
    id,
    question: 'Help me understand recursion.',
  })
}

test('streams a grounded response with citations and follow-up prompts', () => {
  let state = start()

  for (const event of [
    { type: 'accepted' as const, request_id: 'request-1' },
    { type: 'delta' as const, request_id: 'request-1', text: 'What happens ' },
    { type: 'delta' as const, request_id: 'request-1', text: 'in the smaller case?' },
    {
      type: 'citation' as const,
      request_id: 'request-1',
      citation: {
        id: 'chunk-1',
        material_title: 'Week 4 slides',
        source_page: null,
        source_slide: 12,
        excerpt: 'A recursive function calls itself with a smaller input.',
      },
    },
    { type: 'follow_up' as const, request_id: 'request-1', prompt: 'What is the base case?' },
    { type: 'completed' as const, request_id: 'request-1' },
  ]) {
    state = chatReducer(state, { type: 'stream-event', event })
  }

  assert.equal(state.phase, 'completed')
  assert.equal(state.activeId, null)
  assert.equal(state.exchanges[0]?.answer, 'What happens in the smaller case?')
  assert.equal(state.exchanges[0]?.citations[0]?.source_slide, 12)
  assert.deepEqual(state.exchanges[0]?.followUps, ['What is the base case?'])
})

test('keeps partial text and labels a cancelled response incomplete', () => {
  let state = start()
  state = chatReducer(state, {
    type: 'stream-event',
    event: { type: 'delta', request_id: 'request-1', text: 'Start by considering' },
  })
  state = chatReducer(state, { type: 'cancel-started' })
  state = chatReducer(state, { type: 'cancelled-locally' })

  assert.equal(state.phase, 'cancelled')
  assert.equal(state.exchanges[0]?.answer, 'Start by considering')
  assert.equal(state.exchanges[0]?.phase, 'cancelled')
  assert.match(state.exchanges[0]?.explanation ?? '', /stopped/i)
})

test('represents unsupported and empty retrieval as distinct normal outcomes', () => {
  const unsupported = chatReducer(start(), {
    type: 'stream-event',
    event: {
      type: 'unsupported',
      request_id: 'request-1',
      reason: 'That request asks for a direct final answer.',
    },
  })
  const empty = chatReducer(start(), {
    type: 'stream-event',
    event: { type: 'empty_retrieval', request_id: 'request-1' },
  })

  assert.equal(unsupported.phase, 'unsupported')
  assert.match(unsupported.exchanges[0]?.explanation ?? '', /direct final answer/)
  assert.equal(empty.phase, 'empty-retrieval')
  assert.match(empty.exchanges[0]?.explanation ?? '', /lecture material/)
})

test('ignores stale events from an earlier request', () => {
  const state = chatReducer(start('current-request'), {
    type: 'stream-event',
    event: { type: 'delta', request_id: 'old-request', text: 'stale text' },
  })

  assert.equal(state.phase, 'submitting')
  assert.equal(state.exchanges[0]?.answer, '')
})

test('deduplicates citations and follow-up prompts replayed by the stream', () => {
  const citation = {
    id: 'chunk-1',
    material_title: 'Week 4 slides',
    source_page: 3,
    source_slide: null,
    excerpt: null,
  }
  let state = start()

  for (const event of [
    { type: 'citation' as const, request_id: 'request-1', citation },
    { type: 'citation' as const, request_id: 'request-1', citation },
    { type: 'follow_up' as const, request_id: 'request-1', prompt: 'Try an example' },
    { type: 'follow_up' as const, request_id: 'request-1', prompt: 'Try an example' },
  ]) {
    state = chatReducer(state, { type: 'stream-event', event })
  }

  assert.equal(state.exchanges[0]?.citations.length, 1)
  assert.equal(state.exchanges[0]?.followUps.length, 1)
})

test('validates newline-delimited stream events at the client boundary', () => {
  assert.deepEqual(
    parseNdjsonLine('{"type":"delta","request_id":"r1","text":"Hello"}'),
    { type: 'delta', request_id: 'r1', text: 'Hello' },
  )
  assert.equal(parseNdjsonLine('not json'), null)
  assert.equal(
    parseChatStreamEvent({
      type: 'citation',
      request_id: 'r1',
      citation: { id: 'missing-fields' },
    }),
    null,
  )
  assert.equal(
    parseChatStreamEvent({ type: 'unsupported', request_id: 'r1', reason: '' }),
    null,
  )
})

