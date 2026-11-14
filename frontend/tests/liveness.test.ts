// #165: anti-spoofing. The vote, the crop and the model input are plain
// functions, tested here; the model file itself is checked to load and answer.
import { test } from 'node:test'
import assert from 'node:assert/strict'
import { createHash } from 'node:crypto'
import { readFile } from 'node:fs/promises'
import {
  LIVENESS, MODEL_INPUT, SUGGESTED_LIVENESS, applyLiveness, cropBox, dueForCheck, faceBox, forCalibration, isSpoof, livenessFrame,
  loadInBackground, mayLearn, noteFrame, recordCheck, startLiveness, wantsLivenessModel,
  type LiveCheck, type LivenessSettings, type LivenessState,
} from '../src/features/attention/liveness.ts'
import {
  falseRejection, framesToCsv, livenessCounts, parseCsv, replayLiveness, spoofCatch, tuneLiveness, type Frame, type Label,
} from '../eval/evaluation.ts'
import { faceFeatures } from '../src/features/attention/signals.ts'

const s: LivenessSettings = { everyMs: 1000, window: 3, spoofBelow: 0.2 }

/** One frame with one face (or none), at `ms`, scored `live` if due. */
function step(state: LivenessState, ms: number, live: number, faces = 1): LivenessState {
  state = noteFrame(state, faces, ms, s)
  return faces === 1 && dueForCheck(state, ms, s) ? recordCheck(state, live, ms, s) : state
}

test('on, with the settings tuned on the recordings (#165, #253)', () => {
  assert.deepEqual(LIVENESS, { everyMs: 1000, window: 2, spoofBelow: 0.5 })
  assert.equal(wantsLivenessModel(LIVENESS, false), true, 'the classroom loads the model')
})

test('a face is rejected only when every check in a full window says not live', () => {
  let state = startLiveness()
  state = step(state, 0, 0.01)
  state = step(state, 1000, 0.01)
  assert.equal(isSpoof(state, s), false, 'two checks are not a full window')
  state = step(state, 2000, 0.01)
  assert.equal(isSpoof(state, s), true)
  // One live-looking check is enough to give the benefit of the doubt.
  state = step(state, 3000, 0.9)
  assert.equal(isSpoof(state, s), false)
})

test('checks run only every everyMs, not on every frame', () => {
  let state = startLiveness()
  for (let ms = 0; ms < 1000; ms += 250) state = step(state, ms, 0.01)
  assert.equal(state.scores.length, 1)
})

test('a face leaving, a second face or a long gap starts the vote again', () => {
  const spoofed = () => [0, 1000, 2000].reduce((st, ms) => step(st, ms, 0.01), startLiveness())
  assert.equal(isSpoof(spoofed(), s), true)
  assert.equal(isSpoof(noteFrame(spoofed(), 0, 2250, s), s), false, 'no face')
  assert.equal(isSpoof(noteFrame(spoofed(), 2, 2250, s), s), false, 'two faces')
  assert.equal(isSpoof(noteFrame(spoofed(), 1, 2000 + 3001, s), s), false, 'camera stalled')
})

test('a broken model reading never counts towards rejecting', () => {
  let state = startLiveness()
  for (const ms of [0, 1000, 2000, 3000]) state = step(state, ms, Number.NaN)
  assert.equal(state.scores.length, 0)
  assert.equal(isSpoof(state, s), false)
})

test('a rejected face becomes no face with no gaze reading; a live one is unchanged', () => {
  const seen = { face: true, forward: true, head: 'forward' } as const
  assert.deepEqual(applyLiveness(seen, true), { face: false, forward: null, head: 'unavailable' })
  assert.deepEqual(applyLiveness(seen, false), seen)
})

test('face box from landmarks, in pixels', () => {
  assert.deepEqual(faceBox([{ x: 0.25, y: 0.5 }, { x: 0.75, y: 0.75 }], 320, 240), { x: 80, y: 120, width: 160, height: 60 })
  assert.equal(faceBox([], 320, 240), null)
  assert.equal(faceBox([{ x: 0.5, y: 0.5 }], 320, 240), null, 'a single point is not a face')
})

