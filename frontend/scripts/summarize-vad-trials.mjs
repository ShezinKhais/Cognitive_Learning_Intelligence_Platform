import { readFile } from 'node:fs/promises'

const files = process.argv.slice(2)
if (!files.length) throw new Error('Usage: node scripts/summarize-vad-trials.mjs <trial.json> ...')

const participants = new Set()
const groups = new Map()
function tally(group, trial) {
  const counts = groups.get(group) ?? {
    truePositive: 0, falseNegative: 0, falsePositive: 0, trueNegative: 0,
    unavailableSpeech: 0, unavailableQuiet: 0, trials: 0,
  }
  if (trial.expected === 'speaking') {
    counts.truePositive += trial.speaking
    counts.falseNegative += trial.quiet
    counts.unavailableSpeech += trial.unavailable
  } else {
    counts.falsePositive += trial.speaking
    counts.trueNegative += trial.quiet
    counts.unavailableQuiet += trial.unavailable
  }
  counts.trials++
  groups.set(group, counts)
}

for (const file of files) {
  const { participant, interval_ms, trials } = JSON.parse(await readFile(file, 'utf8'))
  if (typeof participant !== 'string' || !/^[a-z0-9-]{1,20}$/i.test(participant) ||
      interval_ms !== 250 || !Array.isArray(trials) || !trials.length) {
    throw new Error(`Invalid recorder export: ${file}`)
  }
  const code = participant.toUpperCase()
  if (participants.has(code)) throw new Error(`Use one export per participant: ${code}`)
  participants.add(code)
  for (const trial of trials) {
    const counts = [trial?.speaking, trial?.quiet, trial?.unavailable]
    if (!['standard', 'lower-spec'].includes(trial?.device) ||
        !['quiet', 'noise', 'other-speaker'].includes(trial?.condition) ||
        !['speaking', 'quiet'].includes(trial?.expected) ||
        !counts.every(count => Number.isInteger(count) && count >= 0) ||
        counts.reduce((sum, count) => sum + count, 0) !== 40) {
      throw new Error(`Invalid trial in ${file}`)
    }
    tally('all', trial)
    tally(`device:${trial.device}`, trial)
    tally(`condition:${trial.condition}`, trial)
    tally(`participant:${code}`, trial)
  }
}

function percent(part, total) {
  return total ? (100 * part / total).toFixed(1) + '%' : 'Unavailable'
}

console.log(`Participants: ${participants.size}. Rates use available samples only.`)
console.log('| Group | Trials | TP | FN | FP | TN | Missed speech | False speech | Unavailable speech | Unavailable quiet |')
console.log('|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|')
for (const [group, c] of groups) {
  const speech = c.truePositive + c.falseNegative
  const quiet = c.trueNegative + c.falsePositive
  console.log(`| ${group} | ${c.trials} | ${c.truePositive} | ${c.falseNegative} | ${c.falsePositive} | ${c.trueNegative} | ${percent(c.falseNegative, speech)} | ${percent(c.falsePositive, quiet)} | ${percent(c.unavailableSpeech, speech + c.unavailableSpeech)} | ${percent(c.unavailableQuiet, quiet + c.unavailableQuiet)} |`)
}
