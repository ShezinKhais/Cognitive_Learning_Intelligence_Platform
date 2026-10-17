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

// -- #159: head pose, calibration and the evaluation ---------------------------

import {
  DEFAULT_THRESHOLDS, calibrate, classifyFace, faceFeatures, poseFromMatrix, type FaceFeatures,
} from '../src/features/attention/signals.ts'
import {
  balancedAccuracy, bootstrap, count, dropCountdown, framesToCsv, parseCsv, precision, recall, split, tune, type Frame,
} from '../src/features/attention/evaluation.ts'

/** A 4x4 column-major rotation about x (pitch) or y (yaw), in degrees. */
function rotation(axis: 'x' | 'y', degrees: number): number[] {
  const a = degrees * Math.PI / 180, c = Math.cos(a), s = Math.sin(a)
  const rows = axis === 'x'
    ? [[1, 0, 0, 0], [0, c, -s, 0], [0, s, c, 0], [0, 0, 0, 1]]
    : [[c, 0, s, 0], [0, 1, 0, 0], [-s, 0, c, 0], [0, 0, 0, 1]]
  return [0, 1, 2, 3].flatMap(column => rows.map(row => row[column]))
}

test('pose angles come from the transformation matrix', () => {
  const still = poseFromMatrix(rotation('x', 0))!
  assert.ok(Math.abs(still.yaw) < 1e-9 && Math.abs(still.pitch) < 1e-9 && Math.abs(still.roll) < 1e-9)
  assert.ok(Math.abs(poseFromMatrix(rotation('x', 30))!.pitch - 30) < 1e-6)
  assert.ok(Math.abs(poseFromMatrix(rotation('y', -40))!.yaw + 40) < 1e-6)
  assert.equal(poseFromMatrix([1, 2, 3]), null)
})

test('looking down at notes is not forward once a pose is known', () => {
  // The landmark proxies alone read this face as forward.
  assert.equal(observeFace([face()], [rotation('x', 0)]).forward, true)
  assert.equal(observeFace([face()], [rotation('x', 30)]).forward, false)
  assert.equal(observeFace([face()], [rotation('x', 30)]).head, 'turned')
  assert.equal(observeFace([face()], [rotation('y', 40)]).forward, false)
})

test('the starting thresholds are the ones written down', () => {
  assert.deepEqual(
    { yaw: DEFAULT_THRESHOLDS.maxYawDegrees, pitch: DEFAULT_THRESHOLDS.maxPitchDegrees, roll: DEFAULT_THRESHOLDS.maxRollDegrees },
    { yaw: 25, pitch: 20, roll: 20 },
  )
})

function looking(pitch: number, irisX = 0.5): FaceFeatures {
  const f = faceFeatures([face()], [rotation('x', pitch)])
  return { ...f, leftEye: { ...f.leftEye!, irisX }, rightEye: { ...f.rightEye!, irisX } }
}

test('a calibration moves the centre to where this student looks', () => {
  // A camera above the screen: looking at the screen reads as 15 degrees down.
  const frames = Array.from({ length: 10 }, () => looking(15))
  const calibration = calibrate(frames)!
  assert.ok(Math.abs(calibration.pitch - 15) < 1e-6)
  const strict = { ...DEFAULT_THRESHOLDS, maxPitchDegrees: 10 }
  assert.equal(classifyFace(looking(15), strict).forward, false)
  assert.equal(classifyFace(looking(15), strict, calibration).forward, true)
  assert.equal(classifyFace(looking(35), strict, calibration).forward, false)
})

test('too few frames, or a centre far off the screen, gives no calibration', () => {
  assert.equal(calibrate(Array.from({ length: 3 }, () => looking(0))), null)
  assert.equal(calibrate(Array.from({ length: 10 }, () => looking(40))), null)
  assert.equal(calibrate(Array.from({ length: 10 }, () => looking(0, 0.9))), null)
})

function frame(participant: string, clip: string, label: Frame['label'], pitch: number): Frame {
  return {
    participant, clip, label, t: 0,
    conditions: { glasses: 'no', lighting: 'normal', position: 'centred', distance: 'near' },
    features: looking(pitch),
  }
}

