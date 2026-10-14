// Derived observations only: no media, landmarks or device identifiers on the wire.
export interface AttentionSummary {
  gaze_on_screen_ratio: number | null
  face_present: boolean | null
  speaking: boolean | null
  window_seconds: number
}
export interface FaceObservation {
  face: boolean | null
  forward: boolean | null
  head: 'forward' | 'turned' | 'unavailable'
}
interface Point { x: number; y: number; z: number }

/** Never count time before the first active sensor actually started. */
export function coveredWindowSeconds(now: number, lastReport: number, activeStarts: number[]): number {
  const firstStart = activeStarts.length ? Math.min(...activeStarts) : lastReport
  return Math.max(0.001, (now - Math.max(lastReport, firstStart)) / 1000)
}

const LANDMARK = {
  nose: 1,
  leftEyeOuter: 33,
  leftEyeInner: 133,
  leftEyeTop: 159,
  leftEyeBottom: 145,
  rightEyeInner: 362,
  rightEyeOuter: 263,
  rightEyeTop: 386,
  rightEyeBottom: 374,
  leftIris: 468,
  rightIris: 473,
} as const
const MIN_FACE_WIDTH = 0.03
const MAX_FORWARD_YAW = 0.22
const MAX_FORWARD_ROLL = 0.3
const MIN_EYE_WIDTH = 0.005
const MIN_OPEN_EYE_RATIO = 0.12
const IRIS_X_RANGE = [0.2, 0.8] as const
const IRIS_Y_RANGE = [0.1, 0.9] as const

/** Coarse camera-facing proxy, not eye tracking or an attention judgement. */
export function observeFace(faces: Point[][]): FaceObservation {
  const unavailable: FaceObservation = { face: null, forward: null, head: 'unavailable' }
  if (!faces.length) return { ...unavailable, face: false }
  if (faces.length !== 1) return unavailable
  const p = faces[0]
  const ids = Object.values(LANDMARK)
  if (ids.some(i => !p[i] || ![p[i].x, p[i].y, p[i].z].every(Number.isFinite))) return unavailable
  const width = Math.abs(p[LANDMARK.rightEyeOuter].x - p[LANDMARK.leftEyeOuter].x)
  if (width < MIN_FACE_WIDTH) return { ...unavailable, face: true }
  const yaw = Math.abs(p[LANDMARK.nose].x - (p[LANDMARK.leftEyeOuter].x + p[LANDMARK.rightEyeOuter].x) / 2) / width
  const roll = Math.abs(p[LANDMARK.leftEyeOuter].y - p[LANDMARK.rightEyeOuter].y) / width
  const head = yaw < MAX_FORWARD_YAW && roll < MAX_FORWARD_ROLL ? 'forward' : 'turned'
  function eye(a: number, b: number, top: number, bottom: number, iris: number) {
    const w = Math.abs(p[a].x - p[b].x)
    const h = Math.abs(p[top].y - p[bottom].y)
    if (w < MIN_EYE_WIDTH || h / w < MIN_OPEN_EYE_RATIO) return null
    const x = (p[iris].x - Math.min(p[a].x, p[b].x)) / w
    const y = (p[iris].y - Math.min(p[top].y, p[bottom].y)) / h
    return x >= IRIS_X_RANGE[0] && x <= IRIS_X_RANGE[1] && y >= IRIS_Y_RANGE[0] && y <= IRIS_Y_RANGE[1]
  }
  const left = eye(LANDMARK.leftEyeOuter, LANDMARK.leftEyeInner, LANDMARK.leftEyeTop, LANDMARK.leftEyeBottom, LANDMARK.leftIris)
  const right = eye(LANDMARK.rightEyeInner, LANDMARK.rightEyeOuter, LANDMARK.rightEyeTop, LANDMARK.rightEyeBottom, LANDMARK.rightIris)
  return { face: true, head, forward: left === null || right === null ? null : head === 'forward' && left && right }
}

/** Null is absence, not a negative signal. Only the frozen wire shape leaves. */
export function summary(
  samples: FaceObservation[],
  speech: boolean[],
  seconds: number,
  freshness?: { now: number; faceAt: number; speechAt: number },
): AttentionSummary {
  // A silent or stalled sensor is unavailable, not evidence of absence.
  const currentFace = freshness && freshness.now - freshness.faceAt >= 2000 ? [] : samples
  const currentSpeech = freshness && freshness.now - freshness.speechAt >= 2000 ? [] : speech
  const gaze = currentFace.filter(s => s.forward !== null)
  const faces = currentFace.filter(s => s.face !== null)
  return {
    gaze_on_screen_ratio: gaze.length ? gaze.filter(s => s.forward).length / gaze.length : null,
    face_present: faces.length ? faces.some(s => s.face) : null,
    speaking: currentSpeech.length ? currentSpeech.some(Boolean) : null,
    window_seconds: Math.min(3600, Math.max(0.001, seconds)),
  }
}