test('crop is 2.7x the face, centred, and slid back inside the image (as in the model source)', () => {
  // Small face in the middle: grows to 2.7x around its centre.
  assert.deepEqual(cropBox({ x: 150, y: 110, width: 20, height: 20 }, 320, 240), { x: 133, y: 93, width: 55, height: 55 })
  // Near the left edge: slid right so it starts at 0.
  assert.deepEqual(cropBox({ x: 0, y: 100, width: 40, height: 40 }, 320, 240), { x: 0, y: 66, width: 109, height: 109 })
  // A big face: the scale shrinks so the crop fits the image height.
  const big = cropBox({ x: 100, y: 40, width: 120, height: 160 }, 320, 240)
  assert.ok(big.height <= 240 && big.y >= 0 && big.x >= 0 && big.x + big.width <= 320)
})

test('MODEL_INPUT makes ONNX Runtime give BGR planes, 0 to 255, not divided', async () => {
  // Tensor.fromImage is what the worker calls. Node has no ImageBitmap or
  // canvas, so minimal stand-ins hand it known pixels; the conversion itself
  // is ONNX Runtime's own code.
  const g = globalThis as Record<string, unknown>
  const saved = { ImageBitmap: g.ImageBitmap, OffscreenCanvas: g.OffscreenCanvas }
  const rgba = new Uint8ClampedArray(2 * 2 * 4)
  rgba.set([10, 20, 30, 255], 0) // first pixel: red 10, green 20, blue 30
  rgba.set([200, 100, 50, 255], 4)
  class FakeBitmap { width = 2; height = 2 }
  class FakeCanvas {
    width = 1; height = 1
    getContext() { return { drawImage() {}, getImageData: () => ({ data: rgba }) } }
  }
  g.ImageBitmap = FakeBitmap
  g.OffscreenCanvas = FakeCanvas
  try {
    const ort = await import('onnxruntime-web/wasm')
    const tensor = await ort.Tensor.fromImage(new FakeBitmap() as unknown as ImageBitmap, MODEL_INPUT)
    assert.deepEqual(tensor.dims, [1, 3, 2, 2])
    const data = [...(tensor.data as Float32Array)]
    // Blue plane first, then green, then red; raw 0-255 values.
    assert.deepEqual([data[0], data[4], data[8]], [30, 20, 10])
    assert.deepEqual([data[1], data[5], data[9]], [50, 100, 200])
  } finally {
    g.ImageBitmap = saved.ImageBitmap
    g.OffscreenCanvas = saved.OffscreenCanvas
  }
})

// -- the worker's paths: off by default, and falling back when the model fails --

const seen = { face: true, forward: true, head: 'forward' } as const
const lowCheck = async (): Promise<LiveCheck> => ({ live: 0.01, ms: 3 })

test('with LIVENESS off, the worker does not load the model and judges faces as before', async () => {
  assert.equal(wantsLivenessModel(null, false), false, 'classroom: no import, no download')
  assert.equal(wantsLivenessModel(null, true), true, 'the recorder still asks for scores')
  let calls = 0
  const check = async () => { calls += 1; return { live: 0.01, ms: 3 } }
  let state = startLiveness()
  for (let ms = 0; ms < 10_000; ms += 250) {
    const step = await livenessFrame(state, 1, ms, null, check)
    state = step.state
    assert.equal(step.spoof, false)
    assert.deepEqual(applyLiveness(seen, step.spoof), seen)
  }
  assert.equal(calls, 0, 'no check runs while off, even with a model')
})

test('with LIVENESS off, the recorder still gets a score on every frame but nothing is rejected', async () => {
  const step = await livenessFrame(startLiveness(), 1, 0, null, lowCheck, true)
  assert.deepEqual(step.live, { live: 0.01, ms: 3 })
  assert.equal(step.spoof, false)
})

