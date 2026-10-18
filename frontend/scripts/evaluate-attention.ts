// Camera attention evaluation (#159). Not a test.
//
// Reads the recorder's CSV files (eval/attention-recorder.html), replays every
// frame through classifyFace and, leaving one participant out at a time, tunes
// the angle limits on everyone else and reports on that person. Run from frontend/:
//
//   node --experimental-strip-types scripts/evaluate-attention.ts ../backend/tests/eval/cv
//   node --experimental-strip-types scripts/evaluate-attention.ts ../backend/tests/eval/cv --out ../backend/tests/eval/CV_EVALUATION.md
import { readdir, readFile, writeFile } from 'node:fs/promises'
import path from 'node:path'
import {
  CONDITIONS, LABELS, ORIGINAL_THRESHOLDS, balancedAccuracy, bootstrap, calibrations, confusion, coverage, folds, parseCsv,
  precision, recall, score, tune,
  type Condition, type Counts, type Frame, type Label, type Settings,
} from '../eval/evaluation.ts'
import { CALIBRATED_THRESHOLDS, DEFAULT_THRESHOLDS, type Thresholds } from '../src/features/attention/signals.ts'

const [folder, ...rest] = process.argv.slice(2)
if (!folder) throw new Error('usage: evaluate-attention.ts <folder of CSV files> [--out report.md]')
const out = rest[0] === '--out' ? rest[1] : undefined

const files = (await readdir(folder)).filter(name => name.endsWith('.csv')).sort()
if (!files.length) throw new Error(`no CSV files in ${folder}`)
const frames: Frame[] = []
// Clip codes restart at c1 in every download, so they are kept apart by file.
for (const name of files) frames.push(...parseCsv(await readFile(path.join(folder, name), 'utf8')).map(f => ({ ...f, clip: `${name}:${f.clip}` })))

// "Before" is #63's judgement: the landmark proxies, as if no pose came with the frame.
const withoutPose = (fs: Frame[]) => fs.map(f => ({ ...f, features: { ...f.features, pose: null } }))

// Each fold tunes on everyone but one participant (or on two thirds of the
// clips, with fewer than three people) and is judged on what it held out.
const { folds: rounds, by } = folds(frames)
const tuned = rounds.map(fold => ({ ...fold, plain: tune(fold.tune, false), calibrated: tune(fold.tune, true) }))
const testFrames = tuned.flatMap(fold => fold.test)
const foldOf = (f: Frame) => by === 'participant' ? tuned.find(fold => fold.held === f.participant)! : tuned[0]
const before = { thresholds: ORIGINAL_THRESHOLDS, calibrated: false }
const tunedPlain: Settings = f => ({ thresholds: foldOf(f).plain.thresholds, calibrated: false })
const tunedCalibrated: Settings = f => ({ thresholds: foldOf(f).calibrated.thresholds, calibrated: true })

interface Row { name: string; frames: Frame[]; setting: Settings }
const rows: Row[] = [
  { name: 'Before: landmark proxies (#63)', frames: withoutPose(testFrames), setting: before },
  { name: 'Pose angles, starting limits', frames: testFrames, setting: before },
  { name: 'After: pose angles, tuned limits', frames: testFrames, setting: tunedPlain },
  { name: 'After + calibration', frames: testFrames, setting: tunedCalibrated },
]

// What ships: the limits tuned on every recording.
const finalPlain = tune(frames, false)
const finalCalibrated = tune(frames, true)

const pct = (value: number | null) => value === null ? 'n/a' : `${(value * 100).toFixed(1)}%`
const ci = (interval: [number, number] | null) => interval ? ` (${pct(interval[0])}–${pct(interval[1])})` : ''
function metric(fs: Frame[], setting: Settings, pick: (s: ReturnType<typeof score>) => Counts, measure: (c: Counts) => number | null) {
  const byKey = calibrations(fs)
  const value = measure(pick(score(fs, setting, byKey)))
  const interval = bootstrap(fs, sample => measure(pick(score(sample, setting, byKey))))
  return `${pct(value)}${ci(interval)}`
}

