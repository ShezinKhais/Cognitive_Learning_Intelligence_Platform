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
 * #63. The angle limits apply when MediaPipe supplies a pose and were tuned on
 * six team members' recordings (backend/tests/eval/CV_EVALUATION.md): these
 * for a student who has not calibrated, CALIBRATED_THRESHOLDS for one who has.
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
  maxYawDegrees: 15,
  maxPitchDegrees: 30,
  maxRollDegrees: 30,
  minEyeWidth: 0.005,
  minOpenEyeRatio: 0.12,
  irisX: [0.3, 0.7],
  irisY: [0.1, 0.9],
}

/**
 * For a student who has calibrated. With GAZE_MODEL on, the yaw and pitch
 * limits apply to the combined head and eye direction measured from the
 * student's own centre: the gaze limits tuned on the ten-participant
 * recordings (#253, #166), which DEFAULT_THRESHOLDS cannot use without a centre.
 */
export const CALIBRATED_THRESHOLDS: Thresholds = {
  ...DEFAULT_THRESHOLDS,
  maxYawDegrees: 20,
  maxPitchDegrees: 25,
}

export const thresholdsFor = (calibration: Calibration | null): Thresholds =>
  calibration ? CALIBRATED_THRESHOLDS : DEFAULT_THRESHOLDS

/**
 * One student's own "looking at the screen": the head angles and iris
 * position they hold while doing so. Kept in the browser only.
 */
export interface Calibration {
  yaw: number; pitch: number; roll: number; irisX: number; irisY: number
  /**
   * Left iris x minus right iris x while looking at the screen. Most people's
   * eyes move together, so this is about 0; for a squint it is not, and the
   * combined gaze (#166) compares the eyes against this person's own gap.
   */
  eyeGapX?: number
}

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
  gaze: GazeModel | null = null,
): FaceObservation {
  const unavailable: FaceObservation = { face: null, forward: null, head: 'unavailable' }
  if (f.faces === 0) return { ...unavailable, face: false }
  if (f.faces !== 1 || !f.valid || f.width === null) return unavailable
  if (f.width < t.minFaceWidth) return { ...unavailable, face: true }
  const c = calibration ?? { yaw: 0, pitch: 0, roll: 0, irisX: 0.5, irisY: 0.5 }
  if (gaze && f.pose) return classifyGaze(f, f.pose, t, c, gaze)
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

// -- #166: one gaze direction from head and eyes together ----------------------

/**
 * How far the eyes turn for a unit of iris movement inside the eye, per axis.
 * Fitted on recordings (`frontend/eval/evaluation.ts`, `tuneGaze`), leaving one
 * participant out. The sign is part of the fit: it depends on which way
 * MediaPipe's angles and the image's x run, which the data settles.
 */
export interface GazeModel {
  /** Degrees of gaze yaw per unit of iris x (0 to 1 across the eye). */
  kYaw: number
  /** Degrees of gaze pitch per unit of iris y. */
  kPitch: number
  /**
   * How far the two eyes may disagree (iris x, beyond this person's own
   * calibrated gap) before there is no reliable reading. Eyes that point
   * different ways (a squint, a prosthetic eye) give "no reading", never "away".
   */
  maxEyeDisagreement: number
  /**
   * Head tilt (ear towards shoulder) beyond which the landmarks are no longer
   * trusted, so there is no reading. Below it tilt is ignored: it hardly moves
   * where the eyes point, and resting the head on a hand, a stiff neck or a
   * camera at an angle should not read as looking away (#166, P2's recording).
   */
  maxRollDegrees: number
}

/**
 * What ships: k fitted on the ten-participant recordings (#253, #166), with
 * `screen_head_turned` and `away_eyes_only` clips. Leaving one participant out,
 * combined gaze and adaptation reached 81.5% balanced accuracy against 77.6%
 * for the head check alone (CV_EVALUATION.md, second round). Null would bring
 * back #159's rule (the head check, with the eyes as a veto).
 */
export const GAZE_MODEL: GazeModel | null = { kYaw: 150, kPitch: 0, maxEyeDisagreement: 0.15, maxRollDegrees: 45 }

/** One gaze direction, in degrees from the student's centre, or null when there is no reliable reading. */
export function gazeAngles(
  f: FaceFeatures, pose: PoseAngles, c: Calibration, gaze: GazeModel,
): { yaw: number; pitch: number } | null {
  const l = f.leftEye, r = f.rightEye
  if (!l || !r) return null
  if (Math.abs((l.irisX - r.irisX) - (c.eyeGapX ?? 0)) > gaze.maxEyeDisagreement) return null
  const irisX = (l.irisX + r.irisX) / 2
  const irisY = (l.irisY + r.irisY) / 2
  return {
    yaw: (pose.yaw - c.yaw) + gaze.kYaw * (irisX - c.irisX),
    pitch: (pose.pitch - c.pitch) + gaze.kPitch * (irisY - c.irisY),
  }
}

/**
 * With a gaze model, "head 20° right, eyes 20° left" is looking at the screen
 * and "head still, eyes 20° left" is not: the eyes can rescue a turned head as
 * well as veto a still one. The yaw and pitch limits then apply to the gaze.
 * A tilted head is not "away"; tilted past gaze.maxRollDegrees it is no reading.
 */
function classifyGaze(f: FaceFeatures, pose: PoseAngles, t: Thresholds, c: Calibration, gaze: GazeModel): FaceObservation {
  const forwardHead = Math.abs(pose.yaw - c.yaw) < t.maxYawDegrees
    && Math.abs(pose.pitch - c.pitch) < t.maxPitchDegrees
    && Math.abs(pose.roll - c.roll) < t.maxRollDegrees
  const head = forwardHead ? 'forward' : 'turned'
  const eyeOpen = (e: EyeFeatures | null) => e !== null && e.width >= t.minEyeWidth && e.open >= t.minOpenEyeRatio
  if (!eyeOpen(f.leftEye) || !eyeOpen(f.rightEye)) return { face: true, head, forward: null }
  const g = gazeAngles(f, pose, c, gaze)
  if (!g || Math.abs(pose.roll - c.roll) > gaze.maxRollDegrees) return { face: true, head, forward: null }
  return { face: true, head, forward: Math.abs(g.yaw) < t.maxYawDegrees && Math.abs(g.pitch) < t.maxPitchDegrees }
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
// Upward (negative pitch) is allowed further: sitting back from a laptop, or a
// camera below eye level, reads as 23 to 30 degrees up while looking at the
// screen (#159 recordings). Downward stays at the limit above, so a centre
// taken while looking down at notes (17 to 20 degrees down) is still refused.
export const MAX_CALIBRATION_UP_DEGREES = 35
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
    eyeGapX: median(usable.map(f => f.leftEye!.irisX - f.rightEye!.irisX)),
  }
  const plausible = [calibration.yaw, calibration.roll]
    .every(angle => Math.abs(angle) <= MAX_CALIBRATION_OFFSET_DEGREES)
    && calibration.pitch <= MAX_CALIBRATION_OFFSET_DEGREES
    && calibration.pitch >= -MAX_CALIBRATION_UP_DEGREES
    && Math.abs(calibration.irisX - 0.5) <= MAX_CALIBRATION_IRIS_OFFSET
    && Math.abs(calibration.irisY - 0.5) <= MAX_CALIBRATION_IRIS_OFFSET
  return plausible ? calibration : null
}