test('a model that fails or hangs while loading leaves the camera without it, not stuck', async () => {
  assert.equal(await loadInBackground(() => Promise.reject(new Error('404'))), null)
  assert.equal(await loadInBackground(() => new Promise(() => {}), 20), null, 'hung load gives up')
  assert.equal(await loadInBackground(async () => 'model', 1000), 'model')
})

test('with no model loaded, LIVENESS on still never rejects a face', async () => {
  let state = startLiveness()
  for (let ms = 0; ms < 10_000; ms += 250) {
    const step = await livenessFrame(state, 1, ms, s, null)
    state = step.state
    assert.equal(step.spoof, false)
  }
})

test('a check that throws gives no score and never counts towards rejecting', async () => {
  let state = startLiveness()
  for (let ms = 0; ms < 10_000; ms += 250) {
    const step = await livenessFrame(state, 1, ms, s, () => Promise.reject(new Error('session lost')))
    state = step.state
    assert.equal(step.live, null)
    assert.equal(step.spoof, false)
    assert.deepEqual(applyLiveness(seen, step.spoof), seen)
  }
})

test('a face judged spoofed is kept out of calibration (and so out of the adaptation it seeds)', async () => {
  let state = startLiveness()
  let spoof = false
  let frames: string[] = []
  // A photo already rejected when calibration starts: none of its frames count.
  for (const ms of [0, 1000, 2000]) ({ state, spoof } = await livenessFrame(state, 1, ms, s, lowCheck))
  for (let ms = 2250; ms < 5250; ms += 250) {
    ;({ state, spoof } = await livenessFrame(state, 1, ms, s, lowCheck))
    frames = forCalibration(frames, `photo@${ms}`, spoof)
  }
  assert.deepEqual(frames, [])
  // A live face calibrates as before.
  frames = []
  state = startLiveness()
  for (let ms = 0; ms < 3000; ms += 250) {
    ;({ state, spoof } = await livenessFrame(state, 1, ms, s, async () => ({ live: 0.95, ms: 3 })))
    frames = forCalibration(frames, `face@${ms}`, spoof)
  }
  assert.equal(frames.length, 12)
})

test('with LIVENESS on, the same steps reject a photo, and adaptation learns nothing from it', async () => {
  let state = startLiveness()
  let spoof = false
  for (const ms of [0, 1000, 2000]) ({ state, spoof } = await livenessFrame(state, 1, ms, s, lowCheck))
  assert.equal(spoof, true)
  assert.deepEqual(applyLiveness(seen, spoof), { face: false, forward: null, head: 'unavailable' })
  assert.equal(mayLearn(true, false, 0, 1000), false, 'rejected face')
  assert.equal(mayLearn(false, true, 0, 1000), false, 'calibrating')
  assert.equal(mayLearn(false, false, 2000, 1000), false, 'no good moment')
  assert.equal(mayLearn(false, false, 0, 1000), true)
})

// -- evaluation -------------------------------------------------------------------

const oneFace = faceFeatures([Array.from({ length: 478 }, (_, i) => ({ x: 0.3 + (i % 10) * 0.04, y: 0.3 + (i % 7) * 0.05, z: 0 }))])
function clip(participant: string, id: string, label: Label, lives: number[]): Frame[] {
  return lives.map((live, i) => ({
    participant, clip: id, label, t: i * 0.25, live, liveMs: 3,
    conditions: { glasses: 'no', lighting: 'normal', position: 'centred', distance: 'near' },
    features: oneFace,
  }))
}

test('the evaluation replays the same vote as the browser', () => {
  const frames = clip('P1', 'c1', 'photo_on_phone', Array(40).fill(0.01))
  const rejected = replayLiveness(frames, s)
  // Checks at 0 s, 1 s and 2 s: rejected from the third check (frame 8) on.
  assert.equal(rejected.indexOf(true), 8)
  assert.ok(rejected.slice(8).every(Boolean))
})

