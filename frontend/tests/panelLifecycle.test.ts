import assert from 'node:assert/strict'
import test from 'node:test'

import { initialLifecycle, lifecycleReducer, type LifecycleEvent } from '../src/features/live/panelLifecycle.ts'

function run(...events: LifecycleEvent[]) {
  return events.reduce(lifecycleReducer, initialLifecycle)
}

test('a successful pause shows Resume even when the socket never reports it', () => {
  const state = run(
    { type: 'socket', session: { status: 'active', paused: false } },
    // The socket drops here; the HTTP reply is all the panel hears.
    { type: 'action', session: { status: 'active', paused: true } },
  )
  assert.equal(state.status, 'active')
  assert.equal(state.paused, true)
})

test('start and end apply from the reply alone', () => {
  const started = run(
    { type: 'loaded', session: { status: 'prepared', paused: false } },
    { type: 'action', session: { status: 'active', paused: false } },
  )
  assert.equal(started.status, 'active')
  assert.equal(lifecycleReducer(started, { type: 'action', session: { status: 'ended', paused: false } }).status, 'ended')
})

test('a socket update after the action takes over again', () => {
  const state = run(
    { type: 'action', session: { status: 'active', paused: true } },
    { type: 'socket', session: { status: 'active', paused: false } },
  )
  assert.equal(state.paused, false)
})

test('a slow first load does not undo a newer report', () => {
  const state = run(
    { type: 'action', session: { status: 'active', paused: false } },
    { type: 'loaded', session: { status: 'prepared', paused: false } },
  )
  assert.equal(state.status, 'active')
})

test('the first load fills in before anything else reports', () => {
  const state = run({ type: 'loaded', session: { status: 'active', paused: true } })
  assert.deepEqual([state.status, state.paused], ['active', true])
})
