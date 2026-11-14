// Microphone voice-detection evaluation (#253): how recorded frames are stored,
// and how well "speaking" is judged on them. Used by the mic recorder page
// (eval/mic-recorder.html) and scripts/evaluate-mic.ts; never by the classroom.
//
// A recording holds, per voice-detection frame (about 32 ms), only the speech
// probability the model gave and the situation the person was asked to act
// out. No audio is stored.
import { SPEECH_THRESHOLD } from '../src/features/attention/signals.ts'
import { seeded } from './evaluation.ts'

/** What the person was asked to do during a clip, and whether they themselves were speaking. */
export const MIC_LABELS = {
  speaking: { speaking: true, instruction: 'Read the passage aloud at your normal volume' },
  speaking_quietly: { speaking: true, instruction: 'Read the passage aloud quietly, as you would in a library' },
  speaking_over_noise: { speaking: true, instruction: 'Read the passage aloud while music or a video plays in the background' },
  silent: { speaking: false, instruction: 'Sit quietly and do not speak' },
  typing: { speaking: false, instruction: 'Type on the keyboard without speaking' },
  noise: { speaking: false, instruction: 'Stay silent while music, a fan or other noise plays' },
  others_talking: { speaking: false, instruction: 'Stay silent while someone else talks nearby (or a video of a person talking plays)' },
} as const
export type MicLabel = keyof typeof MIC_LABELS

/** The setup of a clip. Recorded per clip so results can be split by condition. */
export const MIC_CONDITIONS = {
  microphone: ['built_in', 'headset'],
  room: ['quiet', 'noisy'],
  distance: ['near', 'far'],
  device: ['usual', 'weaker'],
} as const
export type MicCondition = keyof typeof MIC_CONDITIONS

export interface MicFrame {
  participant: string
  clip: string
  label: MicLabel
  conditions: Record<MicCondition, string>
  /** Seconds since the clip started. */
  t: number
  /** The model's speech probability, or null when the microphone gave nothing (muted). */
  probability: number | null
}

/** The classroom reports one summary every 5 seconds: speaking if any frame in it was speech. */
export const WINDOW_SECONDS = 5
export { SPEECH_THRESHOLD }

const COLUMNS = ['participant', 'clip', 'label', ...Object.keys(MIC_CONDITIONS), 't', 'probability'] as const

export function micFramesToCsv(frames: MicFrame[]): string {
  const row = (f: MicFrame) => [
    f.participant, f.clip, f.label, ...(Object.keys(MIC_CONDITIONS) as MicCondition[]).map(c => f.conditions[c]),
    f.t.toFixed(3), f.probability === null ? '' : f.probability.toFixed(4),
  ].join(',')
  return [COLUMNS.join(','), ...frames.map(row)].join('\n') + '\n'
}

export function parseMicCsv(text: string): MicFrame[] {
  const [header, ...lines] = text.trim().split(/\r?\n/)
  const names = header.split(',')
  return lines.filter(Boolean).map(line => {
    const cells = line.split(',')
    const get = (name: string) => cells[names.indexOf(name)] ?? ''
    const label = get('label')
    if (!(label in MIC_LABELS)) throw new Error(`unknown label "${label}"`)
    return {
      participant: get('participant'),
      clip: get('clip'),
      label: label as MicLabel,
      conditions: Object.fromEntries(Object.keys(MIC_CONDITIONS).map(c => [c, get(c)])) as Record<MicCondition, string>,
      t: Number(get('t')),
      probability: get('probability') === '' ? null : Number(get('probability')),
    }
  })
}

/** One 5-second summary, as the classroom would have sent it. */
export interface MicWindow {
  participant: string
  clip: string
  label: MicLabel
  conditions: Record<MicCondition, string>
  /** What the app would report: true, false, or null for no reading. */
  detected: boolean | null
  /** Whether the person was speaking. */
  expected: boolean
}

