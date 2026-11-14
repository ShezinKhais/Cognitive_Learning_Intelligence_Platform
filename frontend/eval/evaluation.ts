// Camera attention evaluation (#159): how recorded frames are stored, and how
// well classifyFace does on them. Used by the recorder page
// (eval/attention-recorder.html) and scripts/evaluate-attention.ts; never by
// the classroom.
//
// A recording holds derived numbers per frame and the label the person was
// told to act out. No video, image or landmark is stored.
import {
  calibrate, classifyAdaptive, classifyFace, DEFAULT_THRESHOLDS, learn, startAdaptation,
  type AdaptationSettings, type Calibration, type FaceFeatures, type FaceObservation, type GazeModel, type Thresholds,
} from '../src/features/attention/signals.ts'
import {
  dueForCheck, isSpoof, noteFrame, recordCheck, startLiveness, type LivenessSettings,
} from '../src/features/attention/liveness.ts'

/** What the person was asked to do during a clip. */
export const LABELS = {
  calibrate: 'Look at the middle of the screen (used only to calibrate)',
  screen: 'Look at the screen and read it normally',
  away_left: 'Look away, to the left of the screen',
  away_right: 'Look away, to the right of the screen',
  down_notes: 'Look down at notes on your desk',
  eyes_closed: 'Close your eyes, facing the screen',
  no_face: 'Move out of the camera view',
  two_faces: 'Have a second person in view with you',
  // #166: the two cases a head-only rule gets wrong, missing from #159's recordings.
  screen_head_turned: 'Keep your eyes on the screen while turning or tilting your head a little left, right, up and down',
  away_eyes_only: 'Keep your head still and look to the side with your eyes only, left then right',
  // #165: presentation attacks. Step out of view and hold the photo or video
  // where your face was, moving it a little as a hand would.
  photo_on_phone: 'Step out of view and hold up a photo of your face on a phone',
  video_on_phone: 'Step out of view and hold up a video of your face playing on a phone',
  printed_photo: 'Step out of view and hold up a printed photo of your face',
} as const
/** Labels added for #166, reported on their own so the #159 numbers stay comparable. */
export const GAZE_LABELS: readonly Label[] = ['screen_head_turned', 'away_eyes_only']
export type Label = keyof typeof LABELS
/** #165: a photo or video of a face, not a live person. Kept out of the #159 numbers. */
export const SPOOF_LABELS: readonly Label[] = ['photo_on_phone', 'video_on_phone', 'printed_photo']
export const isSpoofLabel = (label: Label) => SPOOF_LABELS.includes(label)

export const CONDITIONS = {
  glasses: ['no', 'yes'],
  lighting: ['normal', 'dim'],
  position: ['centred', 'off_centre'],
  distance: ['near', 'far'],
} as const
export type Condition = keyof typeof CONDITIONS

export interface Frame {
  participant: string
  clip: string
  label: Label
  conditions: Record<Condition, string>
  t: number
  features: FaceFeatures
  /** #165: the anti-spoofing model's live probability for this frame, if checked. */
  live?: number | null
  /** #165: how long that check took in the browser, in milliseconds. */
  liveMs?: number | null
}

export const COLUMNS = [
  'participant', 'clip', 'label', 'glasses', 'lighting', 'position', 'distance', 't',
  'faces', 'valid', 'width', 'yaw_proxy', 'roll_proxy', 'yaw', 'pitch', 'roll',
  'l_width', 'l_open', 'l_iris_x', 'l_iris_y', 'r_width', 'r_open', 'r_iris_x', 'r_iris_y',
  'live', 'live_ms',
] as const

const number = (value: number | null | undefined) => value === null || value === undefined ? '' : String(Number(value.toFixed(5)))

export function frameToRow(f: Frame): string {
  const x = f.features
  return [
    f.participant, f.clip, f.label, f.conditions.glasses, f.conditions.lighting,
    f.conditions.position, f.conditions.distance, number(f.t),
    String(x.faces), x.valid ? '1' : '0', number(x.width), number(x.yawProxy), number(x.rollProxy),
    number(x.pose?.yaw), number(x.pose?.pitch), number(x.pose?.roll),
    number(x.leftEye?.width), number(x.leftEye?.open), number(x.leftEye?.irisX), number(x.leftEye?.irisY),
    number(x.rightEye?.width), number(x.rightEye?.open), number(x.rightEye?.irisX), number(x.rightEye?.irisY),
    number(f.live), number(f.liveMs),
  ].join(',')
}

