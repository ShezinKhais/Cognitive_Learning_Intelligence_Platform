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
  CONDITIONS, GAZE_LABELS, LABELS, MAX_FALSE_REJECTION, ORIGINAL_THRESHOLDS, SPOOF_LABELS, balancedAccuracy, bootstrap, calibrations, confusion,
  coverage, falseRejection, folds, isSpoofLabel, livenessCounts, observe, parseCsv, precision, recall, score, spoofCatch, tune, tuneGaze, tuneLiveness,
  type Condition, type Counts, type Frame, type Label, type LivenessCounts, type Settings,
} from '../eval/evaluation.ts'
import { LIVENESS, SUGGESTED_LIVENESS, type LivenessSettings } from '../src/features/attention/liveness.ts'
import {
  ADAPTATION, CALIBRATED_THRESHOLDS, DEFAULT_THRESHOLDS, GAZE_MODEL, SUGGESTED_ADAPTATION, type GazeModel, type Thresholds,
} from '../src/features/attention/signals.ts'

const [folder, ...rest] = process.argv.slice(2)
if (!folder) throw new Error('usage: evaluate-attention.ts <folder of CSV files> [--out report.md]')
const out = rest[0] === '--out' ? rest[1] : undefined

const files = (await readdir(folder)).filter(name => name.endsWith('.csv')).sort()
if (!files.length) throw new Error(`no CSV files in ${folder}`)
const allFrames: Frame[] = []
// Clip codes restart at c1 in every download, so they are kept apart by file.
for (const name of files) allFrames.push(...parseCsv(await readFile(path.join(folder, name), 'utf8')).map(f => ({ ...f, clip: `${name}:${f.clip}` })))

// #165's photo and video clips are judged on their own, below, so the #159
// and #166 numbers stay comparable with earlier reports.
const frames = allFrames.filter(f => !isSpoofLabel(f.label))

// "Before" is #63's judgement: the landmark proxies, as if no pose came with the frame.
const withoutPose = (fs: Frame[]) => fs.map(f => ({ ...f, features: { ...f.features, pose: null } }))

// Each fold tunes on everyone but one participant (or on two thirds of the
// clips, with fewer than three people) and is judged on what it held out.
const { folds: rounds, by } = folds(frames)
// With calibration on, a person without one gets the uncalibrated limits, as
// in the app; each fold uses its own, so nothing held out leaks in.
const tuned = rounds.map(fold => {
  const plain = tune(fold.tune, false)
  const calibrated = tune(fold.tune, true, plain.thresholds)
  // #166: k and the gaze limits, fitted on the same people, never the held-out one.
  return {
    ...fold, plain, calibrated, gaze: tuneGaze(fold.tune, calibrated.thresholds, plain.thresholds),
    // The same, for a classroom with no calibration step: every student judged
    // from straight ahead, with gaze limits tuned that way.
    gazeNoCalibration: tuneGaze(fold.tune, plain.thresholds, plain.thresholds, false),
  }
})
const testFrames = tuned.flatMap(fold => fold.test)
const foldOf = (f: Frame) => by === 'participant' ? tuned.find(fold => fold.held === f.participant)! : tuned[0]
const before = { thresholds: ORIGINAL_THRESHOLDS, calibrated: false }
const tunedPlain: Settings = f => ({ thresholds: foldOf(f).plain.thresholds, calibrated: false })
const tunedCalibrated: Settings = f => ({ thresholds: foldOf(f).calibrated.thresholds, calibrated: true, uncalibrated: foldOf(f).plain.thresholds })
// #166 rows. Adaptation uses the shipped settings if on, else the suggested ones.
const adaptation = ADAPTATION ?? SUGGESTED_ADAPTATION
const withGaze: Settings = f => ({ thresholds: foldOf(f).gaze.thresholds, calibrated: true, uncalibrated: foldOf(f).plain.thresholds, gaze: foldOf(f).gaze.gaze })
const withAdaptation: Settings = f => ({ ...(tunedCalibrated(f)), adaptation })
const withBoth: Settings = f => ({ ...(withGaze(f)), adaptation })
// Without calibration, adaptation still learns from the calibrate clips: the
// recordings' only sure "looking at the screen" moments, standing in for the
// moments the classroom learns from while a student types an answer.
const withGazeNoCalibration: Settings = f => ({ thresholds: foldOf(f).gazeNoCalibration.thresholds, calibrated: false, gaze: foldOf(f).gazeNoCalibration.gaze })
const withBothNoCalibration: Settings = f => ({ ...(withGazeNoCalibration(f)), adaptation })

