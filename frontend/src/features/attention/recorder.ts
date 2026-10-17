// The recorder page (eval/attention-recorder.html), for #159. Runs the same
// face worker as the classroom, asks it for the features behind each
// observation, and keeps those with the label being acted out. The video is
// shown on this page only and never stored. Served by `npm run dev` at
// /eval/attention-recorder.html; not part of the built app.
import '../../index.css'
import { CONDITIONS, LABELS, framesToCsv, type Condition, type Frame, type Label } from './evaluation.ts'
import type { FaceFeatures } from './signals.ts'

const CLIP_SECONDS = 10
const FRAME_MS = 250
const assets = new URL(`${import.meta.env.BASE_URL}attention/`, location.origin).href

const $ = <T extends HTMLElement>(id: string) => document.getElementById(id) as T
const consent = $<HTMLInputElement>('consent')
const participant = $<HTMLInputElement>('participant')
const start = $<HTMLButtonElement>('start')
const stop = $<HTMLButtonElement>('stop')
const preview = $<HTMLVideoElement>('preview')
const status = $<HTMLParagraphElement>('status')
const counter = $<HTMLParagraphElement>('count')
const download = $<HTMLButtonElement>('download')
const discard = $<HTMLButtonElement>('discard')
const bar = $<HTMLDivElement>('bar')
const live = $<HTMLElement>('live')

const frames: Frame[] = []
let clips = 0
let stream: MediaStream | undefined
let worker: Worker | undefined
let timer: ReturnType<typeof setInterval> | undefined
let busy = false
let recording: { label: Label; clip: string; startedAt: number; conditions: Record<Condition, string> } | null = null

const selects = {} as Record<Condition, HTMLSelectElement>
for (const [name, values] of Object.entries(CONDITIONS) as [Condition, readonly string[]][]) {
  const label = document.createElement('label')
  label.className = 'text-sm font-medium capitalize'
  label.textContent = name
  const select = document.createElement('select')
  select.className = 'mt-1 block w-full rounded-lg border border-border bg-input-background px-2 py-1.5 text-sm'
  for (const value of values) select.append(new Option(value, value))
  label.append(select)
  $('conditions').append(label)
  selects[name] = select
}
const labelButtons: HTMLButtonElement[] = []
for (const [label, instruction] of Object.entries(LABELS) as [Label, string][]) {
  const button = document.createElement('button')
  button.className = 'rounded-lg border border-border px-3 py-2 text-left text-sm hover:bg-muted disabled:opacity-40'
  button.innerHTML = `<span class="font-semibold">${label}</span><span class="block text-xs text-muted-foreground">${instruction}</span>`
  button.disabled = true
  button.onclick = () => record(label)
  $('labels').append(button)
  labelButtons.push(button)
}

function refresh() {
  const on = Boolean(worker)
  start.disabled = on || !consent.checked
  stop.disabled = !on
  for (const button of labelButtons) button.disabled = !on || recording !== null || !/^P\d+$/.test(participant.value.trim())
  counter.textContent = `${clips} clips, ${frames.length} frames recorded.`
  download.disabled = discard.disabled = frames.length === 0
}
participant.oninput = refresh
// Unticking consent turns the camera off at once, not just the Start button.
consent.onchange = () => { if (!consent.checked && worker) stopCamera('Consent withdrawn. Camera off.'); else refresh() }

function record(label: Label) {
  clips += 1
  const conditions = Object.fromEntries(Object.entries(selects).map(([k, s]) => [k, s.value])) as Record<Condition, string>
  // No frame counts until the countdown ends and startedAt is set below.
  const clip = { label, clip: `c${clips}`, startedAt: Infinity, conditions }
  recording = clip
  status.textContent = `Get ready: ${LABELS[label]}`
  refresh()
  // Two seconds to get into position before frames count. The timers check
  // this is still the same clip, in case the camera was stopped meanwhile.
  setTimeout(() => {
    if (recording !== clip) return
    clip.startedAt = performance.now()
    status.textContent = `Recording: ${LABELS[label]}`
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

/** The numbers being recorded, live, so the tester can see the camera react. */
function show(features: FaceFeatures) {
  const value = (v: number | undefined) => v === undefined ? '–' : `${Math.round(v)}°`
  const cells: [string, string][] = [
    ['faces', String(features.faces)],
    ['yaw', value(features.pose?.yaw)],
    ['pitch', value(features.pose?.pitch)],
  ]
  live.innerHTML = cells.map(([name, v]) =>
    `<div class="rounded-lg bg-muted p-2"><dt class="text-muted-foreground">${name}</dt><dd class="text-base font-semibold">${v}</dd></div>`).join('')
}

function keep(features: FaceFeatures) {
  if (!recording || performance.now() < recording.startedAt) return
  frames.push({
    participant: participant.value.trim(),
    clip: recording.clip,
    label: recording.label,
    conditions: recording.conditions,
    t: (performance.now() - recording.startedAt) / 1000,
    features,
  })
  refresh()
}

start.onclick = async () => {
  stream = await navigator.mediaDevices.getUserMedia({ video: { width: { ideal: 320 }, height: { ideal: 240 } }, audio: false })
  preview.srcObject = stream
  await preview.play()
  worker = new Worker(new URL('./face.worker.ts', import.meta.url), { type: 'module' })
  worker.onmessage = event => {
    if (event.data.type === 'ready') { status.textContent = 'Camera ready. Pick a clip to record.'; sendFrames() }
    else if (event.data.type === 'observation') { busy = false; if (event.data.features) { show(event.data.features); keep(event.data.features) } }
    else if (event.data.type === 'error') { busy = false; status.textContent = 'A frame could not be read; recording continues.' }
  }
  worker.postMessage({ type: 'init', base: assets, withFeatures: true })
  status.textContent = 'Loading the face model…'
  refresh()
}

/** Frames go to the worker only once its model is ready: one sent before is dropped and never answered. */
function sendFrames() {
  // The classroom's frame rate, so the recordings match what students send.
  timer = setInterval(async () => {
    if (busy || !worker || preview.readyState < 2) return
    busy = true
    try {
      const frame = await createImageBitmap(preview)
      worker.postMessage({ type: 'frame', frame, timestamp: performance.now() }, [frame])
    } catch { busy = false }
  }, FRAME_MS)
}

function stopCamera(message: string) {
  clearInterval(timer)
  worker?.terminate()
  worker = undefined
  busy = false
  stream?.getTracks().forEach(track => track.stop())
  preview.srcObject = null
  recording = null
  bar.style.transition = 'none'
  bar.style.width = '0%'
  status.textContent = message
  refresh()
}
stop.onclick = () => stopCamera('Camera off.')

download.onclick = () => {
  const name = `attention_${participant.value.trim() || 'P'}_${new Date().toISOString().slice(0, 16).replace(/[:T]/g, '-')}.csv`
  const link = document.createElement('a')
  link.href = URL.createObjectURL(new Blob([framesToCsv(frames)], { type: 'text/csv' }))
  link.download = name
  link.click()
  URL.revokeObjectURL(link.href)
}

discard.onclick = () => {
  frames.length = 0
  clips = 0
  refresh()
}