export function framesToCsv(frames: Frame[]): string {
  return [COLUMNS.join(','), ...frames.map(frameToRow)].join('\n') + '\n'
}

/**
 * Rows of one recording file. Files from before the countdown fix also hold
 * the two-second "get ready" frames: their t counts up, then starts again from
 * zero when the clip really begins, so the rows before that restart are dropped.
 */
export function parseCsv(text: string): Frame[] {
  return dropCountdown(parseRows(text))
}

export function dropCountdown(frames: Frame[]): Frame[] {
  const key = (f: Frame) => `${f.participant}/${f.clip}`
  const lastT = new Map<string, number>()
  const restart = new Map<string, number>()
  frames.forEach((f, i) => {
    if (f.t < (lastT.get(key(f)) ?? -Infinity)) restart.set(key(f), i)
    lastT.set(key(f), f.t)
  })
  return frames.filter((f, i) => i >= (restart.get(key(f)) ?? 0))
}

function parseRows(text: string): Frame[] {
  const [header, ...lines] = text.trim().split(/\r?\n/)
  const names = header.split(',')
  return lines.filter(Boolean).map(line => {
    const cells = line.split(',')
    const get = (name: string) => cells[names.indexOf(name)] ?? ''
    const num = (name: string) => get(name) === '' ? null : Number(get(name))
    const eye = (side: 'l' | 'r') => num(`${side}_width`) === null ? null : {
      width: num(`${side}_width`)!, open: num(`${side}_open`)!,
      irisX: num(`${side}_iris_x`)!, irisY: num(`${side}_iris_y`)!,
    }
    const label = get('label')
    if (!(label in LABELS)) throw new Error(`unknown label "${label}"`)
    return {
      participant: get('participant'),
      clip: get('clip'),
      label: label as Label,
      conditions: {
        glasses: get('glasses'), lighting: get('lighting'),
        position: get('position'), distance: get('distance'),
      },
      t: Number(get('t')),
      // Files from before #165 have no live columns: no score, not a failed one.
      live: num('live'),
      liveMs: num('live_ms'),
      features: {
        faces: Number(get('faces')),
        valid: get('valid') === '1',
        width: num('width'),
        yawProxy: num('yaw_proxy'),
        rollProxy: num('roll_proxy'),
        pose: num('yaw') === null ? null : { yaw: num('yaw')!, pitch: num('pitch')!, roll: num('roll')! },
        leftEye: eye('l'),
        rightEye: eye('r'),
      },
    }
  })
}

// -- what each label should give ------------------------------------------------

/** Is there a face in view? Two faces is still a face. */
export const faceTruth = (label: Label) => label !== 'no_face' && !isSpoofLabel(label)
/** Is the person looking at the screen? */
export const lookingTruth = (label: Label) => label === 'screen' || label === 'calibrate' || label === 'screen_head_turned'

// -- counting -------------------------------------------------------------------

/** A binary outcome, with frames the system gave no reading for kept apart. */
export interface Counts { tp: number; fp: number; fn: number; tn: number; noReadingTrue: number; noReadingFalse: number }
const emptyCounts = (): Counts => ({ tp: 0, fp: 0, fn: 0, tn: 0, noReadingTrue: 0, noReadingFalse: 0 })

export function count(pairs: { truth: boolean; predicted: boolean | null }[]): Counts {
  const c = emptyCounts()
  for (const { truth, predicted } of pairs) {
    if (predicted === null) {
      if (truth) c.noReadingTrue++
      else c.noReadingFalse++
    }
    else if (predicted && truth) c.tp++
    else if (predicted && !truth) c.fp++
    else if (!predicted && truth) c.fn++
    else c.tn++
  }
  return c
}

export const precision = (c: Counts) => c.tp + c.fp ? c.tp / (c.tp + c.fp) : null
export const recall = (c: Counts) => c.tp + c.fn ? c.tp / (c.tp + c.fn) : null
/** Share of frames with a reading at all. */
export const coverage = (c: Counts) => {
  const all = c.tp + c.fp + c.fn + c.tn + c.noReadingTrue + c.noReadingFalse
  return all ? (all - c.noReadingTrue - c.noReadingFalse) / all : null
}
/**
 * Balanced accuracy for "looking at the screen", with no reading counted as
 * "not looking", the way a window with no forward frames reads: the measure
 * tuning maximises. Balanced, so the many away labels do not swamp "screen".
 */