test('recordings round-trip through CSV with numbers only', () => {
  const frames = [frame('P1', 'c1', 'screen', 2), { ...frame('P1', 'c2', 'no_face', 0), features: faceFeatures([]) }]
  const csv = framesToCsv(frames)
  assert.ok(!/landmark|image|video/i.test(csv))
  const back = parseCsv(csv)
  assert.equal(back.length, 2)
  assert.equal(back[1].features.faces, 0)
  assert.ok(Math.abs(back[0].features.pose!.pitch - 2) < 1e-3)
  assert.deepEqual(classifyFace(back[0].features), classifyFace(frames[0].features))
})

test('countdown frames from older recordings are dropped where the clock restarts', () => {
  const at = (clip: string, t: number, label: 'screen' | 'away_left' = 'screen') => ({ ...frame('P1', clip, label, 0), t })
  // c1: two countdown frames, then the clip from t = 0. c2 was recorded after the fix.
  const frames = [at('c1', 0.1), at('c1', 1.9), at('c1', 0.1), at('c1', 5), at('c2', 0.2, 'away_left'), at('c2', 9)]
  assert.deepEqual(dropCountdown(frames).map(f => [f.clip, f.t]), [['c1', 0.1], ['c1', 5], ['c2', 0.2], ['c2', 9]])
  assert.equal(parseCsv(framesToCsv(frames)).length, 4)
})

test('counts keep frames with no reading apart', () => {
  const c = count([
    { truth: true, predicted: true }, { truth: true, predicted: false }, { truth: false, predicted: true },
    { truth: false, predicted: false }, { truth: true, predicted: null }, { truth: false, predicted: null },
  ])
  assert.deepEqual(c, { tp: 1, fp: 1, fn: 1, tn: 1, noReadingTrue: 1, noReadingFalse: 1 })
  assert.equal(precision(c), 0.5)
  assert.equal(recall(c), 0.5)
  // No reading counts as "not looking": 1 of 3 looking, 2 of 3 not looking.
  assert.equal(balancedAccuracy(c), (1 / 3 + 2 / 3) / 2)
})

test('the held-out split never tests on a participant it tuned on', () => {
  const frames = ['P1', 'P2', 'P3', 'P4', 'P5', 'P6'].map(p => frame(p, 'c1', 'screen', 0))
  const { tune: tuned, test: tested, by } = split(frames)
  assert.equal(by, 'participant')
  const overlap = tuned.filter(f => tested.some(g => g.participant === f.participant))
  assert.deepEqual(overlap, [])
  assert.deepEqual([...new Set(tested.map(f => f.participant))], ['P3', 'P6'])
})

test('tuning picks a pitch limit that separates the screen from the desk', () => {
  const frames = ['P1', 'P2'].flatMap(p => [
    ...Array.from({ length: 5 }, (_, i) => frame(p, 's', 'screen', i * 1.5)),
    ...Array.from({ length: 5 }, (_, i) => frame(p, 'd', 'down_notes', 18 + i)),
  ])
  const { thresholds, balancedAccuracy: best } = tune(frames, false)
  assert.equal(best, 1)
  // Above every screen pitch (0 to 6), at or below every desk pitch (18 to 22).
  assert.ok(thresholds.maxPitchDegrees > 6 && thresholds.maxPitchDegrees <= 18)
})

test('bootstrap intervals resample whole clips and repeat with the same seed', () => {
  const frames = ['c1', 'c2', 'c3', 'c4'].flatMap((clip, i) => [frame('P1', clip, 'screen', 0), frame('P1', clip, i % 2 ? 'screen' : 'down_notes', 30)])
  const metric = (sample: Frame[]) => sample.filter(f => f.label === 'down_notes').length / sample.length
  assert.deepEqual(bootstrap(frames, metric, 200, 7), bootstrap(frames, metric, 200, 7))
  assert.equal(bootstrap(frames.slice(0, 2), metric), null)
})