// -- #166: limits that adapt to each student during the session ----------------

/**
 * How the camera learns one student's own normal while the class runs, in the
 * browser only. It learns from good moments, when the student is very likely
 * looking at the screen (the calibration, typing an answer), and it can only
 * make the judgement fairer: a learned limit is never stricter than the
 * standard one, and a normal wider than the camera can measure gives "no
 * reading" rather than "away". It never tries to work out why a student's
 * normal is what it is.
 */
export interface AdaptationSettings {
  /** Weight of one good frame in the running centre and spread, 0 to 1. */
  rate: number
  /**
   * The most the centre may move for one frame, in degrees: enough to follow a
   * laptop being moved over a few seconds, too little for one odd frame to matter.
   */
  maxCentreStepDegrees: number
  /** Limits are this many times the student's own spread (standard deviation). */
  spreadMultiplier: number
  /** The loosest limits adaptation may reach, in degrees. A wider normal gives no reading. */
  maxLimits: { yaw: number; pitch: number; roll: number }
  /** Good frames needed before the spread is trusted; until then the standard limits apply. */
  minFrames: number
}

/**
 * What ships: the suggested settings, evaluated with GAZE_MODEL on the
 * ten-participant recordings (#253, #166). Learned limits are never stricter;
 * a moved centre turned 19 of 13,080 held-out frames (0.15%) from "on screen"
 * to "away" (CV_EVALUATION.md). Null would bring back fixed limits.
 */
export const SUGGESTED_ADAPTATION: AdaptationSettings = {
  rate: 0.05,
  maxCentreStepDegrees: 0.5,
  spreadMultiplier: 3,
  maxLimits: { yaw: 25, pitch: 30, roll: 25 },
  minFrames: 12,
}
export const ADAPTATION: AdaptationSettings | null = SUGGESTED_ADAPTATION

export interface AdaptiveState {
  /** Good frames learned from so far. */
  frames: number
  /** The student's centre now: the calibration, then followed as it drifts. */
  centre: Calibration
  /** Running mean squared distance from the centre while looking, in degrees squared. */
  variance: { yaw: number; pitch: number; roll: number }
}

const NO_CENTRE: Calibration = { yaw: 0, pitch: 0, roll: 0, irisX: 0.5, irisY: 0.5, eyeGapX: 0 }

export function startAdaptation(calibration: Calibration | null): AdaptiveState {
  return { frames: 0, centre: { ...NO_CENTRE, ...calibration }, variance: { yaw: 0, pitch: 0, roll: 0 } }
}