const lines: string[] = []
const say = (line = '') => { lines.push(line); console.log(line) }

const people = [...new Set(frames.map(f => f.participant))].sort()
const clipsOf = (fs: Frame[]) => new Set(fs.map(f => `${f.participant}/${f.clip}`)).size
say('# Camera attention evaluation')
say()
say(`Issue #159. ${files.length} recording file(s), ${people.length} participant(s), ${clipsOf(frames)} clips, ${frames.length} frames.`)
say('Made with `scripts/evaluate-attention.ts`; recordings from `eval/attention-recorder.html` hold derived numbers only, no video.')
say()
say('## The recordings')
say()
say('| Label | What the person did | Clips | Frames |')
say('|---|---|---|---|')
for (const [label, instruction] of Object.entries(LABELS) as [Label, string][]) {
  const of = frames.filter(f => f.label === label)
  say(`| ${label} | ${instruction} | ${clipsOf(of)} | ${of.length} |`)
}
say()
say(by === 'participant'
  ? `Leave one participant out: ${people.length} rounds, each tuning the limits on ${people.length - 1} participants and testing on the one left out. Every result below is on a person the limits were not tuned on, and pools all ${people.length} rounds (${clipsOf(testFrames)} clips).`
  : `Fewer than 3 participants, so clips are held out instead of people: tuned on ${clipsOf(tuned[0].tune)} clips, tested on ${clipsOf(testFrames)} others. The same people are in both, so these numbers are optimistic.`)
say()
say('## Before and after (held-out, all rounds pooled)')
say()
say('95% intervals in brackets, from 1000 bootstrap resamples of whole clips.')
say()
say('| Setting | Face present: precision | Face present: recall | Looking at screen: precision | Looking at screen: recall | Frames with a gaze reading | Balanced accuracy |')
say('|---|---|---|---|---|---|---|')
for (const row of rows) {
  say(`| ${row.name} | ${metric(row.frames, row.setting, s => s.face, precision)} | ${metric(row.frames, row.setting, s => s.face, recall)} | ${metric(row.frames, row.setting, s => s.looking, precision)} | ${metric(row.frames, row.setting, s => s.looking, recall)} | ${metric(row.frames, row.setting, s => s.looking, coverage)} | ${metric(row.frames, row.setting, s => s.looking, balancedAccuracy)} |`)
}
say()
say('Balanced accuracy counts a frame with no gaze reading as "not looking", as a five-second window with no forward frames does; it is what tuning maximises. "Two faces" gives no reading at all by design.')
say()

if (by === 'participant') {
  const ba = (fs: Frame[], setting: Settings) => balancedAccuracy(score(fs, setting).looking)
  const limits = (t: Thresholds) => `${t.maxYawDegrees}° / ${t.maxPitchDegrees}° / ${t.maxRollDegrees}°`
  const perPerson = tuned.map(fold => ({
    held: fold.held,
    before: ba(withoutPose(fold.test), before),
    after: ba(fold.test, { thresholds: fold.plain.thresholds, calibrated: false }),
    calibrated: ba(fold.test, { thresholds: fold.calibrated.thresholds, calibrated: true }),
    fold,
  }))
  say('## Per participant')
  say()
  say('Balanced accuracy on each person, with the limits tuned on everyone else. Yaw / pitch / roll are those limits, so the spread shows how much they depend on who is in the tuning set.')
  say()
  say('| Held out | Clips | Before | After | After + calibration | Tuned limits (yaw / pitch / roll) | With calibration |')
  say('|---|---|---|---|---|---|---|')
  for (const p of perPerson) {
    say(`| ${p.held} | ${clipsOf(p.fold.test)} | ${pct(p.before)} | ${pct(p.after)} | ${pct(p.calibrated)} | ${limits(p.fold.plain.thresholds)} | ${limits(p.fold.calibrated.thresholds)} |`)
  }
  say()
  const worst = (pick: (p: typeof perPerson[number]) => number | null) => {
    const scored = perPerson.filter(p => pick(p) !== null)
    if (!scored.length) return 'n/a'
    const p = scored.reduce((a, b) => pick(b)! < pick(a)! ? b : a)
    return `${pct(pick(p))} (${p.held})`
  }
  say(`Worst participant: before ${worst(p => p.before)}, after ${worst(p => p.after)}, after + calibration ${worst(p => p.calibrated)}.`)
  say()
}