export function balancedAccuracy(c: Counts): number | null {
  const positives = c.tp + c.fn + c.noReadingTrue
  const negatives = c.tn + c.fp + c.noReadingFalse
  if (!positives || !negatives) return null
  return (c.tp / positives + (c.tn + c.noReadingFalse) / negatives) / 2
}

/**
 * `uncalibrated` is what the app falls back to when calibration is on but this
 * person has none (missing or refused), as thresholdsFor does in the worker.
 */
export interface Setting {
  thresholds: Thresholds
  calibrated: boolean
  uncalibrated?: Thresholds
  /** #166: judge one gaze direction from head and eyes. */
  gaze?: GazeModel | null
  /** #166: learn each person's own limits from their calibrate clips first. */
  adaptation?: AdaptationSettings | null
}
/** One setting for every frame, or one per frame (each held-out person's own fold). */
export type Settings = Setting | ((frame: Frame) => Setting)

// The calibrate clips behind each calibrations() result, by person and
// conditions, for adaptation to learn from.
const calibrationFrames = new WeakMap<Map<string, Calibration>, Map<string, FaceFeatures[]>>()

/** A calibration per participant and set of conditions, from their "calibrate" clips. */
export function calibrations(frames: Frame[]): Map<string, Calibration> {
  const groups = new Map<string, FaceFeatures[]>()
  for (const f of frames.filter(f => f.label === 'calibrate')) {
    const key = calibrationKey(f)
    groups.set(key, [...(groups.get(key) ?? []), f.features])
  }
  const result = new Map<string, Calibration>()
  for (const [key, group] of groups) {
    const c = calibrate(group)
    if (c) result.set(key, c)
  }
  calibrationFrames.set(result, groups)
  return result
}
const calibrationKey = (f: Frame) => [f.participant, ...Object.values(f.conditions)].join('|')

export function observe(frames: Frame[], settings: Settings, calibrationsByKey = calibrations(frames)): FaceObservation[] {
  const learned = new Map<string, ReturnType<typeof startAdaptation>>()
  return frames.map(f => {
    const setting = typeof settings === 'function' ? settings(f) : settings
    const calibration = setting.calibrated ? calibrationsByKey.get(calibrationKey(f)) ?? null : null
    const thresholds = setting.calibrated && !calibration ? setting.uncalibrated ?? setting.thresholds : setting.thresholds
    if (!setting.adaptation) return classifyFace(f.features, thresholds, calibration, setting.gaze ?? null)
    // The recordings' only sure "looking at the screen" moments are the
    // calibrate clips, so adaptation learns from those (as the browser does
    // after calibrating), never from the clips it is scored on.
    const key = `${calibrationKey(f)}|${setting.calibrated}`
    let state = learned.get(key)
    if (!state) {
      state = startAdaptation(calibration)
      for (const g of calibrationFrames.get(calibrationsByKey)?.get(calibrationKey(f)) ?? []) state = learn(state, g, thresholds, setting.adaptation, setting.gaze ?? null)
      learned.set(key, state)
    }
    return classifyAdaptive(f.features, state, thresholds, setting.adaptation, setting.gaze ?? null)
  })
}

export interface Scores { face: Counts; looking: Counts }

/**
 * Face presence and looking-at-screen counts. Calibration clips are not
 * scored. Spoof clips (#165) count for face presence but not for looking: the
 * gaze rule cannot tell a photo from a face, which is the liveness check's
 * job, so they would blur the gaze numbers (#166) without measuring gaze.
 */
export function score(frames: Frame[], setting: Settings, calibrationsByKey = calibrations(frames)): Scores {
  const scored = frames.filter(f => f.label !== 'calibrate')
  const seen = observe(scored, setting, calibrationsByKey)
  const gaze = scored.map((f, i) => ({ f, s: seen[i] })).filter(({ f }) => !isSpoofLabel(f.label))
  return {
    face: count(scored.map((f, i) => ({ truth: faceTruth(f.label), predicted: seen[i].face }))),
    looking: count(gaze.map(({ f, s }) => ({ truth: lookingTruth(f.label), predicted: s.forward }))),
  }
}

