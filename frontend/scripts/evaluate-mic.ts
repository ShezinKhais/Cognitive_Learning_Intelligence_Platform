// Microphone voice-detection evaluation (#253). Not a test.
//
// Reads the mic recorder's CSV files (eval/mic-recorder.html), cuts every clip
// into the classroom's 5-second windows and reports how often "speaking" was
// right: speech caught when the person spoke, false alarms when they did not,
// and windows with no reading, overall, per situation, per person and per
// condition. Run from frontend/:
//
//   node --experimental-strip-types scripts/evaluate-mic.ts ../backend/tests/eval/mic
//   node --experimental-strip-types scripts/evaluate-mic.ts ../backend/tests/eval/mic --out ../backend/tests/eval/mic/RESULTS.md
import { readdir, readFile, writeFile } from 'node:fs/promises'
import path from 'node:path'
import {
  MIC_CONDITIONS, MIC_LABELS, SPEECH_THRESHOLD, WINDOW_SECONDS, bootstrapClips, falseAlarmRate, micBalancedAccuracy, micWindows,
  parseMicCsv, scoreWindows, speechRecall, type MicCondition, type MicFrame, type MicLabel, type MicWindow,
} from '../eval/micEvaluation.ts'

const [folder, ...rest] = process.argv.slice(2)
if (!folder) throw new Error('usage: evaluate-mic.ts <folder of CSV files> [--out report.md]')
const out = rest[0] === '--out' ? rest[1] : undefined

const files = (await readdir(folder)).filter(name => name.endsWith('.csv')).sort()
if (!files.length) throw new Error(`no CSV files in ${folder}`)
const frames: MicFrame[] = []
// Clip codes restart at c1 in every download, so they are kept apart by file.
for (const name of files) frames.push(...parseMicCsv(await readFile(path.join(folder, name), 'utf8')).map(f => ({ ...f, clip: `${name}:${f.clip}` })))
const windows = micWindows(frames)

const pct = (v: number | null) => v === null ? '–' : `${Math.round(v * 100)}%`
const interval = (ws: MicWindow[], metric: (s: MicWindow[]) => number | null) => {
  const ci = bootstrapClips(ws, metric)
  return ci ? ` (${pct(ci[0])} to ${pct(ci[1])})` : ''
}
const recallOf = (ws: MicWindow[]) => speechRecall(scoreWindows(ws))
const alarmsOf = (ws: MicWindow[]) => falseAlarmRate(scoreWindows(ws))
const balancedOf = (ws: MicWindow[]) => micBalancedAccuracy(scoreWindows(ws))

function row(name: string, ws: MicWindow[], intervals = false): string {
  const s = scoreWindows(ws)
  const cell = (value: number | null, metric: (s: MicWindow[]) => number | null) =>
    `${pct(value)}${intervals && value !== null ? interval(ws, metric) : ''}`
  return `| ${name} | ${s.windows} | ${s.missing} | ${s.spoke ? `${s.caught} of ${s.spoke}` : '–'} · ${cell(speechRecall(s), recallOf)} | `
    + `${s.silent ? `${s.falseAlarms} of ${s.silent}` : '–'} · ${cell(falseAlarmRate(s), alarmsOf)} | ${cell(micBalancedAccuracy(s), balancedOf)} |`
}
const header = [
  '| | Windows | No reading | Speech caught | False alarms (silent but "speaking") | Balanced accuracy |',
  '|---|---|---|---|---|---|',
]
const group = <K extends string>(key: (w: MicWindow) => K) => {
  const groups = new Map<K, MicWindow[]>()
  for (const w of windows) groups.set(key(w), [...(groups.get(key(w)) ?? []), w])
  return [...groups.entries()].sort(([a], [b]) => a.localeCompare(b))
}

const participants = group(w => w.participant)
const worst = participants
  .map(([name, ws]) => ({ name, value: balancedOf(ws) }))
  .filter(p => p.value !== null)
  .sort((a, b) => a.value! - b.value!)[0]

const lines = [
  '# Microphone voice detection',
  '',
  `${participants.length} participants, ${new Set(windows.map(w => `${w.participant}/${w.clip}`)).size} clips, `
    + `${windows.length} windows of ${WINDOW_SECONDS} seconds, at the classroom's threshold of ${SPEECH_THRESHOLD}. A window counts as `
    + '"speaking" if any frame in it does, as in the classroom. 95% intervals resample whole clips.',
  '',
  '## Overall',
  '',
  ...header,
  row('All', windows, true),
  '',
  worst ? `Worst participant: ${worst.name}, balanced accuracy ${pct(worst.value)}.` : '',
  '',
  '## By situation',
  '',
  '| Situation | Person speaking? | Windows reported "speaking" |',
  '|---|---|---|',
  ...(Object.keys(MIC_LABELS) as MicLabel[]).flatMap(label => {
    const ws = windows.filter(w => w.label === label && w.detected !== null)
    return ws.length ? [`| ${label} | ${MIC_LABELS[label].speaking ? 'yes' : 'no'} | ${ws.filter(w => w.detected).length} of ${ws.length} |`] : []
  }),
  '',
  '## By participant',
  '',
  ...header,
  ...participants.map(([name, ws]) => row(name, ws)),
  '',
  '## By condition',
  '',
  ...header,
  ...(Object.keys(MIC_CONDITIONS) as MicCondition[]).flatMap(condition =>
    group(w => w.conditions[condition]).map(([value, ws]) => row(`${condition}: ${value}`, ws))),
  '',
  '## Other thresholds',
  '',
  'For information only: choosing a threshold from this table and reporting it on the same recordings would overstate it.',
  '',
  '| Threshold | Speech caught | False alarms |',
  '|---|---|---|',
  ...[0.5, 0.6, 0.7, 0.8, 0.9].map(t => {
    const s = scoreWindows(micWindows(frames, t))
    return `| ${t}${t === SPEECH_THRESHOLD ? ' (classroom)' : ''} | ${pct(speechRecall(s))} | ${pct(falseAlarmRate(s))} |`
  }),
  '',
]
const report = lines.join('\n')
console.log(report)
if (out) {
  await writeFile(out, report)
  console.log(`written to ${out}`)
}
