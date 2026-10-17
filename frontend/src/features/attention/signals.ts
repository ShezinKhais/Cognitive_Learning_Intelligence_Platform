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

/** Head angles in degrees, from MediaPipe's facial transformation matrix. */
export interface PoseAngles { yaw: number; pitch: number; roll: number }
/** One eye: how open it is (height / width) and where the iris sits in it (0 to 1). */
export interface EyeFeatures { width: number; open: number; irisX: number; irisY: number }
/**
 * The numbers one frame is judged on. A frame is turned into these first and
 * judged second (classifyFace), so the evaluation replays recorded features
 * through exactly the judgement the browser makes, and no video is kept.
 */
export interface FaceFeatures {
  faces: number
  /** One face with every landmark used here present and finite. */
  valid: boolean
  width: number | null
  /** Landmark proxies for head turn and tilt, used when there is no pose. */
  yawProxy: number | null
  rollProxy: number | null
  pose: PoseAngles | null
  leftEye: EyeFeatures | null
  rightEye: EyeFeatures | null
}

/**
 * Where "facing the screen" ends. The proxy values are the hand-set ones from
 * #63; the angle limits apply when MediaPipe supplies a pose and are the ones
 * to set from data (scripts/evaluate-attention.ts, CV_EVALUATION.md).
 */
export interface Thresholds {
  minFaceWidth: number
  maxYawProxy: number
  maxRollProxy: number
  maxYawDegrees: number
  maxPitchDegrees: number
  maxRollDegrees: number
  minEyeWidth: number
  minOpenEyeRatio: number
  irisX: readonly [number, number]
  irisY: readonly [number, number]
}
export const DEFAULT_THRESHOLDS: Thresholds = {
  minFaceWidth: 0.03,
  maxYawProxy: 0.22,
  maxRollProxy: 0.3,
  maxYawDegrees: 25,
  maxPitchDegrees: 20,
  maxRollDegrees: 20,
  minEyeWidth: 0.005,
  minOpenEyeRatio: 0.12,
  irisX: [0.2, 0.8],
  irisY: [0.1, 0.9],
}

/**
 * One student's own "looking at the screen": the head angles and iris
 * position they hold while doing so. Kept in the browser only.
 */
export interface Calibration { yaw: number; pitch: number; roll: number; irisX: number; irisY: number }

/** MediaPipe's 4x4 matrix is column-major: element (row, column) is data[column * 4 + row]. */
export function poseFromMatrix(data: ArrayLike<number>): PoseAngles | null {
  if (data.length < 16) return null
  const r = (row: number, column: number) => data[column * 4 + row]
  const degrees = 180 / Math.PI
  const pose = {
    yaw: Math.asin(Math.max(-1, Math.min(1, -r(2, 0)))) * degrees,
    pitch: Math.atan2(r(2, 1), r(2, 2)) * degrees,
    roll: Math.atan2(r(1, 0), r(0, 0)) * degrees,
  }
  return [pose.yaw, pose.pitch, pose.roll].every(Number.isFinite) ? pose : null
}

/** The numbers classifyFace needs, from the landmarks (and pose, if any) of every face found. */
export function faceFeatures(faces: Point[][], matrices?: ArrayLike<number>[]): FaceFeatures {
  const none: FaceFeatures = {
    faces: faces.length, valid: false, width: null, yawProxy: null, rollProxy: null,
    pose: null, leftEye: null, rightEye: null,
  }
  if (faces.length !== 1) return none
  const p = faces[0]
  const ids = Object.values(LANDMARK)
  if (ids.some(i => !p[i] || ![p[i].x, p[i].y, p[i].z].every(Number.isFinite))) return none
  const width = Math.abs(p[LANDMARK.rightEyeOuter].x - p[LANDMARK.leftEyeOuter].x)
  function eye(a: number, b: number, top: number, bottom: number, iris: number): EyeFeatures {
    const w = Math.abs(p[a].x - p[b].x)
    const h = Math.abs(p[top].y - p[bottom].y)
    return {
      width: w,
      open: w > 0 ? h / w : 0,
      irisX: w > 0 ? (p[iris].x - Math.min(p[a].x, p[b].x)) / w : 0,
      irisY: h > 0 ? (p[iris].y - Math.min(p[top].y, p[bottom].y)) / h : 0,
    }
  }
  return {
    faces: 1,
    valid: true,
    width,
    yawProxy: width > 0 ? Math.abs(p[LANDMARK.nose].x - (p[LANDMARK.leftEyeOuter].x + p[LANDMARK.rightEyeOuter].x) / 2) / width : null,
    rollProxy: width > 0 ? Math.abs(p[LANDMARK.leftEyeOuter].y - p[LANDMARK.rightEyeOuter].y) / width : null,
    pose: matrices?.[0] ? poseFromMatrix(matrices[0]) : null,
    leftEye: eye(LANDMARK.leftEyeOuter, LANDMARK.leftEyeInner, LANDMARK.leftEyeTop, LANDMARK.leftEyeBottom, LANDMARK.leftIris),
    rightEye: eye(LANDMARK.rightEyeInner, LANDMARK.rightEyeOuter, LANDMARK.rightEyeTop, LANDMARK.rightEyeBottom, LANDMARK.rightIris),
  }
}

