// Anti-spoofing (#165): is the one face in view a live person, or a photo or
// video of one held up to the camera? A small model (MiniFASNetV2,
// attention-models/) looks at the face crop MediaPipe already found, in the
// browser. Nothing new leaves the browser: a face judged "not live" is simply
// reported as no face, so `signal.attention` keeps its four fields.
//
// Everything here is plain maths on numbers and pixels, so it is unit tested
// and the evaluation (eval/evaluation.ts) replays exactly the same vote.
import type { FaceObservation } from './signals'

/**
 * How often to check and how sure to be. Wrongly rejecting a real student is
 * worse than missing a photo (#165), so a face is only rejected when every one
 * of the last `window` checks says "not live".
 */
export interface LivenessSettings {
  /** Time between checks on the current face, in milliseconds. */
  everyMs: number
  /** How many recent checks vote. All of them must say "not live" to reject. */
  window: number
  /** A check says "not live" when the model's live probability is below this. */
  spoofBelow: number
}

/**
 * Off until the #165 recordings say how well it works for everyone (see
 * backend/tests/eval/CV_EVALUATION.md), like GAZE_MODEL and ADAPTATION in
 * signals.ts. While null the classroom judges faces exactly as before, and the
 * model is never even loaded there.
 */
export const LIVENESS: LivenessSettings | null = null
/** A starting point for the evaluation, not yet measured on recordings. */
export const SUGGESTED_LIVENESS: LivenessSettings = { everyMs: 2000, window: 3, spoofBelow: 0.2 }

/** The model's input: an 80 x 80 crop, 2.7 times the face box, as it was trained. */
export const MODEL_SIZE = 80
export const CROP_SCALE = 2.7
/**
 * How ONNX Runtime turns the 80 x 80 crop into the model's input: blue, green,
 * red planes, 0 to 255 ((pixel + 0) / 1). The model was trained on OpenCV
 * images, which are BGR and not divided by 255.
 */
export const MODEL_INPUT = {
  tensorFormat: 'BGR', tensorLayout: 'NCHW', dataType: 'float32', norm: { mean: 1, bias: 0 },
} as const
/** Index of "live" in the model's three outputs (the other two are spoof types). */
export const LIVE_CLASS = 1

/** The recent checks on the face in view. Kept in the worker only. */
export interface LivenessState {
  scores: number[]
  lastCheck: number
  lastFrame: number
}
export const startLiveness = (): LivenessState => ({ scores: [], lastCheck: -Infinity, lastFrame: -Infinity })

/**
 * Call on every frame, before anything else. A new face (none or two in view,
 * or a long gap in frames, such as a muted camera) starts the vote again, so a
 * student who comes back is never judged on an old photo's checks.
 */
export function noteFrame(state: LivenessState, faces: number, timestamp: number, s: LivenessSettings): LivenessState {
  const gap = timestamp - state.lastFrame > 3 * s.everyMs
  if (faces !== 1 || gap) return { scores: [], lastCheck: -Infinity, lastFrame: timestamp }
  return { ...state, lastFrame: timestamp }
}

export const dueForCheck = (state: LivenessState, timestamp: number, s: LivenessSettings) =>
  timestamp - state.lastCheck >= s.everyMs

/** Add one check's live probability (0 to 1). A broken reading is ignored. */
export function recordCheck(state: LivenessState, live: number, timestamp: number, s: LivenessSettings): LivenessState {
  if (!Number.isFinite(live)) return { ...state, lastCheck: timestamp }
  return { ...state, scores: [...state.scores, live].slice(-s.window), lastCheck: timestamp }
}

/** Not live only with a full window in which every check said "not live". */
export const isSpoof = (state: LivenessState, s: LivenessSettings) =>
  state.scores.length >= s.window && state.scores.every(live => live < s.spoofBelow)

// -- what the face worker does with it --------------------------------------------

/** One check's result: the live probability and how long it took, in milliseconds. */
export interface LiveCheck { live: number; ms: number }

/** The worker loads the model only while LIVENESS is on or the recorder asks for scores. */
export const wantsLivenessModel = (s: LivenessSettings | null, withLiveScores: boolean) => s !== null || withLiveScores

/** How long the model may take to load before the camera carries on without it. */
export const LIVENESS_LOAD_TIMEOUT_MS = 30_000

/**
 * Loads the model without holding up the camera: resolves to the model, or to
 * null if loading fails or takes longer than `timeoutMs`. A model that arrives
 * after the timeout is not used, so faces stay judged as before.
 */
