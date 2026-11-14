// The mic recorder page (mic-recorder.html), for #253. Opens the microphone and
// runs the voice detector exactly as the classroom does (startMicrophone in
// localSensors.ts), and keeps each frame's speech probability with the
// situation being acted out. No audio is stored. Served by `npm run dev` at
// /eval/mic-recorder.html; not part of the built app, so it lives outside src/.
import '../src/index.css'
import { saveFile } from './saveFile.ts'
import type { MicVAD } from '@ricky0123/vad-web'
import { MICROPHONE_AUDIO } from '../src/features/attention/localSensors.ts'
import { MIC_CONDITIONS, MIC_LABELS, SPEECH_THRESHOLD, micFramesToCsv, type MicCondition, type MicFrame, type MicLabel } from './micEvaluation.ts'

// 15 seconds gives three of the classroom's 5-second windows per clip.
const CLIP_SECONDS = 15
const assets = new URL(`${import.meta.env.BASE_URL}attention/`, location.origin).href

const $ = <T extends HTMLElement>(id: string) => document.getElementById(id) as T
const consent = $<HTMLInputElement>('consent')
const participant = $<HTMLInputElement>('participant')
const start = $<HTMLButtonElement>('start')
const stop = $<HTMLButtonElement>('stop')
const status = $<HTMLParagraphElement>('status')
const counter = $<HTMLParagraphElement>('count')
const download = $<HTMLButtonElement>('download')
const discard = $<HTMLButtonElement>('discard')
const bar = $<HTMLDivElement>('bar')
const meter = $<HTMLDivElement>('meter')
const reading = $<HTMLParagraphElement>('reading')

const frames: MicFrame[] = []
let clips = 0
let stream: MediaStream | undefined
let vad: MicVAD | undefined
// A start waits on the permission prompt and the model. Every stop bumps the
// generation, so a start that was stopped meanwhile drops what it gets.
let generation = 0
let starting = false
let recording: { label: MicLabel; clip: string; startedAt: number; conditions: Record<MicCondition, string> } | null = null

const selects = {} as Record<MicCondition, HTMLSelectElement>
for (const [name, values] of Object.entries(MIC_CONDITIONS) as [MicCondition, readonly string[]][]) {
  const label = document.createElement('label')
  label.className = 'text-sm font-medium capitalize'
  label.textContent = name
  const select = document.createElement('select')
  select.className = 'mt-1 block w-full rounded-lg border border-border bg-input-background px-2 py-1.5 text-sm'
  for (const value of values) select.append(new Option(value.replace('_', ' '), value))
  label.append(select)
  $('conditions').append(label)
  selects[name] = select
}

const labelButtons: HTMLButtonElement[] = []
for (const [label, { instruction }] of Object.entries(MIC_LABELS) as [MicLabel, { instruction: string }][]) {
  const button = document.createElement('button')
  button.className = 'rounded-lg border border-border px-3 py-2 text-left text-sm hover:bg-muted disabled:opacity-40'
  button.innerHTML = `<span class="font-semibold">${label}</span><span class="block text-xs text-muted-foreground">${instruction}</span>`
  button.disabled = true
  button.onclick = () => record(label)
  $('labels').append(button)
  labelButtons.push(button)
}

function refresh() {
  const on = Boolean(vad)
  start.disabled = on || starting || !consent.checked
  stop.disabled = !on && !starting
  for (const button of labelButtons) button.disabled = !on || recording !== null || !/^P\d+$/.test(participant.value.trim())
  counter.textContent = `${clips} clips, ${frames.length} frames recorded.`
  download.disabled = discard.disabled = frames.length === 0
}
participant.oninput = refresh
// Unticking consent turns the microphone off at once, not just the Start button.
consent.onchange = () => { if (!consent.checked && (vad || starting)) stopMicrophone('Consent withdrawn. Microphone off.'); else refresh() }