/** The limits for this student now, never stricter than `base`, and whether their normal fits what the camera can measure. */
export function adaptedThresholds(
  state: AdaptiveState, base: Thresholds, s: AdaptationSettings,
): { thresholds: Thresholds; measurable: boolean } {
  if (state.frames < s.minFrames) return { thresholds: base, measurable: true }
  let measurable = true
  const limit = (variance: number, standard: number, cap: number) => {
    const wanted = s.spreadMultiplier * Math.sqrt(variance)
    const ceiling = Math.max(standard, cap)
    if (wanted > ceiling) measurable = false
    return Math.max(standard, Math.min(ceiling, wanted))
  }
  const thresholds = {
    ...base,
    maxYawDegrees: limit(state.variance.yaw, base.maxYawDegrees, s.maxLimits.yaw),
    maxPitchDegrees: limit(state.variance.pitch, base.maxPitchDegrees, s.maxLimits.pitch),
    maxRollDegrees: limit(state.variance.roll, base.maxRollDegrees, s.maxLimits.roll),
  }
  return { thresholds, measurable }
}

const clamp = (value: number, low: number, high: number) => Math.min(high, Math.max(low, value))

/**
 * Learn from one frame of a good moment. A frame far outside even the loosest
 * limits is skipped, so glancing at the keyboard while typing, or a long look
 * away, does not become the new normal; the centre moves a little per frame
 * and stays inside the range a calibration may have.
 */
export function learn(
  state: AdaptiveState, f: FaceFeatures, base: Thresholds, s: AdaptationSettings, gaze: GazeModel | null = null,
): AdaptiveState {
  if (f.faces !== 1 || !f.valid || !f.pose || !f.leftEye || !f.rightEye) return state
  const c = state.centre
  const irisX = (f.leftEye.irisX + f.rightEye.irisX) / 2
  const irisY = (f.leftEye.irisY + f.rightEye.irisY) / 2
  if (Math.abs(irisX - c.irisX) > MAX_CALIBRATION_IRIS_OFFSET || Math.abs(irisY - c.irisY) > MAX_CALIBRATION_IRIS_OFFSET) return state
  const g = gaze ? gazeAngles(f, f.pose, c, gaze) : null
  if (gaze && !g) return state
  const d = { yaw: g ? g.yaw : f.pose.yaw - c.yaw, pitch: g ? g.pitch : f.pose.pitch - c.pitch, roll: f.pose.roll - c.roll }
  const { thresholds } = adaptedThresholds(state, base, s)
  const tooFar = (deviation: number, now: number, cap: number) => Math.abs(deviation) > Math.min(1.5 * now, Math.max(now, cap))
  if (tooFar(d.yaw, thresholds.maxYawDegrees, s.maxLimits.yaw)
    || tooFar(d.pitch, thresholds.maxPitchDegrees, s.maxLimits.pitch)
    || tooFar(d.roll, thresholds.maxRollDegrees, s.maxLimits.roll)) return state
  const step = (now: number, seen: number, most: number) => now + clamp(s.rate * (seen - now), -most, most)
  const degrees = s.maxCentreStepDegrees
  const centre: Calibration = {
    yaw: clamp(step(c.yaw, f.pose.yaw, degrees), -MAX_CALIBRATION_OFFSET_DEGREES, MAX_CALIBRATION_OFFSET_DEGREES),
    pitch: clamp(step(c.pitch, f.pose.pitch, degrees), -MAX_CALIBRATION_UP_DEGREES, MAX_CALIBRATION_OFFSET_DEGREES),
    roll: clamp(step(c.roll, f.pose.roll, degrees), -MAX_CALIBRATION_OFFSET_DEGREES, MAX_CALIBRATION_OFFSET_DEGREES),
    irisX: clamp(step(c.irisX, irisX, degrees / 100), 0.5 - MAX_CALIBRATION_IRIS_OFFSET, 0.5 + MAX_CALIBRATION_IRIS_OFFSET),
    irisY: clamp(step(c.irisY, irisY, degrees / 100), 0.5 - MAX_CALIBRATION_IRIS_OFFSET, 0.5 + MAX_CALIBRATION_IRIS_OFFSET),
    eyeGapX: step(c.eyeGapX ?? 0, f.leftEye.irisX - f.rightEye.irisX, degrees / 100),
  }
  // The first frames weigh more, so the spread settles in seconds, not minutes.
  const weight = Math.max(s.rate, 1 / (state.frames + 1))
  const blend = (now: number, deviation: number) => (1 - weight) * now + weight * deviation * deviation
  return {
    frames: state.frames + 1,
    centre,
    variance: { yaw: blend(state.variance.yaw, d.yaw), pitch: blend(state.variance.pitch, d.pitch), roll: blend(state.variance.roll, d.roll) },
  }
}

/** classifyFace with this student's learned centre and limits; "away" beyond what can be measured becomes "no reading". */
export function classifyAdaptive(
  f: FaceFeatures, state: AdaptiveState, base: Thresholds, s: AdaptationSettings, gaze: GazeModel | null = null,
): FaceObservation {
  const { thresholds, measurable } = adaptedThresholds(state, base, s)
  const seen = classifyFace(f, thresholds, state.centre, gaze)
  return !measurable && seen.forward === false ? { ...seen, forward: null } : seen
}

/** A voice-detection frame at or above this speech probability counts as speaking. */
export const SPEECH_THRESHOLD = 0.6

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
