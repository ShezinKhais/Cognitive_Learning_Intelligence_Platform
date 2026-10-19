import { test } from 'node:test'
import assert from 'node:assert/strict'
import {
  awayDurationSeconds,
  nextAwayStart,
} from '../src/features/attention/awayDuration.ts'

test('looking away starts and continues a local timer', () => {
  const start = nextAwayStart(null, false, 1000)
  assert.equal(start, 1000)
  assert.equal(nextAwayStart(start, false, 2500), 1000)
  assert.equal(awayDurationSeconds(start, 4500), 3)
})

test('camera-facing observations reset the timer', () => {
  assert.equal(nextAwayStart(1000, true, 3000), 0)
  assert.equal(awayDurationSeconds(0, 4000), 0)
})

test('unavailable observations never count as looking away', () => {
  assert.equal(nextAwayStart(1000, null, 3000), null)
  assert.equal(nextAwayStart(null, null, 4000), null)
})

test('the timer never displays negative or invalid durations', () => {
  assert.equal(awayDurationSeconds(3000, 2000), 0)
  assert.equal(awayDurationSeconds(1000, Number.NaN), null)
  assert.equal(nextAwayStart(null, false, Number.NaN), null)
})
