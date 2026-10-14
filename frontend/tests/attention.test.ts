import { test } from 'node:test'
import assert from 'node:assert/strict'
import { coveredWindowSeconds, observeFace, summary } from '../src/features/attention/signals.ts'

function face() {
  const p = Array.from({ length: 478 }, () => ({ x: .5, y: .5, z: 0 }))
  for (const [id, x, y] of [[33,.3,.4],[133,.4,.4],[263,.7,.4],[362,.6,.4],[159,.35,.38],[145,.35,.42],[386,.65,.38],[374,.65,.42],[468,.35,.4],[473,.65,.4]]) p[id] = { x, y, z: 0 }
  return p
}
test('single neutral face yields coarse camera-facing observation', () => {
  assert.deepEqual(observeFace([face()]), { face: true, head: 'forward', forward: true })
})
test('missing, malformed and multiple faces preserve unavailable gaze', () => {
  assert.deepEqual(observeFace([]), { face: false, head: 'unavailable', forward: null })
  assert.equal(observeFace([face(), face()]).face, null)
  assert.equal(observeFace([[]]).forward, null)
  const p = face(); p[1].x = NaN
  assert.equal(observeFace([p]).face, null)
})
test('turned head and off-centre iris are negative proxies, closed eyes unavailable', () => {
  const p = face(); p[1].x = .65
  assert.equal(observeFace([p]).head, 'turned')
  assert.equal(observeFace([p]).forward, false)
  const q = face(); q[468].x = .305
  assert.equal(observeFace([q]).forward, false)
  q[145].y = q[159].y
  assert.equal(observeFace([q]).forward, null)
})
test('summary omits raw data and does not turn missing readings into negatives', () => {
  assert.deepEqual(summary([], [], 5), { gaze_on_screen_ratio: null, face_present: null, speaking: null, window_seconds: 5 })
  assert.deepEqual(summary([
    { face: true, forward: true, head: 'forward' },
    { face: true, forward: false, head: 'turned' },
    { face: false, forward: null, head: 'unavailable' },
  ], [false, true], 5), { gaze_on_screen_ratio: .5, face_present: true, speaking: true, window_seconds: 5 })
  assert.equal(summary([], [false], 5).speaking, false)
  assert.equal(summary([], [], 99999).window_seconds, 3600)
})

test('stale sensor samples are unavailable rather than negative', () => {
  const observed = { face: true, forward: true, head: 'forward' } as const
  assert.deepEqual(summary([observed], [false], 5, { now: 5000, faceAt: 2999, speechAt: 4000 }), {
    gaze_on_screen_ratio: null,
    face_present: null,
    speaking: false,
    window_seconds: 5,
  })
})

test('the first summary covers only time since local sensing began', () => {
  assert.equal(coveredWindowSeconds(605000, 600000, [604900]), 0.1)
  assert.equal(coveredWindowSeconds(610000, 605000, [604900]), 5)
})