interface Row { name: string; frames: Frame[]; setting: Settings }
const rows: Row[] = [
  { name: 'Before: landmark proxies (#63)', frames: withoutPose(testFrames), setting: before },
  { name: 'Pose angles, starting limits', frames: testFrames, setting: before },
  { name: 'After: pose angles, tuned limits', frames: testFrames, setting: tunedPlain },
  { name: 'After + calibration', frames: testFrames, setting: tunedCalibrated },
  { name: '#166: + combined head and eye gaze', frames: testFrames, setting: withGaze },
  { name: '#166: + adaptive limits', frames: testFrames, setting: withAdaptation },
  { name: '#166: + both', frames: testFrames, setting: withBoth },
  { name: '#166 without calibration: combined gaze', frames: testFrames, setting: withGazeNoCalibration },
  { name: '#166 without calibration: + adaptive limits', frames: testFrames, setting: withBothNoCalibration },
]

// What ships: the limits tuned on every recording.
const finalPlain = tune(frames, false)
const finalCalibrated = tune(frames, true, finalPlain.thresholds)
const finalGaze = tuneGaze(frames, finalCalibrated.thresholds, finalPlain.thresholds)
const finalGazeNoCalibration = tuneGaze(frames, finalPlain.thresholds, finalPlain.thresholds, false)