test('counts spoofs caught and live faces wrongly rejected, per frame and per clip', () => {
  const frames = [
    ...clip('P1', 'c1', 'screen', Array(40).fill(0.9)),
    ...clip('P1', 'c2', 'screen', Array(40).fill(0.05)), // a live face the model dislikes
    ...clip('P1', 'c3', 'printed_photo', Array(40).fill(0.05)),
  ]
  const c = livenessCounts(frames, s)
  assert.equal(c.liveFrames, 80)
  assert.equal(c.liveRejected, 32)
  assert.equal(c.spoofCaught, 32)
  assert.equal(c.liveClips, 2)
  assert.equal(c.liveClipsRejected, 1)
  assert.equal(falseRejection(c), 0.4)
  assert.equal(spoofCatch(c), 0.8)
})

test('tuning never trades real students for spoofs', () => {
  // Live faces score 0.15 to 0.9; photos 0.02. Only a threshold under 0.15 keeps students safe.
  const frames = [
    ...clip('P1', 'c1', 'screen', Array(40).fill(0.15)),
    ...clip('P1', 'c2', 'screen', Array(40).fill(0.9)),
    ...clip('P1', 'c3', 'photo_on_phone', Array(40).fill(0.02)),
  ]
  const tuned = tuneLiveness(frames)
  assert.equal(tuned.meetsBar, true)
  assert.ok(tuned.settings.spoofBelow <= 0.15)
  assert.equal(falseRejection(tuned.counts), 0)
  assert.ok((spoofCatch(tuned.counts) ?? 0) > 0.5)
})

test('live scores survive the CSV round trip; old files without them still parse', () => {
  const frames = clip('P1', 'c1', 'video_on_phone', [0.25, 0.5])
  const back = parseCsv(framesToCsv(frames))
  assert.deepEqual(back.map(f => [f.label, f.live, f.liveMs]), [['video_on_phone', 0.25, 3], ['video_on_phone', 0.5, 3]])
  const old = framesToCsv(frames).split('\n').map(line => line.split(',').slice(0, -2).join(',')).join('\n')
  assert.deepEqual(parseCsv(old).map(f => f.live), [null, null])
})

test('suggested settings are cautious: several checks, low threshold', () => {
  assert.ok(SUGGESTED_LIVENESS.window >= 3)
  assert.ok(SUGGESTED_LIVENESS.spoofBelow <= 0.3)
})

// -- the model file ---------------------------------------------------------------

const modelPath = new URL('../attention-models/minifasnet_v2_80x80.onnx', import.meta.url)

test('the committed model matches its pinned checksum', async () => {
  const data = await readFile(modelPath)
  assert.equal(createHash('sha256').update(data).digest('hex'), '9c6b11e41aa610366c9becdebaf93f10beaf53c1be34a613c32763707b9a6fe3')
  const prepare = await readFile(new URL('../scripts/prepare-attention.mjs', import.meta.url), 'utf8')
  assert.ok(prepare.includes('9c6b11e41aa610366c9becdebaf93f10beaf53c1be34a613c32763707b9a6fe3'), 'build checks the same checksum')
})

test('the model loads and gives three probabilities for an 80x80 crop', async () => {
  const ort = await import('onnxruntime-web/wasm')
  ort.env.wasm.numThreads = 1
  const session = await ort.InferenceSession.create(new Uint8Array(await readFile(modelPath)))
  const pixels = new Float32Array(3 * 80 * 80).map((_, i) => (i * 37) % 256)
  const out = await session.run({ input: new ort.Tensor('float32', pixels, [1, 3, 80, 80]) })
  const probs = [...(out.probs.data as Float32Array)]
  assert.equal(probs.length, 3)
  assert.ok(probs.every(p => p >= 0 && p <= 1))
  assert.ok(Math.abs(probs.reduce((a, b) => a + b, 0) - 1) < 1e-4)
})
