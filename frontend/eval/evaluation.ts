// Camera attention evaluation (#159): how recorded frames are stored, and how
// well classifyFace does on them. Used by the recorder page
// (eval/attention-recorder.html) and scripts/evaluate-attention.ts; never by
// the classroom.
//
// A recording holds derived numbers per frame and the label the person was
// told to act out. No video, image or landmark is stored.
import {
  calibrate, classifyFace, DEFAULT_THRESHOLDS,
  type Calibration, type FaceFeatures, type FaceObservation, type Thresholds,
} from '../src/features/attention/signals.ts'

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
} as const
export type Label = keyof typeof LABELS

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
}

export const COLUMNS = [
  'participant', 'clip', 'label', 'glasses', 'lighting', 'position', 'distance', 't',
  'faces', 'valid', 'width', 'yaw_proxy', 'roll_proxy', 'yaw', 'pitch', 'roll',
  'l_width', 'l_open', 'l_iris_x', 'l_iris_y', 'r_width', 'r_open', 'r_iris_x', 'r_iris_y',
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
export const faceTruth = (label: Label) => label !== 'no_face'
/** Is the person looking at the screen? */
export const lookingTruth = (label: Label) => label === 'screen' || label === 'calibrate'

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

export interface Setting { thresholds: Thresholds; calibrated: boolean }
/** One setting for every frame, or one per frame (each held-out person's own fold). */
export type Settings = Setting | ((frame: Frame) => Setting)

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
  return result
}
const calibrationKey = (f: Frame) => [f.participant, ...Object.values(f.conditions)].join('|')

export function observe(frames: Frame[], settings: Settings, calibrationsByKey = calibrations(frames)): FaceObservation[] {
  return frames.map(f => {
    const setting = typeof settings === 'function' ? settings(f) : settings
    return classifyFace(
      f.features,
      setting.thresholds,
      setting.calibrated ? calibrationsByKey.get(calibrationKey(f)) ?? null : null,
    )
  })
}

export interface Scores { face: Counts; looking: Counts }

/** Face presence and looking-at-screen counts. Calibration clips are not scored. */
export function score(frames: Frame[], setting: Settings, calibrationsByKey = calibrations(frames)): Scores {
  const scored = frames.filter(f => f.label !== 'calibrate')
  const seen = observe(scored, setting, calibrationsByKey)
  return {
    face: count(scored.map((f, i) => ({ truth: faceTruth(f.label), predicted: seen[i].face }))),
    looking: count(scored.map((f, i) => ({ truth: lookingTruth(f.label), predicted: seen[i].forward }))),
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
export function tune(frames: Frame[], calibrated: boolean): { thresholds: Thresholds; balancedAccuracy: number | null } {
  const byKey = calibrations(frames)
  let best = { thresholds: ORIGINAL_THRESHOLDS, balancedAccuracy: balancedAccuracy(score(frames, { thresholds: ORIGINAL_THRESHOLDS, calibrated }, byKey).looking) }
  for (const maxYawDegrees of GRID.maxYawDegrees) {
    for (const maxPitchDegrees of GRID.maxPitchDegrees) {
      for (const maxRollDegrees of GRID.maxRollDegrees) {
        for (const irisX of GRID.irisX) {
          const thresholds = { ...ORIGINAL_THRESHOLDS, maxYawDegrees, maxPitchDegrees, maxRollDegrees, irisX }
          const value = balancedAccuracy(score(frames, { thresholds, calibrated }, byKey).looking)
          if (value !== null && (best.balancedAccuracy === null || value > best.balancedAccuracy)) {
            best = { thresholds, balancedAccuracy: value }
          }
        }
      }
    }
  }
  return best
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
