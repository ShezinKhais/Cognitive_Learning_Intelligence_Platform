import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'

import {
  historyViewState,
  nextHistoryAttempt,
} from '../src/features/review/engagementHistoryState.ts'

test('engagement history reports loading while no response is available', () => {
  assert.equal(
    historyViewState({ failed: false, history: null }),
    'loading',
  )
})

test('failed engagement history shows an error rather than indefinite loading', () => {
  assert.equal(
    historyViewState({ failed: true, history: null }),
    'error',
  )
  assert.equal(
    historyViewState({ failed: true, history: { classes: [] } }),
    'error',
  )
})

test('empty engagement history is distinct from a loaded class history', () => {
  assert.equal(
    historyViewState({ failed: false, history: { classes: [] } }),
    'empty',
  )
  assert.equal(
    historyViewState({
      failed: false,
      history: { classes: [{ session_id: 'session-1' }] },
    }),
    'ready',
  )
})

test('retry advances the request generation', () => {
  assert.equal(nextHistoryAttempt(0), 1)
  assert.equal(nextHistoryAttempt(1), 2)
})

test('engagement history renders a retry control for request failures', () => {
  const component = readFileSync(
    new URL('../src/features/review/EngagementHistory.tsx', import.meta.url),
    'utf8',
  )
  assert.match(component, /role="alert"/)
  assert.match(component, /onClick=\{retry\}/)
  assert.match(component, /Retry class history/)
  assert.match(component, /setAttempt\(nextHistoryAttempt\)/)
  assert.match(component, /\[attempt\]/)
})

test('Progress page defers engagement history until main reviews have loaded', () => {
  const page = readFileSync(
    new URL('../src/pages/StudentProgressPage.tsx', import.meta.url),
    'utf8',
  )
  assert.match(page, /\{reviews && <EngagementHistory \/>\}/)
})