// Both tuned rows ship: one for students who calibrate, one for those who do not.
for (const chosen of [rows[2], rows[3]]) {
  say(`## What each label was read as (${chosen.name})`)
  say()
  say('| Label | On screen | Away | No reading |')
  say('|---|---|---|---|')
  for (const [label, row] of confusion(chosen.frames, chosen.setting)) {
    const total = row.onScreen + row.away + row.noReading
    say(`| ${label} | ${row.onScreen} (${pct(row.onScreen / total)}) | ${row.away} (${pct(row.away / total)}) | ${row.noReading} (${pct(row.noReading / total)}) |`)
  }
  say()
  say(`## By condition (${chosen.name}, held-out, all rounds pooled)`)
  say()
  say('| Condition | Value | Clips | Face present: recall | Looking: precision | Looking: recall |')
  say('|---|---|---|---|---|---|')
  for (const [condition, values] of Object.entries(CONDITIONS) as [Condition, readonly string[]][]) {
    for (const value of values) {
      const of = chosen.frames.filter(f => f.conditions[condition] === value)
      if (!of.length) continue
      say(`| ${condition} | ${value} | ${clipsOf(of)} | ${metric(of, chosen.setting, s => s.face, recall)} | ${metric(of, chosen.setting, s => s.looking, precision)} | ${metric(of, chosen.setting, s => s.looking, recall)} |`)
    }
  }
  say()
}
const show = (t: Thresholds) => `maxYawDegrees: ${t.maxYawDegrees}, maxPitchDegrees: ${t.maxPitchDegrees}, maxRollDegrees: ${t.maxRollDegrees}, irisX: [${t.irisX.join(', ')}]`
say('## Thresholds')
say()
say(`- Starting limits (#63): \`${show(ORIGINAL_THRESHOLDS)}\``)
say(`- Tuned on every recording, without calibration: \`${show(finalPlain.thresholds)}\` (balanced accuracy on those recordings ${pct(finalPlain.balancedAccuracy)})`)
say(`- Tuned on every recording, with calibration: \`${show(finalCalibrated.thresholds)}\` (${pct(finalCalibrated.balancedAccuracy)})`)
say()
say('These are the limits to ship. The held-out results above estimate how they do on a new person, since each round tuned the same way without that person.')
say()
say(`- Shipped in \`signals.ts\`: \`DEFAULT_THRESHOLDS\` ${show(DEFAULT_THRESHOLDS)}; \`CALIBRATED_THRESHOLDS\` ${show(CALIBRATED_THRESHOLDS)}.`)
say()
say('If the tuned values above differ from the shipped ones, copy them into `signals.ts` and the threshold test in `tests/attention.test.ts`.')
say()
say('## Limits')
say()
say(`- ${people.length} participants, all team members: a small sample of similar people, so the intervals are wide and the numbers may not hold for a whole class.`)
say('- Acted, not natural: people were told what to do for 10 seconds at a time.')
say('- "Looking at the screen" is a camera-facing proxy, not eye tracking, and never a measure of attention or understanding.')
say('- Fairness of the tuned thresholds across people is for Cyber 1 to sign off; devices and Teams are tested by Cyber 2.')

if (out) {
  await writeFile(out, lines.join('\n') + '\n')
  console.log(`\nwritten to ${out}`)
}