/** Rows: what was asked. Columns: on screen, away, no reading. */
export function confusion(frames: Frame[], setting: Settings, calibrationsByKey = calibrations(frames)) {
  const scored = frames.filter(f => f.label !== 'calibrate')
  const seen = observe(scored, setting, calibrationsByKey)
  const table = new Map<Label, { onScreen: number; away: number; noReading: number }>()
  scored.forEach((f, i) => {
    const row = table.get(f.label) ?? { onScreen: 0, away: 0, noReading: 0 }
    const forward = seen[i].forward
    if (forward === null) row.noReading++
    else if (forward) row.onScreen++
    else row.away++
    table.set(f.label, row)
  })
  return table
}

// -- held-out folds and tuning -----------------------------------------------------

/** One round of the evaluation: tune on `tune`, report on `test`. */
export interface Fold { held: string; tune: Frame[]; test: Frame[] }

/**
 * Leave one participant out: each participant in turn is the test set and the
 * limits are tuned on everyone else, so every result is on a person the limits
 * never saw, and every person gets a result. With fewer than three
 * participants there is no fair split by person, so every third clip is held
 * out instead and the report says so.
 */
export function folds(frames: Frame[]): { folds: Fold[]; by: 'participant' | 'clip' } {
  const people = [...new Set(frames.map(f => f.participant))].sort()
  if (people.length >= 3) {
    return {
      by: 'participant',
      folds: people.map(held => ({
        held, tune: frames.filter(f => f.participant !== held), test: frames.filter(f => f.participant === held),
      })),
    }
  }
  const clips = [...new Set(frames.map(f => f.clip))].sort()
  const held = new Set(clips.filter((_, i) => i % 3 === 2))
  return { by: 'clip', folds: [{ held: 'held-out clips', tune: frames.filter(f => !held.has(f.clip)), test: frames.filter(f => held.has(f.clip)) }] }
}

/** #63's hand-set limits: the "before" of every comparison, and where tuning starts. */
export const ORIGINAL_THRESHOLDS: Thresholds = {
  ...DEFAULT_THRESHOLDS, maxYawDegrees: 25, maxPitchDegrees: 20, maxRollDegrees: 20, irisX: [0.2, 0.8],
}

/** The angle limits tried. The proxies, eye and face-size limits stay as they are. */
export const GRID = {
  maxYawDegrees: [10, 15, 20, 25, 30, 35],
  maxPitchDegrees: [8, 12, 16, 20, 25, 30],
  maxRollDegrees: [15, 20, 30],
  irisX: [[0.2, 0.8], [0.25, 0.75], [0.3, 0.7], [0.15, 0.85]] as [number, number][],
}

/** The thresholds with the best balanced accuracy on `frames`; ties keep the earlier (stricter) one. */
export function tune(
  frames: Frame[], calibrated: boolean, uncalibrated?: Thresholds,
): { thresholds: Thresholds; balancedAccuracy: number | null } {
  const byKey = calibrations(frames)
  let best = { thresholds: ORIGINAL_THRESHOLDS, balancedAccuracy: balancedAccuracy(score(frames, { thresholds: ORIGINAL_THRESHOLDS, calibrated, uncalibrated }, byKey).looking) }
  for (const maxYawDegrees of GRID.maxYawDegrees) {
    for (const maxPitchDegrees of GRID.maxPitchDegrees) {
      for (const maxRollDegrees of GRID.maxRollDegrees) {
        for (const irisX of GRID.irisX) {
          const thresholds = { ...ORIGINAL_THRESHOLDS, maxYawDegrees, maxPitchDegrees, maxRollDegrees, irisX }
          const value = balancedAccuracy(score(frames, { thresholds, calibrated, uncalibrated }, byKey).looking)
          if (value !== null && (best.balancedAccuracy === null || value > best.balancedAccuracy)) {
            best = { thresholds, balancedAccuracy: value }
          }
        }
      }
    }
  }
  return best
}

/**
 * #166: the gaze model's k per axis, and the gaze limits, tried with
 * calibration on (the iris centre is the student's own). k may be negative:
 * which way it runs depends on MediaPipe's axes, and the data decides.
 */