function record(label: MicLabel) {
  clips += 1
  const conditions = Object.fromEntries(Object.entries(selects).map(([k, s]) => [k, s.value])) as Record<MicCondition, string>
  // No frame counts until the countdown ends and startedAt is set below.
  const clip = { label, clip: `c${clips}`, startedAt: Infinity, conditions }
  recording = clip
  status.textContent = `Get ready: ${MIC_LABELS[label].instruction}`
  refresh()
  setTimeout(() => {
    if (recording !== clip) return
    clip.startedAt = performance.now()
    status.textContent = `Recording: ${MIC_LABELS[label].instruction}`
    bar.style.transition = 'none'
    bar.style.width = '0%'
    requestAnimationFrame(() => {
      bar.style.transition = `width ${CLIP_SECONDS}s linear`
      bar.style.width = '100%'
    })
    setTimeout(() => {
      if (recording !== clip) return
      recording = null
      bar.style.transition = 'none'
      bar.style.width = '0%'
      status.textContent = 'Clip saved. Pick the next one.'
      refresh()
    }, CLIP_SECONDS * 1000)
  }, 2000)
}

function keep(probability: number | null) {
  meter.style.width = `${Math.round((probability ?? 0) * 100)}%`
  reading.textContent = probability === null ? 'no reading' : `${probability.toFixed(2)} ${probability >= SPEECH_THRESHOLD ? '· speaking' : ''}`
  if (!recording || performance.now() < recording.startedAt) return
  frames.push({
    participant: participant.value.trim(),
    clip: recording.clip,
    label: recording.label,
    conditions: recording.conditions,
    t: (performance.now() - recording.startedAt) / 1000,
    probability,
  })
  refresh()
}

start.onclick = async () => {
  const mine = ++generation
  const current = () => mine === generation && consent.checked
  starting = true
  status.textContent = 'Waiting for the microphone…'
  refresh()
  let acquired: MediaStream
  try {
    acquired = await navigator.mediaDevices.getUserMedia({ audio: MICROPHONE_AUDIO, video: false })
  } catch {
    if (mine === generation) { starting = false; status.textContent = 'The microphone could not be started.'; refresh() }
    return
  }
  if (!current()) { acquired.getTracks().forEach(track => track.stop()); return }
  stream = acquired
  status.textContent = 'Loading the voice detector…'
  try {
    const { MicVAD } = await import('@ricky0123/vad-web')
    // The classroom's settings (startMicrophone), so the recordings match what students send.
    const created = await MicVAD.new({
      model: 'v5', startOnLoad: false,
      baseAssetPath: `${assets}vad/`, onnxWASMBasePath: `${assets}onnx/`,
      ortConfig: ort => { ort.env.wasm.numThreads = 1; ort.env.wasm.proxy = false },
      getStream: async () => acquired,
      resumeStream: async () => acquired,
      pauseStream: async value => value.getTracks().forEach(track => track.stop()),
      onFrameProcessed: ({ isSpeech }) => keep(acquired.getAudioTracks()[0]?.muted ? null : isSpeech),
      submitUserSpeechOnPause: false,
    })
    if (!current()) { void created.destroy(); acquired.getTracks().forEach(track => track.stop()); return }
    await created.start()
    vad = created
  } catch {
    if (mine === generation) stopMicrophone('The voice detector could not be loaded. Run `npm run prepare:attention` first.')
    return
  }
  starting = false
  status.textContent = 'Microphone ready. Pick a clip to record.'
  refresh()
}

function stopMicrophone(message: string) {
  generation += 1
  starting = false
  void vad?.destroy().catch(() => {})
  vad = undefined
  stream?.getTracks().forEach(track => track.stop())
  stream = undefined
  recording = null
  bar.style.transition = 'none'
  bar.style.width = '0%'
  meter.style.width = '0%'
  reading.textContent = '–'
  status.textContent = message
  refresh()
}
stop.onclick = () => stopMicrophone('Microphone off.')

download.onclick = () => {
  const name = `mic_${participant.value.trim() || 'P'}_${new Date().toISOString().slice(0, 16).replace(/[:T]/g, '-')}.csv`
  saveFile(name, micFramesToCsv(frames))
}

discard.onclick = () => {
  frames.length = 0
  clips = 0
  refresh()
}
