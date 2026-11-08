import { useEffect, useRef, useState } from 'react'
import { apiAuthenticatedRequest } from '../../api'
import { buttonStyles } from '../../components/ui/button'
import { pcmWav } from './liveMicrophone'

interface Status {
  configured: boolean
  running: boolean
  session_running: boolean
  capture_id: string | null
  language: string
}
interface Capture {
  id: string
  stream: MediaStream
  context: AudioContext
  source: MediaStreamAudioSourceNode
  node: AudioWorkletNode
  abort: AbortController
  queue: { samples: Float32Array; started: number; sequence: number }[]
  working: boolean
  sequence: number
  epoch: number
}

function isHidden() { return document.visibilityState === 'hidden' }

export default function LiveTranscriptionControls({ sessionId, onUpdate }: { sessionId: string; onUpdate: () => void }) {
  const [status, setStatus] = useState<Status | null>(null)
  const [confirmed, setConfirmed] = useState(false)
  const [phase, setPhase] = useState<'off' | 'starting' | 'recording'>('off')
  const [error, setError] = useState<string | null>(null)
  const [last, setLast] = useState<string | null>(null)
  const capture = useRef<Capture | null>(null)
  const starting = useRef<{ stream?: MediaStream; context?: AudioContext; abort: AbortController } | null>(null)
  const attempt = useRef(0)
  const refresh = useRef(onUpdate)
  refresh.current = onUpdate
  const path = `/sessions/${sessionId}/live-transcription`

  function release(item: Capture) {
    item.abort.abort(); item.queue = []
    item.node.port.onmessage = null
    item.source.disconnect(); item.node.disconnect()
    item.stream.getTracks().forEach(track => track.stop())
    void item.context.close().catch(() => {})
    void apiAuthenticatedRequest(`${path}/${item.id}/stop`, { method: 'POST', keepalive: true }).catch(() => {})
  }

  function cancelStarting() {
    const pending = starting.current
    starting.current = null
    pending?.abort.abort()
    pending?.stream?.getTracks().forEach(track => track.stop())
    if (pending?.context) void pending.context.close().catch(() => {})
  }

  function stop(message?: string) {
    attempt.current++
    cancelStarting()
    const item = capture.current
    capture.current = null
    if (item) release(item)
    setPhase('off'); setConfirmed(false)
    if (message) setError(message)
    refresh.current()
  }

  useEffect(() => {
    let stopped = false
    let pending = false
    let statusAbort: AbortController | null = null
    const check = async () => {
      if (pending) return
      pending = true
      const captureAtRequest = capture.current?.id
      const generation = attempt.current
      const abort = new AbortController()
      statusAbort = abort
      const timeout = window.setTimeout(() => abort.abort(), 10_000)
      try {
        const found = await apiAuthenticatedRequest<Status>(path, { signal: abort.signal })
        if (stopped || attempt.current !== generation || capture.current?.id !== captureAtRequest) return
        setStatus(found)
        if ((!found.session_running || !found.configured) && starting.current || (capture.current && (!found.session_running || !found.configured || found.capture_id !== capture.current.id))) {
          stop('Live transcription stopped because the class or capture is no longer running.')
        }
      } catch {
        if (!stopped && attempt.current === generation && capture.current?.id === captureAtRequest) {
          setError('Could not check the class transcription status. Retry when the connection returns.')
          if (capture.current || starting.current) stop()
        }
      } finally { window.clearTimeout(timeout); if (statusAbort === abort) statusAbort = null; pending = false }
    }
    void check()
    const timer = window.setInterval(() => void check(), 3000)
    const hidden = () => { if (isHidden()) stop('Transcription stopped when this tab was hidden. Restart explicitly when ready.') }
    const pagehide = () => stop()
    document.addEventListener('visibilitychange', hidden)
    window.addEventListener('pagehide', pagehide)
    return () => {
      stopped = true; attempt.current++
      statusAbort?.abort()
      cancelStarting()
      window.clearInterval(timer)
      document.removeEventListener('visibilitychange', hidden); window.removeEventListener('pagehide', pagehide)
      const item = capture.current; capture.current = null
      if (item) release(item)
    }
    // Capture is tied to this session and must not restart on ordinary renders.
  }, [path])

  async function drain(item: Capture) {
    if (item.working) return
    item.working = true
    try {
      while (capture.current === item && item.queue.length) {
        const chunk = item.queue.shift()!
        const start = new Date(item.epoch + chunk.started * 1000).toISOString()
        const url = `${path}/${item.id}/chunks/${chunk.sequence}?started_at=${encodeURIComponent(start)}`
        await apiAuthenticatedRequest(url, {
          method: 'POST', headers: { 'Content-Type': 'audio/wav' },
          body: pcmWav(chunk.samples), signal: item.abort.signal,
        })
        if (capture.current !== item) return
        setLast(new Date().toLocaleTimeString())
        refresh.current()
      }
    } catch (caught) {
      if (!item.abort.signal.aborted && capture.current === item) stop(caught instanceof Error ? caught.message : 'Transcription failed. Check the server and restart.')
    } finally { item.working = false }
  }

  async function start() {
    if (!confirmed || phase !== 'off' || !status?.configured || !status.session_running) return
    const generation = ++attempt.current
    const pending = { abort: new AbortController() } as { stream?: MediaStream; context?: AudioContext; abort: AbortController }
    starting.current = pending
    setPhase('starting'); setError(null)
    let stream: MediaStream | undefined
    let context: AudioContext | undefined
    let id: string | undefined
    let setupTimer: number | undefined
    try {
      if (!isSecureContext || !navigator.mediaDevices?.getUserMedia || !window.AudioWorkletNode) throw new Error('Use a supported browser over HTTPS or localhost for lecturer microphone transcription.')
      stream = await navigator.mediaDevices.getUserMedia({ audio: { channelCount: 1, echoCancellation: true }, video: false })
      pending.stream = stream
      setupTimer = window.setTimeout(() => {
        if (attempt.current === generation) stop('Microphone setup timed out. Capture stopped; check the connection and retry.')
      }, 15_000)
      if (attempt.current !== generation || isHidden()) throw new Error('Capture was cancelled before it started.')
      context = new AudioContext({ sampleRate: 16000 })
      pending.context = context
      if (context.sampleRate !== 16000) throw new Error('This browser cannot provide the required audio sample rate.')
      await context.audioWorklet.addModule('/live-transcription/capture.worklet.js')
      const lease = await apiAuthenticatedRequest<Status>(`${path}/start`, {
        method: 'POST', headers: { 'Content-Type': 'application/json' }, signal: pending.abort.signal,
        body: JSON.stringify({ automatic_sharing_confirmed: true }),
      })
      id = lease.capture_id ?? undefined
      if (!id || attempt.current !== generation || isHidden()) throw new Error('Live capture was cancelled before it started.')
      const source = context.createMediaStreamSource(stream)
      const node = new AudioWorkletNode(context, 'lecture-capture')
      const item: Capture = { id, stream, context, source, node, abort: new AbortController(), queue: [], working: false, sequence: 0, epoch: Date.now() - context.currentTime * 1000 }
      capture.current = item
      starting.current = null
      node.port.onmessage = event => {
        if (capture.current !== item) return
        if (item.queue.length >= 2) { stop('The speech processor cannot keep up. Transcription stopped; use a faster model or server before restarting.'); return }
        item.queue.push({ ...event.data, sequence: item.sequence++ })
        void drain(item)
      }
      stream.getTracks().forEach(track => { track.onended = () => { if (capture.current === item) stop('Microphone disconnected. Restart when ready.') } })
      source.connect(node); node.connect(context.destination)
      await context.resume()
      if (attempt.current !== generation || capture.current !== item) return
      setStatus(lease); setPhase('recording')
      refresh.current()
    } catch (caught) {
      if (starting.current === pending) starting.current = null
      if (capture.current?.id === id && capture.current) { const item = capture.current; capture.current = null; release(item) }
      else {
        stream?.getTracks().forEach(track => track.stop())
        if (context) void context.close().catch(() => {})
        if (id) void apiAuthenticatedRequest(`${path}/${id}/stop`, { method: 'POST', keepalive: true }).catch(() => {})
      }
      if (attempt.current === generation) { setPhase('off'); setError(caught instanceof Error ? caught.message : 'Microphone transcription could not start.') }
    } finally { if (setupTimer !== undefined) window.clearTimeout(setupTimer) }
  }

  return <section className="space-y-3 rounded-lg border border-border p-4" aria-label="Live lecturer transcription">
    <h3 className="font-semibold">Live microphone → student catch-up</h3>
    <p className="text-sm">Captures your microphone, including other speech it picks up nearby. It does not capture every Teams participant. Short audio chunks go to the C.L.I.P server for local speech recognition; no audio recording is saved.</p>
    <p className="text-sm">Recognized text is shared automatically with enrolled students and their chatbot, labelled unreviewed. Pause before private discussion. You can correct or remove text below. Recognition can be wrong or incomplete.</p>
    {!status?.configured && <p>Administrator setup is required: install a local speech model and enable live transcription.</p>}
    {status && !status.session_running && <p>Start or resume the class before enabling live transcription.</p>}
    {error && <p role="alert">{error}</p>}
    {phase === 'off' && status?.running && status.capture_id && <button type="button" className="underline" onClick={() => {
      void apiAuthenticatedRequest(`${path}/${status.capture_id}/stop`, { method: 'POST' })
        .then(() => setStatus({ ...status, running: false, capture_id: null }))
        .catch(() => setError('Could not stop the existing capture. Check the connection and retry.'))
    }}>Stop existing capture</button>}
    <label className="flex gap-2"><input type="checkbox" disabled={phase !== 'off'} checked={confirmed} onChange={event => setConfirmed(event.target.checked)} />I confirm participants have been informed, required consent is in place, and this microphone speech may be transcribed and shared automatically with this course.</label>
    {phase === 'off' ? <button type="button" className={buttonStyles()} disabled={!confirmed || !status?.configured || !status.session_running} onClick={() => void start()}>Start live transcription</button>
      : <button type="button" className={buttonStyles({ intent: 'danger' })} onClick={() => stop()}>Stop live transcription</button>}
    <p role="status">{phase === 'recording' ? `Microphone live — processing 10-second chunks (${status?.language}).` : phase === 'starting' ? 'Requesting microphone access…' : 'Microphone transcription off.'} {last && `Last chunk processed: ${last}.`}</p>
    <p className="text-xs text-muted-foreground">Hiding/leaving this page stops capture. Keep it in a separate visible window while presenting. No automatic restart. Pausing/ending the class stops capture on the next status check (within approximately 3 seconds).</p>
  </section>
}