/** Coarse camera-facing proxy, not eye tracking or an attention judgement. */
export function classifyFace(
  f: FaceFeatures,
  t: Thresholds = DEFAULT_THRESHOLDS,
  calibration: Calibration | null = null,
): FaceObservation {
  const unavailable: FaceObservation = { face: null, forward: null, head: 'unavailable' }
  if (f.faces === 0) return { ...unavailable, face: false }
  if (f.faces !== 1 || !f.valid || f.width === null) return unavailable
  if (f.width < t.minFaceWidth) return { ...unavailable, face: true }
  const c = calibration ?? { yaw: 0, pitch: 0, roll: 0, irisX: 0.5, irisY: 0.5 }
  let forwardHead: boolean
  if (f.pose) {
    // Looking down at notes is a pitch the landmark proxies cannot see.
    forwardHead = Math.abs(f.pose.yaw - c.yaw) < t.maxYawDegrees
      && Math.abs(f.pose.pitch - c.pitch) < t.maxPitchDegrees
      && Math.abs(f.pose.roll - c.roll) < t.maxRollDegrees
  } else {
    forwardHead = f.yawProxy !== null && f.rollProxy !== null
      && f.yawProxy < t.maxYawProxy && f.rollProxy < t.maxRollProxy
  }
  const head = forwardHead ? 'forward' : 'turned'
  // The calibrated centre moves the iris box, so a student whose eyes rest
  // off the middle is not read as looking away.
  const shiftX = c.irisX - 0.5
  const shiftY = c.irisY - 0.5
  function eyeOnScreen(e: EyeFeatures | null): boolean | null {
    if (!e || e.width < t.minEyeWidth || e.open < t.minOpenEyeRatio) return null
    const x = e.irisX - shiftX
    const y = e.irisY - shiftY
    return x >= t.irisX[0] && x <= t.irisX[1] && y >= t.irisY[0] && y <= t.irisY[1]
  }
  const left = eyeOnScreen(f.leftEye)
  const right = eyeOnScreen(f.rightEye)
  return { face: true, head, forward: left === null || right === null ? null : forwardHead && left && right }
}

export function observeFace(
  faces: Point[][],
  matrices?: ArrayLike<number>[],
  t: Thresholds = DEFAULT_THRESHOLDS,
  calibration: Calibration | null = null,
): FaceObservation {
  return classifyFace(faceFeatures(faces, matrices), t, calibration)
}

// A calibration is a few seconds of looking at the screen. Fewer usable
// frames, or a centre this far off straight ahead, means the student was not
// looking at the screen, so no calibration is better than a wrong one.
export const MIN_CALIBRATION_FRAMES = 6
export const MAX_CALIBRATION_OFFSET_DEGREES = 20
export const MAX_CALIBRATION_IRIS_OFFSET = 0.2

function median(values: number[]): number {
  const sorted = [...values].sort((a, b) => a - b)
  const middle = Math.floor(sorted.length / 2)
  return sorted.length % 2 ? sorted[middle] : (sorted[middle - 1] + sorted[middle]) / 2
}

/** The student's own centre from frames taken while they looked at the screen, or null. */
export function calibrate(frames: FaceFeatures[]): Calibration | null {
  const usable = frames.filter(f => f.faces === 1 && f.valid && f.pose && f.leftEye && f.rightEye)
  if (usable.length < MIN_CALIBRATION_FRAMES) return null
  const calibration = {
    yaw: median(usable.map(f => f.pose!.yaw)),
    pitch: median(usable.map(f => f.pose!.pitch)),
    roll: median(usable.map(f => f.pose!.roll)),
    irisX: median(usable.map(f => (f.leftEye!.irisX + f.rightEye!.irisX) / 2)),
    irisY: median(usable.map(f => (f.leftEye!.irisY + f.rightEye!.irisY) / 2)),
  }
  const plausible = [calibration.yaw, calibration.pitch, calibration.roll]
    .every(angle => Math.abs(angle) <= MAX_CALIBRATION_OFFSET_DEGREES)
    && Math.abs(calibration.irisX - 0.5) <= MAX_CALIBRATION_IRIS_OFFSET
    && Math.abs(calibration.irisY - 0.5) <= MAX_CALIBRATION_IRIS_OFFSET
  return plausible ? calibration : null
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