export const GAZE_GRID = {
  kYaw: [-150, -120, -90, -60, -30, 0, 30, 60, 90, 120, 150],
  // Left-right only. Iris height is unreliable: looking down lowers the
  // eyelids over the iris (P1, P2, P3), and on the first three participants a
  // fitted kPitch flipped sign between rounds (+60, +60, -60) and made the
  // held-out person worse (P3: 77.9% with it, 84.8% without).
  kPitch: [0],
  maxYawDegrees: [10, 15, 20, 25],
  maxPitchDegrees: [12, 16, 20, 25],
  maxEyeDisagreement: 0.15,
  maxRollDegrees: 45,
}

/** The gaze model and limits with the best balanced accuracy on `frames`; ties keep the earlier one. */
export function tuneGaze(
  frames: Frame[], base: Thresholds, uncalibrated: Thresholds, calibrated = true,
): { gaze: GazeModel; thresholds: Thresholds; balancedAccuracy: number | null } {
  const byKey = calibrations(frames)
  let best: { gaze: GazeModel; thresholds: Thresholds; balancedAccuracy: number | null } | null = null
  for (const kYaw of GAZE_GRID.kYaw) {
    for (const kPitch of GAZE_GRID.kPitch) {
      const gaze = { kYaw, kPitch, maxEyeDisagreement: GAZE_GRID.maxEyeDisagreement, maxRollDegrees: GAZE_GRID.maxRollDegrees }
      for (const maxYawDegrees of GAZE_GRID.maxYawDegrees) {
        for (const maxPitchDegrees of GAZE_GRID.maxPitchDegrees) {
          const thresholds = { ...base, maxYawDegrees, maxPitchDegrees }
          const value = balancedAccuracy(score(frames, { thresholds, calibrated, uncalibrated, gaze }, byKey).looking)
          if (value !== null && (best === null || best.balancedAccuracy === null || value > best.balancedAccuracy)) {
            best = { gaze, thresholds, balancedAccuracy: value }
          }
        }
      }
    }
  }
  return best ?? { gaze: { kYaw: 0, kPitch: 0, maxEyeDisagreement: GAZE_GRID.maxEyeDisagreement, maxRollDegrees: GAZE_GRID.maxRollDegrees }, thresholds: base, balancedAccuracy: null }
}

// -- confidence intervals ----------------------------------------------------------

/** A small seeded generator, so the same recordings give the same intervals. */
export function seeded(seed: number): () => number {
  let state = seed >>> 0
  return () => {
    state = (state + 0x6d2b79f5) >>> 0
    let x = state
    x = Math.imul(x ^ (x >>> 15), x | 1)
    x ^= x + Math.imul(x ^ (x >>> 7), x | 61)
    return ((x ^ (x >>> 14)) >>> 0) / 4294967296
  }
}

/**
 * A 95% bootstrap interval for `metric`, resampling whole clips rather than
 * frames: frames from one clip are near copies of each other, so resampling
 * them would make the interval look far tighter than the data allows.
 */
export function bootstrap(
  frames: Frame[],
  metric: (sample: Frame[]) => number | null,
  rounds = 1000,
  seed = 0,
): [number, number] | null {
  const clips = new Map<string, Frame[]>()
  for (const f of frames) clips.set(`${f.participant}/${f.clip}`, [...(clips.get(`${f.participant}/${f.clip}`) ?? []), f])
  const groups = [...clips.values()]
  if (groups.length < 2) return null
  const random = seeded(seed)
  const values: number[] = []
  for (let r = 0; r < rounds; r++) {
    const sample: Frame[] = []
    for (let i = 0; i < groups.length; i++) sample.push(...groups[Math.floor(random() * groups.length)])
    const value = metric(sample)
    if (value !== null) values.push(value)
  }
  if (values.length < rounds / 2) return null
  values.sort((a, b) => a - b)
  return [values[Math.floor(values.length * 0.025)], values[Math.min(values.length - 1, Math.floor(values.length * 0.975))]]
}

// -- anti-spoofing (#165) --------------------------------------------------------

/**
 * Replays the browser's vote (liveness.ts) over one clip's frames in time
 * order: a check every `everyMs` using that frame's recorded score. True where
 * the face would be rejected as not live.
 */
