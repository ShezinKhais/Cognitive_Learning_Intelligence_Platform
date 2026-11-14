import assert from 'node:assert/strict'
import test from 'node:test'

import {
  falseAlarmRate, micBalancedAccuracy, micFramesToCsv, micWindows, parseMicCsv, scoreWindows, speechRecall,
  type MicFrame, type MicLabel,
} from '../eval/micEvaluation.ts'

const conditions = { microphone: 'built_in', room: 'quiet', distance: 'near', device: 'usual' }

/** A clip of `seconds` with one frame every 32 ms, all at `probability` unless `at` says otherwise. */
function clip(participant: string, name: string, label: MicLabel, seconds: number, probability: number | null, at: Record<number, number> = {}): MicFrame[] {
  const frames: MicFrame[] = []
  for (let i = 0; i * 0.032 < seconds; i++) {
    frames.push({ participant, clip: name, label, conditions, t: i * 0.032, probability: at[i] ?? probability })
  }
  return frames
}

test('a clip is cut into 5-second windows and one speech frame makes a window speaking', () => {
  // Frame 200 is at 6.4 s: the second window only.
  const windows = micWindows(clip('P1', 'c1', 'silent', 15, 0.1, { 200: 0.9 }))
  assert.deepEqual(windows.map(w => w.detected), [false, true, false])
  assert.ok(windows.every(w => w.expected === false))
})

test('a microphone that gives nothing has no reading, not silence', () => {
  const [window] = micWindows(clip('P1', 'c1', 'speaking', 5, null))
  assert.equal(window.detected, null)
  const score = scoreWindows([window])
  assert.equal(score.missing, 1)
  assert.equal(speechRecall(score), null)
})

test('speech caught, false alarms and balanced accuracy', () => {
  const windows = micWindows([
    ...clip('P1', 'c1', 'speaking', 10, 0.9),
    ...clip('P1', 'c2', 'speaking_quietly', 5, 0.3),
    ...clip('P1', 'c3', 'others_talking', 10, 0.8),
    ...clip('P1', 'c4', 'typing', 10, 0.1),
  ])
  const score = scoreWindows(windows)
  assert.equal(speechRecall(score), 2 / 3)
  assert.equal(falseAlarmRate(score), 2 / 4)
  assert.equal(micBalancedAccuracy(score), (2 / 3 + 1 / 2) / 2)
})

test('a short tail is dropped, as the classroom merges it with the next window', () => {
  assert.equal(micWindows(clip('P1', 'c1', 'silent', 11, 0.1)).length, 2)
})

test('recordings survive a round trip through CSV', () => {
  const frames = clip('P2', 'c1', 'noise', 0.1, 0.25, { 1: 0.75 }).concat(clip('P2', 'c2', 'speaking', 0.05, null))
  const back = parseMicCsv(micFramesToCsv(frames))
  assert.deepEqual(back.map(f => [f.label, f.probability]), frames.map(f => [f.label, f.probability]))
  assert.deepEqual(back[0].conditions, conditions)
  assert.throws(() => parseMicCsv('participant,clip,label\nP1,c1,shouting\n'), /unknown label/)
})
