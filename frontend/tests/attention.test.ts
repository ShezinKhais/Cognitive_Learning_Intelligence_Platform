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
  CALIBRATED_THRESHOLDS, DEFAULT_THRESHOLDS, calibrate, classifyFace, faceFeatures, poseFromMatrix, thresholdsFor, type FaceFeatures,
} from '../src/features/attention/signals.ts'
import {
  balancedAccuracy, bootstrap, calibrations, count, dropCountdown, framesToCsv, parseCsv, folds, observe, precision, recall, tune, type Frame,
} from '../eval/evaluation.ts'

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
  assert.equal(observeFace([face()], [rotation('x', 35)]).forward, false)
  assert.equal(observeFace([face()], [rotation('x', 35)]).head, 'turned')
  assert.equal(observeFace([face()], [rotation('y', 40)]).forward, false)
})

test('the thresholds are the ones tuned in CV_EVALUATION.md', () => {
  const limits = (t: typeof DEFAULT_THRESHOLDS) => ({ yaw: t.maxYawDegrees, pitch: t.maxPitchDegrees, roll: t.maxRollDegrees, irisX: t.irisX })
  assert.deepEqual(limits(DEFAULT_THRESHOLDS), { yaw: 10, pitch: 30, roll: 20, irisX: [0.2, 0.8] })
  assert.deepEqual(limits(CALIBRATED_THRESHOLDS), { yaw: 15, pitch: 16, roll: 15, irisX: [0.25, 0.75] })
  assert.equal(thresholdsFor(null), DEFAULT_THRESHOLDS)
  assert.equal(thresholdsFor({ yaw: 0, pitch: 0, roll: 0, irisX: 0.5, irisY: 0.5 }), CALIBRATED_THRESHOLDS)
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

test('a centre tilted up from a far or low camera is kept, one looking down at notes is not', () => {
  // Sitting back from the laptop read as about 30 degrees up in the #159 recordings.
  assert.ok(Math.abs(calibrate(Array.from({ length: 10 }, () => looking(-30)))!.pitch + 30) < 1e-6)
  assert.equal(calibrate(Array.from({ length: 10 }, () => looking(-40))), null)
  // Looking down at notes read 17 to 20 degrees down; past the limit it is refused.
  assert.equal(calibrate(Array.from({ length: 10 }, () => looking(25))), null)
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

test('every participant is held out once, and never tuned on in their own fold', () => {
  const frames = ['P1', 'P2', 'P3', 'P4', 'P5'].map(p => frame(p, 'c1', 'screen', 0))
  const { folds: rounds, by } = folds(frames)
  assert.equal(by, 'participant')
  assert.deepEqual(rounds.map(r => r.held), ['P1', 'P2', 'P3', 'P4', 'P5'])
  for (const { held, tune: tuned, test: tested } of rounds) {
    assert.deepEqual([...new Set(tested.map(f => f.participant))], [held])
    assert.ok(tuned.every(f => f.participant !== held))
  }
})

test('with fewer than three participants, clips are held out instead', () => {
  const frames = ['c1', 'c2', 'c3', 'c4', 'c5', 'c6'].map(c => frame('P1', c, 'screen', 0))
  const { folds: rounds, by } = folds(frames)
  assert.equal(by, 'clip')
  assert.equal(rounds.length, 1)
  assert.deepEqual(rounds[0].test.map(f => f.clip), ['c3', 'c6'])
  assert.ok(rounds[0].tune.every(f => !['c3', 'c6'].includes(f.clip)))
})

test('with calibration on, a person without a usable one is judged as the app does', () => {
  // Joel's case: 12 degrees of yaw passes the calibrated 15 but not the uncalibrated 10.
  const turned = { ...frame('P1', 'c2', 'screen', 0), features: faceFeatures([face()], [rotation('y', 12)]) }
  const setting = { thresholds: CALIBRATED_THRESHOLDS, calibrated: true, uncalibrated: DEFAULT_THRESHOLDS }
  // No calibrate clip, or one refused (40 degrees down): the uncalibrated limits apply.
  assert.equal(observe([turned], setting)[0].forward, false)
  const refused = Array.from({ length: 10 }, () => frame('P1', 'c1', 'calibrate', 40))
  assert.equal(observe([turned], setting, calibrations([...refused, turned]))[0].forward, false)
  // A usable calibration, straight ahead: the calibrated limits apply.
  const usable = Array.from({ length: 10 }, () => frame('P1', 'c1', 'calibrate', 0))
  assert.equal(observe([turned], setting, calibrations([...usable, turned]))[0].forward, true)
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

// -- #166: combined gaze and adaptive limits ------------------------------------

import {
  ADAPTATION, GAZE_MODEL, SUGGESTED_ADAPTATION, adaptedThresholds, classifyAdaptive, learn, startAdaptation,
  type AdaptiveState, type GazeModel,
} from '../src/features/attention/signals.ts'
import { GAZE_LABELS, lookingTruth, seeded, tuneGaze } from '../eval/evaluation.ts'

/** One valid face with the given head angles and iris position (both eyes alike unless `gapX`). */
function pose(yaw: number, pitch = 0, roll = 0, irisX = 0.5, irisY = 0.5, gapX = 0): FaceFeatures {
  const eye = (x: number) => ({ width: 0.1, open: 0.3, irisX: x, irisY })
  return {
    faces: 1, valid: true, width: 0.4, yawProxy: 0, rollProxy: 0,
    pose: { yaw, pitch, roll }, leftEye: eye(irisX + gapX / 2), rightEye: eye(irisX - gapX / 2),
  }
}
const GAZE: GazeModel = { kYaw: -100, kPitch: 0, maxEyeDisagreement: 0.15 }
const centre = { yaw: 0, pitch: 0, roll: 0, irisX: 0.5, irisY: 0.5 }

test('the combined gaze and adaptation stay off until recordings support them', () => {
  assert.equal(GAZE_MODEL, null)
  assert.equal(ADAPTATION, null)
})

test('with a gaze model, the eyes can rescue a turned head as well as veto a still one', () => {
  const t = CALIBRATED_THRESHOLDS
  // Head 20 degrees one way, eyes 0.2 the other: still looking at the screen.
  const compensating = pose(20, 0, 0, 0.7)
  assert.equal(classifyFace(compensating, t, centre).forward, false)
  assert.equal(classifyFace(compensating, t, centre, GAZE).forward, true)
  assert.equal(classifyFace(compensating, t, centre, GAZE).head, 'turned')
  // Head still, eyes to the side but inside the wide iris box: a glance away.
  const glance = pose(0, 0, 0, 0.7)
  assert.equal(classifyFace(glance, t, centre).forward, true)
  assert.equal(classifyFace(glance, t, centre, GAZE).forward, false)
  // Plain looking at the screen is unchanged, and closed eyes are still no reading.
  assert.equal(classifyFace(pose(0), t, centre, GAZE).forward, true)
  const closed = { ...pose(0), leftEye: { ...pose(0).leftEye!, open: 0 } }
  assert.equal(classifyFace(closed, t, centre, GAZE).forward, null)
})

test('eyes that point different ways give no reading, unless that is this student\'s own normal', () => {
  const t = CALIBRATED_THRESHOLDS
  const squint = pose(0, 0, 0, 0.5, 0.5, 0.3)
  assert.equal(classifyFace(squint, t, centre, GAZE).forward, null)
  // A calibration taken with the same gap reads the same eyes normally.
  const calibration = calibrate(Array.from({ length: 10 }, () => squint))!
  assert.ok(Math.abs(calibration.eyeGapX! - 0.3) < 1e-9)
  assert.equal(classifyFace(squint, t, calibration, GAZE).forward, true)
})

function learnAll(frames: FaceFeatures[], state: AdaptiveState = startAdaptation(null), base = DEFAULT_THRESHOLDS): AdaptiveState {
  for (const f of frames) state = learn(state, f, base, SUGGESTED_ADAPTATION)
  return state
}

test('learned limits are never stricter than the standard ones', () => {
  const random = seeded(7)
  for (const base of [DEFAULT_THRESHOLDS, CALIBRATED_THRESHOLDS]) {
    for (let run = 0; run < 50; run++) {
      const spread = random() * 30
      const frames = Array.from({ length: 80 }, () => pose((random() - 0.5) * spread, (random() - 0.5) * spread, (random() - 0.5) * spread))
      let state = startAdaptation(null)
      for (const f of frames) {
        state = learn(state, f, base, SUGGESTED_ADAPTATION)
        const { thresholds } = adaptedThresholds(state, base, SUGGESTED_ADAPTATION)
        assert.ok(thresholds.maxYawDegrees >= base.maxYawDegrees)
        assert.ok(thresholds.maxPitchDegrees >= base.maxPitchDegrees)
        assert.ok(thresholds.maxRollDegrees >= base.maxRollDegrees)
        // Nothing else about the judgement changes.
        assert.deepEqual(thresholds.irisX, base.irisX)
      }
    }
  }
})

test('a still student keeps the standard limits; one who moves a lot while looking gets wider ones', () => {
  const still = learnAll(Array.from({ length: 40 }, (_, i) => pose(i % 2 ? 1 : -1)))
  assert.equal(adaptedThresholds(still, DEFAULT_THRESHOLDS, SUGGESTED_ADAPTATION).thresholds.maxYawDegrees, DEFAULT_THRESHOLDS.maxYawDegrees)
  // Head yaw swinging about 6 degrees either way while looking (a tremor, say).
  const moving = learnAll(Array.from({ length: 60 }, (_, i) => pose(i % 2 ? 6 : -6)))
  const { thresholds, measurable } = adaptedThresholds(moving, DEFAULT_THRESHOLDS, SUGGESTED_ADAPTATION)
  assert.ok(measurable)
  assert.ok(thresholds.maxYawDegrees > 15 && thresholds.maxYawDegrees <= SUGGESTED_ADAPTATION.maxLimits.yaw)
  assert.equal(classifyFace(pose(13), DEFAULT_THRESHOLDS).forward, false)
  assert.equal(classifyAdaptive(pose(13), moving, DEFAULT_THRESHOLDS, SUGGESTED_ADAPTATION).forward, true)
  // Well beyond the student's own normal is still away.
  assert.equal(classifyAdaptive(pose(40), moving, DEFAULT_THRESHOLDS, SUGGESTED_ADAPTATION).forward, false)
})

test('until enough good frames, the standard limits apply', () => {
  const few = learnAll(Array.from({ length: SUGGESTED_ADAPTATION.minFrames - 1 }, (_, i) => pose(i % 2 ? 8 : -8)))
  assert.equal(adaptedThresholds(few, DEFAULT_THRESHOLDS, SUGGESTED_ADAPTATION).thresholds, DEFAULT_THRESHOLDS)
})

test('a normal wider than the camera can measure gives no reading, not "away"', () => {
  // Learned limits only widen up to the cap; this student needs more.
  const s = { ...SUGGESTED_ADAPTATION, maxLimits: { yaw: 12, pitch: 30, roll: 25 } }
  let state = startAdaptation(null)
  for (let i = 0; i < 60; i++) state = learn(state, pose(i % 2 ? 7 : -7), DEFAULT_THRESHOLDS, s)
  const { measurable } = adaptedThresholds(state, DEFAULT_THRESHOLDS, s)
  assert.equal(measurable, false)
  assert.equal(classifyAdaptive(pose(30), state, DEFAULT_THRESHOLDS, s).forward, null)
  assert.equal(classifyAdaptive(pose(0), state, DEFAULT_THRESHOLDS, s).forward, true)
})

test('the centre follows a slow drift but a long look away does not become normal', () => {
  // The laptop is moved: looking at the screen slowly goes from 0 to 8 degrees of yaw.
  const drift = learnAll(Array.from({ length: 400 }, (_, i) => pose(8 * Math.min(1, i / 200))))
  assert.ok(Math.abs(drift.centre.yaw - 8) < 1)
  // A minute looking far to the side during a good moment is skipped, frame by frame.
  const settled = learnAll(Array.from({ length: 40 }, () => pose(0)))
  const after = learnAll(Array.from({ length: 240 }, () => pose(40)), settled)
  assert.equal(after.centre.yaw, settled.centre.yaw)
  assert.equal(after.frames, settled.frames)
  // One odd frame moves the centre by at most the step limit.
  const odd = learn(settled, pose(12), DEFAULT_THRESHOLDS, SUGGESTED_ADAPTATION)
  assert.ok(Math.abs(odd.centre.yaw - settled.centre.yaw) <= SUGGESTED_ADAPTATION.maxCentreStepDegrees + 1e-9)
})

test('frames with no face, two faces or no pose teach nothing', () => {
  const state = startAdaptation(null)
  for (const f of [faceFeatures([]), faceFeatures([face(), face()]), faceFeatures([face()])]) {
    assert.equal(learn(state, f, DEFAULT_THRESHOLDS, SUGGESTED_ADAPTATION), state)
  }
})

function clip(participant: string, name: string, label: Frame['label'], features: FaceFeatures, n = 10): Frame[] {
  return Array.from({ length: n }, (_, i) => ({
    participant, clip: name, label, t: i / 4,
    conditions: { glasses: 'no', lighting: 'normal', position: 'centred', distance: 'near' },
    features,
  }))
}

test('the #166 labels round-trip and count as looking or away', () => {
  assert.deepEqual([...GAZE_LABELS], ['screen_head_turned', 'away_eyes_only'])
  assert.equal(lookingTruth('screen_head_turned'), true)
  assert.equal(lookingTruth('away_eyes_only'), false)
  const frames = [...clip('P1', 'c1', 'screen_head_turned', pose(20, 0, 0, 0.7), 1), ...clip('P1', 'c2', 'away_eyes_only', pose(0, 0, 0, 0.7), 1)]
  assert.deepEqual(parseCsv(framesToCsv(frames)).map(f => f.label), ['screen_head_turned', 'away_eyes_only'])
})

test('tuning the gaze model finds the k that tells a compensating head from an eye-only glance', () => {
  const frames = ['P1', 'P2', 'P3'].flatMap(p => [
    ...clip(p, 'c1', 'calibrate', pose(0)),
    ...clip(p, 'c2', 'screen_head_turned', pose(20, 0, 0, 0.7)),
    ...clip(p, 'c3', 'away_eyes_only', pose(0, 0, 0, 0.7)),
    ...clip(p, 'c4', 'screen', pose(0)),
  ])
  const { gaze, balancedAccuracy: value } = tuneGaze(frames, CALIBRATED_THRESHOLDS, DEFAULT_THRESHOLDS)
  assert.ok(gaze.kYaw < 0)
  assert.equal(value, 1)
})

test('in the evaluation, adaptation learns from calibrate clips only', () => {
  // Calibrate clips with lots of yaw movement; the scored clip is 13 degrees off.
  const calibrating = Array.from({ length: 40 }, (_, i) => ({ ...clip('P1', 'c1', 'calibrate', pose(i % 2 ? 6 : -6), 1)[0], t: i / 4 }))
  const scored = clip('P1', 'c2', 'screen', pose(13))
  const frames = [...calibrating, ...scored]
  const byKey = calibrations(frames)
  const fixed = observe(scored, { thresholds: DEFAULT_THRESHOLDS, calibrated: false }, byKey)
  const adapted = observe(scored, { thresholds: DEFAULT_THRESHOLDS, calibrated: false, adaptation: SUGGESTED_ADAPTATION }, byKey)
  assert.ok(fixed.every(s => s.forward === false))
  assert.ok(adapted.every(s => s.forward === true))
  // With no calibrate clips at all there is nothing to learn from.
  const none = observe(scored, { thresholds: DEFAULT_THRESHOLDS, calibrated: false, adaptation: SUGGESTED_ADAPTATION }, calibrations(scored))
  assert.ok(none.every(s => s.forward === false))
})