const gazeK = (g: GazeModel) => `${g.kYaw} / ${g.kPitch}`
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
say(`Issues #159, #165 and #166. ${files.length} recording file(s), ${people.length} participant(s), ${clipsOf(allFrames)} clips, ${allFrames.length} frames.`)
say('Made with `scripts/evaluate-attention.ts`; recordings from `eval/attention-recorder.html` hold derived numbers only, no video.')
say()
say('## The recordings')
say()
say('| Label | What the person did | Clips | Frames |')
say('|---|---|---|---|')
for (const [label, instruction] of Object.entries(LABELS) as [Label, string][]) {
  const of = allFrames.filter(f => f.label === label)
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
    calibrated: ba(fold.test, { thresholds: fold.calibrated.thresholds, calibrated: true, uncalibrated: fold.plain.thresholds }),
    gaze: ba(fold.test, withGaze),
    adaptive: ba(fold.test, withAdaptation),
    both: ba(fold.test, withBoth),
    bothNoCalibration: ba(fold.test, withBothNoCalibration),
    fold,
  }))
  say('## Per participant')
  say()
  say('Balanced accuracy on each person, with the limits tuned on everyone else. Yaw / pitch / roll are those limits, so the spread shows how much they depend on who is in the tuning set.')
  say()
  say('| Held out | Clips | Before | After | After + calibration | + gaze | + adaptive | + both | Both, no calibration | Tuned limits (yaw / pitch / roll) | With calibration | Gaze k (yaw / pitch) |')
  say('|---|---|---|---|---|---|---|---|---|---|---|---|')
  for (const p of perPerson) {
    say(`| ${p.held} | ${clipsOf(p.fold.test)} | ${pct(p.before)} | ${pct(p.after)} | ${pct(p.calibrated)} | ${pct(p.gaze)} | ${pct(p.adaptive)} | ${pct(p.both)} | ${pct(p.bothNoCalibration)} | ${limits(p.fold.plain.thresholds)} | ${limits(p.fold.calibrated.thresholds)} | ${gazeK(p.fold.gaze.gaze)} |`)
  }
  say()
  const worst = (pick: (p: typeof perPerson[number]) => number | null) => {
    const scored = perPerson.filter(p => pick(p) !== null)
    if (!scored.length) return 'n/a'
    const p = scored.reduce((a, b) => pick(b)! < pick(a)! ? b : a)
    return `${pct(pick(p))} (${p.held})`
  }
  say(`Worst participant: before ${worst(p => p.before)}, after ${worst(p => p.after)}, after + calibration ${worst(p => p.calibrated)}, + gaze ${worst(p => p.gaze)}, + adaptive ${worst(p => p.adaptive)}, + both ${worst(p => p.both)}, both without calibration ${worst(p => p.bothNoCalibration)}.`)
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
// #166: the two new labels on their own, so the #159 labels stay comparable.
const gazeFrames = testFrames.filter(f => GAZE_LABELS.includes(f.label))
say('## #166 labels on their own (held-out, all rounds pooled)')
say()
if (!gazeFrames.length) {
  say(`No \`${GAZE_LABELS.join('` or `')}\` clips recorded yet, so the combined gaze has nothing to be judged on here; record them with the recorder page first.`)
} else {
  say('Share of frames read as "on screen". `screen_head_turned` should be high, `away_eyes_only` low.')
  say()
  say('| Label | Clips | ' + rows.slice(3).map(r => r.name).join(' | ') + ' |')
  say('|---|---|' + rows.slice(3).map(() => '---').join('|') + '|')
  for (const label of GAZE_LABELS) {
    const of = gazeFrames.filter(f => f.label === label)
    if (!of.length) continue
    const share = (setting: Settings) => {
      const byKey = calibrations(testFrames)
      const onScreen = (fs: Frame[]) => {
        const seen = observe(fs, setting, byKey)
        return seen.length ? seen.filter(s => s.forward === true).length / seen.length : null
      }
      return `${pct(onScreen(of))}${ci(bootstrap(of, onScreen))}`
    }
    say(`| ${label} | ${clipsOf(of)} | ${rows.slice(3).map(r => share(r.setting)).join(' | ')} |`)
  }
}
say()

// Adaptation may only be fairer: count frames it turned from "on screen" to "away".
{
  const byKey = calibrations(testFrames)
  const scored = testFrames.filter(f => f.label !== 'calibrate')
  const fixed = observe(scored, tunedCalibrated, byKey)
  const adapted = observe(scored, withAdaptation, byKey)
  const harsher = fixed.filter((s, i) => s.forward === true && adapted[i].forward === false).length
  const noReading = fixed.filter((s, i) => s.forward === false && adapted[i].forward === null).length
  say('## Adaptation fairness check')
  say()
  say(`Of ${scored.length} held-out frames, adaptation turned ${harsher} from "on screen" to "away" (only a moved centre can do this; the learned limits are never stricter) and ${noReading} from "away" to "no reading" (a normal wider than the camera can measure).`)
  say()
  say(`Adaptation settings replayed: \`${JSON.stringify(adaptation)}\`${ADAPTATION ? ' (shipped)' : ' (suggested; `ADAPTATION` is off in `signals.ts`)'}. The recordings' only certain "looking" moments are the calibrate clips, so adaptation learns from those; the classroom also learns while a student types an answer, which these clips do not contain.`)
  say()
}

