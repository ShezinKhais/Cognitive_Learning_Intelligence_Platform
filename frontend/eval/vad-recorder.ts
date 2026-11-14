import { startMicrophone } from '../src/features/attention/localSensors'

type Trial = {
  device: string
  condition: string
  expected: 'speaking' | 'quiet'
  speaking: number
  quiet: number
  unavailable: number
}

const participant = document.querySelector<HTMLInputElement>('#participant')!
const consent = document.querySelector<HTMLInputElement>('#consent')!
const device = document.querySelector<HTMLSelectElement>('#device')!
const condition = document.querySelector<HTMLSelectElement>('#condition')!
const start = document.querySelector<HTMLButtonElement>('#start')!
const stop = document.querySelector<HTMLButtonElement>('#stop')!
const speaking = document.querySelector<HTMLButtonElement>('#speaking')!
const quiet = document.querySelector<HTMLButtonElement>('#quiet')!
const download = document.querySelector<HTMLButtonElement>('#download')!
const status = document.querySelector<HTMLParagraphElement>('#status')!

const intervalMs = 250
const samplesPerTrial = 40
const trials: Trial[] = []
let capture: AbortController | undefined
let timer: number | undefined
let latest: { speaking: boolean | null; at: number } | undefined

function release(message: string) {
  capture?.abort()
  capture = undefined
  latest = undefined
  window.clearInterval(timer)
  start.disabled = false
  stop.disabled = speaking.disabled = quiet.disabled = true
  download.disabled = trials.length === 0
  status.textContent = message
}

start.onclick = async () => {
  if (!consent.checked || !/^[a-z0-9-]{1,20}$/i.test(participant.value)) {
    status.textContent = 'Enter your assigned code and tick consent.'
    return
  }
  const request = new AbortController()
  capture = request
  start.disabled = true
  stop.disabled = false
  status.textContent = 'Starting microphone…'
  try {
    await startMicrophone(
      request.signal,
      value => { latest = { speaking: value, at: performance.now() } },
      () => { if (capture === request) release('The microphone stopped.') },
    )
    if (capture !== request) return
    participant.readOnly = true
    speaking.disabled = quiet.disabled = false
    status.textContent = 'Microphone active. Choose a trial.'
  } catch {
    if (capture === request) release('Could not start the microphone.')
  }
}

function record(expected: Trial['expected']) {
  if (!capture || speaking.disabled || quiet.disabled) return
  speaking.disabled = quiet.disabled = download.disabled = true
  const trial: Trial = {
    device: device.value, condition: condition.value, expected,
    speaking: 0, quiet: 0, unavailable: 0,
  }
  latest = undefined
  status.textContent = expected === 'speaking' ? 'Speak now for ten seconds.' : 'Stay quiet for ten seconds.'
  let samples = 0
  timer = window.setInterval(() => {
    const value = latest && performance.now() - latest.at < 500 ? latest.speaking : null
    if (value === null) trial.unavailable++
    else if (value) trial.speaking++
    else trial.quiet++
    if (++samples < samplesPerTrial) return
    window.clearInterval(timer)
    trials.push(trial)
    speaking.disabled = quiet.disabled = download.disabled = false
    status.textContent = `Trial saved. ${trials.length} completed.`
  }, intervalMs)
}

speaking.onclick = () => record('speaking')
quiet.onclick = () => record('quiet')
stop.onclick = () => release('Microphone off.')
consent.onchange = () => { if (!consent.checked) release('Microphone off.') }
window.addEventListener('pagehide', () => release('Microphone off.'))
document.addEventListener('visibilitychange', () => {
  if (document.hidden && capture) release('Microphone off because the page was hidden.')
})

download.onclick = () => {
  const blob = new Blob([
    JSON.stringify({ participant: participant.value, interval_ms: intervalMs, trials }, null, 2),
  ], { type: 'application/json' })
  const url = URL.createObjectURL(blob)
  const link = document.createElement('a')
  link.href = url
  link.download = 'clip-vad-trials.json'
  link.click()
  window.setTimeout(() => URL.revokeObjectURL(url), 1000)
}