export function loadInBackground<T>(load: () => Promise<T>, timeoutMs = LIVENESS_LOAD_TIMEOUT_MS): Promise<T | null> {
  return new Promise(resolve => {
    const timer = setTimeout(() => resolve(null), timeoutMs)
    load().then(model => { clearTimeout(timer); resolve(model) }, () => { clearTimeout(timer); resolve(null) })
  })
}

/**
 * One camera frame's anti-spoofing step, as the worker runs it. `check` runs
 * the model on the frame's face (null while the model is not loaded). With
 * `s` null (LIVENESS off) nothing is judged, and the model runs only when
 * `everyFrame` asks for a score (the recorder). A failed check gives no score
 * and never counts towards rejecting.
 */
export async function livenessFrame(
  state: LivenessState,
  faces: number,
  timestamp: number,
  s: LivenessSettings | null,
  check: (() => Promise<LiveCheck | null>) | null,
  everyFrame = false,
): Promise<{ state: LivenessState; live: LiveCheck | null; spoof: boolean }> {
  if (s) state = noteFrame(state, faces, timestamp, s)
  let live: LiveCheck | null = null
  if (check && faces === 1 && (everyFrame || (s !== null && dueForCheck(state, timestamp, s)))) {
    live = await check().catch(() => null)
    if (s) state = recordCheck(state, live?.live ?? Number.NaN, timestamp, s)
  }
  return { state, live, spoof: s !== null && isSpoof(state, s) }
}

/** Adaptation (#166) learns only from a good moment, never while calibrating or from a rejected face. */
export const mayLearn = (spoof: boolean, calibrating: boolean, timestamp: number, learnUntil: number) =>
  !spoof && !calibrating && timestamp < learnUntil

/**
 * Calibration keeps only frames of a face not judged spoofed. Too few left,
 * and calibrate() refuses, so the student is told to try again.
 */
export const forCalibration = <T>(frames: T[], frame: T, spoof: boolean): T[] => spoof ? frames : [...frames, frame]

/** A face judged not live counts as no face, with no gaze reading (#165). */
export function applyLiveness(observation: FaceObservation, spoof: boolean): FaceObservation {
  return spoof ? { face: false, forward: null, head: 'unavailable' } : observation
}

// -- pixels ---------------------------------------------------------------------

export interface Box { x: number; y: number; width: number; height: number }

/** The face box in pixels, from MediaPipe's landmarks (0 to 1 across the image). */
export function faceBox(points: { x: number; y: number }[], imageWidth: number, imageHeight: number): Box | null {
  const xs = points.map(p => p.x).filter(Number.isFinite)
  const ys = points.map(p => p.y).filter(Number.isFinite)
  if (!xs.length || !ys.length) return null
  const x = Math.min(...xs) * imageWidth
  const y = Math.min(...ys) * imageHeight
  const width = (Math.max(...xs) - Math.min(...xs)) * imageWidth
  const height = (Math.max(...ys) - Math.min(...ys)) * imageHeight
  return width > 1 && height > 1 ? { x, y, width, height } : null
}

/**
 * The area the model looks at: the face box grown `scale` times around its
 * centre, shrunk if it would not fit, then slid back inside the image. A port
 * of CropImage._get_new_box in the model's source, so the crop matches the
 * one it was trained on. Whole pixels; right and bottom are inclusive there,
 * so width = right - left + 1.
 */
export function cropBox(face: Box, imageWidth: number, imageHeight: number, scale = CROP_SCALE): Box {
  const s = Math.min((imageHeight - 1) / face.height, (imageWidth - 1) / face.width, scale)
  const width = face.width * s
  const height = face.height * s
  const cx = face.x + face.width / 2
  const cy = face.y + face.height / 2
  let left = cx - width / 2
  let top = cy - height / 2
  let right = cx + width / 2
  let bottom = cy + height / 2
  if (left < 0) { right -= left; left = 0 }
  if (top < 0) { bottom -= top; top = 0 }
  if (right > imageWidth - 1) { left -= right - imageWidth + 1; right = imageWidth - 1 }
  if (bottom > imageHeight - 1) { top -= bottom - imageHeight + 1; bottom = imageHeight - 1 }
  const l = Math.trunc(left)
  const t = Math.trunc(top)
  return { x: l, y: t, width: Math.trunc(right) - l + 1, height: Math.trunc(bottom) - t + 1 }
}