export function replayLiveness(clip: Frame[], s: LivenessSettings): boolean[] {
  let state = startLiveness()
  return clip.map(f => {
    const ms = f.t * 1000
    state = noteFrame(state, f.features.faces, ms, s)
    if (f.features.faces === 1 && dueForCheck(state, ms, s)) state = recordCheck(state, f.live ?? Number.NaN, ms, s)
    return isSpoof(state, s)
  })
}

export interface LivenessCounts {
  /** Frames with one live face, and how many of them were rejected. */
  liveFrames: number; liveRejected: number
  /** Frames with one spoofed face, and how many of them were caught. */
  spoofFrames: number; spoofCaught: number
  /** Live clips, and how many had any frame rejected (what a student would notice). */
  liveClips: number; liveClipsRejected: number
}

const clipGroups = (frames: Frame[]) => {
  const clips = new Map<string, Frame[]>()
  for (const f of frames) clips.set(`${f.participant}/${f.clip}`, [...(clips.get(`${f.participant}/${f.clip}`) ?? []), f])
  return [...clips.values()].map(c => [...c].sort((a, b) => a.t - b.t))
}

/** Only frames with one face count: no face or two faces is not a liveness question. */
export function livenessCounts(frames: Frame[], s: LivenessSettings): LivenessCounts {
  const c: LivenessCounts = { liveFrames: 0, liveRejected: 0, spoofFrames: 0, spoofCaught: 0, liveClips: 0, liveClipsRejected: 0 }
  for (const clip of clipGroups(frames)) {
    const rejected = replayLiveness(clip, s)
    const spoof = isSpoofLabel(clip[0].label)
    let any = false
    let counted = false
    clip.forEach((f, i) => {
      if (f.features.faces !== 1) return
      counted = true
      if (spoof) { c.spoofFrames += 1; if (rejected[i]) c.spoofCaught += 1 }
      else { c.liveFrames += 1; if (rejected[i]) { c.liveRejected += 1; any = true } }
    })
    if (!spoof && counted) { c.liveClips += 1; if (any) c.liveClipsRejected += 1 }
  }
  return c
}

/** Live faces wrongly rejected: the number that must stay very low. */
export const falseRejection = (c: LivenessCounts) => c.liveFrames ? c.liveRejected / c.liveFrames : null
/** Photos and videos caught. */
export const spoofCatch = (c: LivenessCounts) => c.spoofFrames ? c.spoofCaught / c.spoofFrames : null

/** The #165 acceptance bar to agree as a team: under 2% of live faces rejected. */
export const MAX_FALSE_REJECTION = 0.02

export const LIVENESS_GRID = {
  everyMs: [1000, 2000, 3000],
  window: [2, 3, 4],
  spoofBelow: [0.05, 0.1, 0.2, 0.3, 0.5],
}

/**
 * The settings that catch the most spoofs while rejecting under
 * MAX_FALSE_REJECTION of live faces. If none get under the bar, the one that
 * rejects the fewest live faces (ties: the more cautious one), so the result
 * never trades students for spoofs.
 */
export function tuneLiveness(frames: Frame[], grid = LIVENESS_GRID): { settings: LivenessSettings; counts: LivenessCounts; meetsBar: boolean } {
  let best: { settings: LivenessSettings; counts: LivenessCounts; meetsBar: boolean } | null = null
  const better = (a: NonNullable<typeof best>, b: typeof best) => {
    if (!b) return true
    if (a.meetsBar !== b.meetsBar) return a.meetsBar
    const [fa, fb] = [falseRejection(a.counts) ?? 0, falseRejection(b.counts) ?? 0]
    if (!a.meetsBar) return fa < fb || (fa === fb && a.settings.spoofBelow < b.settings.spoofBelow)
    const [ca, cb] = [spoofCatch(a.counts) ?? 0, spoofCatch(b.counts) ?? 0]
    return ca > cb || (ca === cb && fa < fb)
  }
  for (const everyMs of grid.everyMs) for (const window of grid.window) for (const spoofBelow of grid.spoofBelow) {
    const settings = { everyMs, window, spoofBelow }
    const counts = livenessCounts(frames, settings)
    const frr = falseRejection(counts)
    const candidate = { settings, counts, meetsBar: frr !== null && frr < MAX_FALSE_REJECTION }
    if (better(candidate, best)) best = candidate
  }
  return best!
}