/**
 * Cut each clip into the classroom's 5-second windows. A window is "speaking"
 * if any frame in it reaches the threshold, and has no reading if the
 * microphone gave nothing, as in summary() in signals.ts. A last part shorter
 * than half a window is dropped: the classroom would merge it with the next.
 */
export function micWindows(frames: MicFrame[], threshold = SPEECH_THRESHOLD, seconds = WINDOW_SECONDS): MicWindow[] {
  const clips = new Map<string, MicFrame[]>()
  for (const f of frames) clips.set(`${f.participant}/${f.clip}`, [...(clips.get(`${f.participant}/${f.clip}`) ?? []), f])
  const windows: MicWindow[] = []
  for (const clip of clips.values()) {
    const end = Math.max(...clip.map(f => f.t))
    for (let start = 0; start < end; start += seconds) {
      const inside = clip.filter(f => f.t >= start && f.t < start + seconds)
      if (end - start < seconds / 2 || !inside.length) continue
      const read = inside.filter(f => f.probability !== null)
      const first = clip[0]
      windows.push({
        participant: first.participant,
        clip: first.clip,
        label: first.label,
        conditions: first.conditions,
        detected: read.length ? read.some(f => f.probability! >= threshold) : null,
        expected: MIC_LABELS[first.label].speaking,
      })
    }
  }
  return windows
}

export interface MicScore {
  windows: number
  /** Windows with no reading at all. */
  missing: number
  /** Of the windows where the person spoke, how many were reported speaking. */
  caught: number
  spoke: number
  /** Of the windows where the person was silent, how many were wrongly reported speaking. */
  falseAlarms: number
  silent: number
}

export function scoreWindows(windows: MicWindow[]): MicScore {
  const read = windows.filter(w => w.detected !== null)
  return {
    windows: windows.length,
    missing: windows.length - read.length,
    caught: read.filter(w => w.expected && w.detected).length,
    spoke: read.filter(w => w.expected).length,
    falseAlarms: read.filter(w => !w.expected && w.detected).length,
    silent: read.filter(w => !w.expected).length,
  }
}

/** Share of spoken windows reported as speaking (null with none). */
export const speechRecall = (s: MicScore) => s.spoke ? s.caught / s.spoke : null
/** Share of silent windows wrongly reported as speaking (null with none). */
export const falseAlarmRate = (s: MicScore) => s.silent ? s.falseAlarms / s.silent : null
/** Mean of recall and the true-negative rate, so a mostly-silent set cannot look good by always saying "silent". */
export function micBalancedAccuracy(s: MicScore): number | null {
  const recall = speechRecall(s)
  const alarms = falseAlarmRate(s)
  return recall === null || alarms === null ? null : (recall + (1 - alarms)) / 2
}

/**
 * A 95% bootstrap interval for `metric`, resampling whole clips: windows from
 * one clip are near copies of each other, so resampling them one by one would
 * make the interval far too narrow.
 */
export function bootstrapClips(
  windows: MicWindow[], metric: (sample: MicWindow[]) => number | null, rounds = 1000, seed = 0,
): [number, number] | null {
  const clips = new Map<string, MicWindow[]>()
  for (const w of windows) clips.set(`${w.participant}/${w.clip}`, [...(clips.get(`${w.participant}/${w.clip}`) ?? []), w])
  const groups = [...clips.values()]
  if (groups.length < 2) return null
  const random = seeded(seed)
  const values: number[] = []
  for (let r = 0; r < rounds; r++) {
    const sample: MicWindow[] = []
    for (let i = 0; i < groups.length; i++) sample.push(...groups[Math.floor(random() * groups.length)])
    const value = metric(sample)
    if (value !== null) values.push(value)
  }
  if (values.length < rounds / 2) return null
  values.sort((a, b) => a - b)
  return [values[Math.floor(values.length * 0.025)], values[Math.min(values.length - 1, Math.floor(values.length * 0.975))]]
}
