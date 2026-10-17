// Camera attention evaluation (#159). Not a test.
//
// Reads the recorder's CSV files (eval/attention-recorder.html), replays every
// frame through classifyFace, tunes the angle limits on some participants and
// reports on the others. Run from frontend/:
//
//   node --experimental-strip-types scripts/evaluate-attention.ts ../backend/tests/eval/cv
//   node --experimental-strip-types scripts/evaluate-attention.ts ../backend/tests/eval/cv --out ../backend/tests/eval/CV_EVALUATION.md
import { readdir, readFile, writeFile } from 'node:fs/promises'
import path from 'node:path'
import {
  CONDITIONS, LABELS, balancedAccuracy, bootstrap, calibrations, confusion, coverage, parseCsv,
  precision, recall, score, split, tune,
  type Condition, type Counts, type Frame, type Label, type Setting,
} from '../src/features/attention/evaluation.ts'
import { DEFAULT_THRESHOLDS, type Thresholds } from '../src/features/attention/signals.ts'

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

const { tune: tuneFrames, test: testFrames, by } = split(frames)
const tunedPlain = tune(tuneFrames, false)
const tunedCalibrated = tune(tuneFrames, true)

interface Row { name: string; frames: Frame[]; setting: Setting }
const rows: Row[] = [
  { name: 'Before: landmark proxies (#63)', frames: withoutPose(testFrames), setting: { thresholds: DEFAULT_THRESHOLDS, calibrated: false } },
  { name: 'Pose angles, starting limits', frames: testFrames, setting: { thresholds: DEFAULT_THRESHOLDS, calibrated: false } },
  { name: 'After: pose angles, tuned limits', frames: testFrames, setting: { thresholds: tunedPlain.thresholds, calibrated: false } },
  { name: 'After + calibration', frames: testFrames, setting: { thresholds: tunedCalibrated.thresholds, calibrated: true } },
]

const pct = (value: number | null) => value === null ? 'n/a' : `${(value * 100).toFixed(1)}%`
const ci = (interval: [number, number] | null) => interval ? ` (${pct(interval[0])}–${pct(interval[1])})` : ''
function metric(fs: Frame[], setting: Setting, pick: (s: ReturnType<typeof score>) => Counts, measure: (c: Counts) => number | null) {
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
  ? `Tuned on ${clipsOf(tuneFrames)} clips from ${new Set(tuneFrames.map(f => f.participant)).size} participants; every result below is on the ${clipsOf(testFrames)} clips of the ${new Set(testFrames.map(f => f.participant)).size} held-out participant(s), never used to tune.`
  : `Fewer than 3 participants, so clips are held out instead of people: tuned on ${clipsOf(tuneFrames)} clips, tested on ${clipsOf(testFrames)} others. The same people are in both, so these numbers are optimistic.`)
say()
say('## Before and after (held-out set)')
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

const chosen = rows[2]
say(`## What each label was read as (${chosen.name})`)
say()
say('| Label | On screen | Away | No reading |')
say('|---|---|---|---|')
for (const [label, row] of confusion(chosen.frames, chosen.setting)) {
  const total = row.onScreen + row.away + row.noReading
  say(`| ${label} | ${row.onScreen} (${pct(row.onScreen / total)}) | ${row.away} (${pct(row.away / total)}) | ${row.noReading} (${pct(row.noReading / total)}) |`)
}
say()
say(`## By condition (${chosen.name}, held-out set)`)
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
const show = (t: Thresholds) => `maxYawDegrees: ${t.maxYawDegrees}, maxPitchDegrees: ${t.maxPitchDegrees}, maxRollDegrees: ${t.maxRollDegrees}, irisX: [${t.irisX.join(', ')}]`
say('## Thresholds')
say()
say(`- Starting limits: \`${show(DEFAULT_THRESHOLDS)}\``)
say(`- Tuned without calibration: \`${show(tunedPlain.thresholds)}\` (balanced accuracy on the tuning set ${pct(tunedPlain.balancedAccuracy)})`)
say(`- Tuned with calibration: \`${show(tunedCalibrated.thresholds)}\` (${pct(tunedCalibrated.balancedAccuracy)})`)
say()
say('Copy the chosen values into `DEFAULT_THRESHOLDS` in `frontend/src/features/attention/signals.ts`, and the threshold test in `tests/attention.test.ts`.')
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