// -- #165: anti-spoofing ----------------------------------------------------------
{
  say('## Anti-spoofing (#165)')
  say()
  const scored = allFrames.filter(f => f.features.faces === 1 && typeof f.live === 'number')
  const spoofs = scored.filter(f => isSpoofLabel(f.label))
  const livePeople = [...new Set(scored.filter(f => !isSpoofLabel(f.label)).map(f => f.participant))].sort()
  if (!spoofs.length || livePeople.length < 2) {
    say(`Not enough recordings yet: ${clipsOf(spoofs)} spoof clip(s) (${SPOOF_LABELS.join(', ')}) and live scores from ${livePeople.length} participant(s). Record the spoof labels with the recorder, alongside live clips from the same people, then run this again. \`LIVENESS\` stays off until then.`)
    say()
  } else {
    // Leave one participant out, as above: settings tuned on the others,
    // judged on the person held out (their live and spoof clips both).
    const roundsL = livePeople.map(held => ({ held, tuned: tuneLiveness(scored.filter(f => f.participant !== held)), test: scored.filter(f => f.participant === held) }))
    const settingFor = (f: Frame) => roundsL.find(r => r.held === f.participant)?.tuned.settings ?? SUGGESTED_LIVENESS
    const heldCounts = (fs: Frame[]): LivenessCounts => {
      const total: LivenessCounts = { liveFrames: 0, liveRejected: 0, spoofFrames: 0, spoofCaught: 0, liveClips: 0, liveClipsRejected: 0 }
      for (const person of new Set(fs.map(f => f.participant))) {
        const mine = fs.filter(f => f.participant === person)
        const c = livenessCounts(mine, settingFor(mine[0]))
        for (const k of Object.keys(total) as (keyof LivenessCounts)[]) total[k] += c[k]
      }
      return total
    }
    const held = roundsL.flatMap(r => r.test)
    const cell = (fs: Frame[], measure: (c: LivenessCounts) => number | null) =>
      `${pct(measure(heldCounts(fs)))}${ci(bootstrap(fs, sample => measure(heldCounts(sample))))}`
    const fixedCell = (fs: Frame[], s: LivenessSettings, measure: (c: LivenessCounts) => number | null) =>
      `${pct(measure(livenessCounts(fs, s)))}${ci(bootstrap(fs, sample => measure(livenessCounts(sample, s))))}`
    say(`Held out one participant at a time (${livePeople.length} rounds). Acceptance bar to agree: under ${pct(MAX_FALSE_REJECTION)} of live faces rejected, in every condition. Only frames with exactly one face count.`)
    say()
    say('| Setting | Spoofs caught | Live faces wrongly rejected | Live clips with any rejection |')
    say('|---|---|---|---|')
    const clipShare = (c: LivenessCounts) => c.liveClips ? c.liveClipsRejected / c.liveClips : null
    say(`| Suggested \`${JSON.stringify(SUGGESTED_LIVENESS)}\` | ${fixedCell(held, SUGGESTED_LIVENESS, spoofCatch)} | ${fixedCell(held, SUGGESTED_LIVENESS, falseRejection)} | ${pct(clipShare(livenessCounts(held, SUGGESTED_LIVENESS)))} |`)
    say(`| Tuned without the held-out person | ${cell(held, spoofCatch)} | ${cell(held, falseRejection)} | ${pct(clipShare(heldCounts(held)))} |`)
    say()
    say('**Per participant** (tuned without them):')
    say()
    say('| Held out | Settings | Spoofs caught | Live faces wrongly rejected |')
    say('|---|---|---|---|')
    for (const r of roundsL) {
      const c = livenessCounts(r.test, r.tuned.settings)
      say(`| ${r.held} | \`${JSON.stringify(r.tuned.settings)}\`${r.tuned.meetsBar ? '' : ' (bar not met on tuning set)'} | ${pct(spoofCatch(c))} | ${pct(falseRejection(c))} |`)
    }
    say()
    say('**By condition** (tuned without the held-out person):')
    say()
    say('| Condition | Value | Spoofs caught | Live faces wrongly rejected |')
    say('|---|---|---|---|')
    for (const [name, values] of Object.entries(CONDITIONS) as [Condition, readonly string[]][]) {
      for (const value of values) {
        const of = held.filter(f => f.conditions[name] === value)
        if (of.length) say(`| ${name} | ${value} | ${cell(of, spoofCatch)} | ${cell(of, falseRejection)} |`)
      }
    }
    say()
    say('**By spoof type** (caught, tuned without the held-out person):')
    say()
    for (const label of SPOOF_LABELS) {
      const of = held.filter(f => f.label === label)
      if (of.length) say(`- ${label}: ${cell(of, spoofCatch)} of ${of.length} frames`)
    }
    say()
    const times = scored.map(f => f.liveMs).filter((v): v is number => typeof v === 'number').sort((a, b) => a - b)
    if (times.length) {
      const at = (q: number) => times[Math.min(times.length - 1, Math.floor(q * times.length))].toFixed(1)
      say(`Time per check in the browser: median ${at(0.5)} ms, 95th percentile ${at(0.95)} ms (${times.length} checks). Note the device each participant used: a slow laptop is the case that matters.`)
      say()
    }
    const final = tuneLiveness(scored)
    say(`Tuned on every recording: \`${JSON.stringify(final.settings)}\` (${final.meetsBar ? 'meets' : '**does not meet**'} the bar there: ${pct(spoofCatch(final.counts))} caught, ${pct(falseRejection(final.counts))} live rejected). Shipped \`LIVENESS\`: ${LIVENESS ? `\`${JSON.stringify(LIVENESS)}\`` : 'off'}.`)
    say()
  }
}

const show = (t: Thresholds) => `maxYawDegrees: ${t.maxYawDegrees}, maxPitchDegrees: ${t.maxPitchDegrees}, maxRollDegrees: ${t.maxRollDegrees}, irisX: [${t.irisX.join(', ')}]`
say('## Thresholds')
say()
say(`- Starting limits (#63): \`${show(ORIGINAL_THRESHOLDS)}\``)
say(`- Tuned on every recording, without calibration: \`${show(finalPlain.thresholds)}\` (balanced accuracy on those recordings ${pct(finalPlain.balancedAccuracy)})`)
say(`- Tuned on every recording, with calibration: \`${show(finalCalibrated.thresholds)}\` (${pct(finalCalibrated.balancedAccuracy)})`)
say(`- #166 gaze model tuned on every recording: \`kYaw: ${finalGaze.gaze.kYaw}, kPitch: ${finalGaze.gaze.kPitch}\`, gaze limits \`${show(finalGaze.thresholds)}\` (${pct(finalGaze.balancedAccuracy)}). Shipped \`GAZE_MODEL\`: ${GAZE_MODEL ? `\`${JSON.stringify(GAZE_MODEL)}\`` : 'off'}.`)
say(`- #166 gaze model tuned on every recording, without calibration: \`kYaw: ${finalGazeNoCalibration.gaze.kYaw}, kPitch: ${finalGazeNoCalibration.gaze.kPitch}\`, gaze limits \`${show(finalGazeNoCalibration.thresholds)}\` (${pct(finalGazeNoCalibration.balancedAccuracy)}).`)
say()
say('These are the limits to ship. The held-out results above estimate how they do on a new person, since each round tuned the same way without that person.')
say()
say(`- Shipped in \`signals.ts\`: \`DEFAULT_THRESHOLDS\` ${show(DEFAULT_THRESHOLDS)}; \`CALIBRATED_THRESHOLDS\` ${show(CALIBRATED_THRESHOLDS)}.`)
say()
say('If the tuned values above differ from the shipped ones, copy them into `signals.ts` and the threshold test in `tests/attention.test.ts`.')
say()
say('## Limits')
say()
say(`- ${people.length} participants: a small sample, so the intervals are wide and the numbers may not hold for a whole class.`)
say('- Acted, not natural: people were told what to do for 10 seconds at a time.')
say('- "Looking at the screen" is a camera-facing proxy, not eye tracking, and never a measure of attention or understanding.')
say('- Fairness of the tuned thresholds across people is for Cyber 1 to sign off; devices and Teams are tested by Cyber 2.')

if (out) {
  await writeFile(out, lines.join('\n') + '\n')
  console.log(`\nwritten to ${out}`)
}
