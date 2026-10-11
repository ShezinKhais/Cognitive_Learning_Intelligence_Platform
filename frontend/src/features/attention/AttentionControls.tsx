import { useCallback, useEffect, useRef, useState } from 'react'
import { getCurrentUser, recordConsent } from '../../api'
import { startCamera, startMicrophone } from './localSensors'
import { summary } from './signals'
import type { AttentionSummary, FaceObservation } from './signals'

type Sensor = 'camera' | 'microphone'
type Status = 'off' | 'starting' | 'on' | 'unavailable'
const unknownFace: FaceObservation = { face: null, forward: null, head: 'unavailable' }

export function AttentionControls({ enabled, onSignal }: {
  enabled: boolean
  onSignal: (value: AttentionSummary) => boolean
}) {
  const [choice, setChoice] = useState({ camera: false, microphone: false })
  const [status, setStatus] = useState<Record<Sensor, Status>>({ camera: 'off', microphone: 'off' })
  const [message, setMessage] = useState('')
  const [face, setFace] = useState(unknownFace)
  const [speaking, setSpeaking] = useState<boolean | null>(null)
  const controllers = useRef<Partial<Record<Sensor, AbortController>>>({})
  const samples = useRef<{ face: FaceObservation[]; speech: boolean[]; faceAt: number; speechAt: number }>({ face: [], speech: [], faceAt: 0, speechAt: 0 })
  const emit = useRef(onSignal)
  emit.current = onSignal

  const stop = useCallback((sensor: Sensor) => {
    controllers.current[sensor]?.abort()
    delete controllers.current[sensor]
    if (sensor === 'camera') {
      samples.current.face = []; samples.current.faceAt = 0; setFace(unknownFace)
    } else {
      samples.current.speech = []; samples.current.speechAt = 0; setSpeaking(null)
    }
    setStatus(previous => ({ ...previous, [sensor]: 'off' }))
  }, [])
  const stopAll = useCallback(() => { stop('camera'); stop('microphone') }, [stop])

  useEffect(() => {
    if (!enabled) stopAll()
    const hide = () => { if (document.hidden) stopAll() }
    document.addEventListener('visibilitychange', hide)
    window.addEventListener('pagehide', stopAll)
    return () => {
      document.removeEventListener('visibilitychange', hide)
      window.removeEventListener('pagehide', stopAll)
      // Abort even pending permission/model requests. Never auto-resume.
      Object.values(controllers.current).forEach(controller => controller?.abort())
      controllers.current = {}
    }
  }, [enabled, stopAll])

  useEffect(() => {
    if (!enabled) return
    let disposed = false
    let checking = false
    let last = performance.now()
    const timer = setInterval(async () => {
      if (checking || !Object.keys(controllers.current).length) return
      checking = true
      try {
        const user = await getCurrentUser()
        if (disposed) return
        if (!user.consents.includes('engagement_monitoring')) {
          stopAll(); setMessage('Monitoring consent is unavailable. Sensors have stopped.'); return
        }
        for (const sensor of ['camera', 'microphone'] as const) {
          if (!user.consents.includes(sensor)) stop(sensor)
        }
        const now = performance.now()
        const current = samples.current
        const payload = summary(
          controllers.current.camera && now - current.faceAt < 2000 ? current.face : [],
          controllers.current.microphone && now - current.speechAt < 2000 ? current.speech : [],
          (now - last) / 1000,
        )
        last = now
        current.face = []; current.speech = []
        if (Object.keys(controllers.current).length && !document.hidden) emit.current(payload)
      } catch {
        if (!disposed) { stopAll(); setMessage('Consent could not be verified. Sensors have stopped; you can try again.') }
      } finally { checking = false }
    }, 5000)
    return () => { disposed = true; clearInterval(timer) }
  }, [enabled, stop, stopAll])

  async function enable(sensor: Sensor) {
    if (!enabled || document.hidden || controllers.current[sensor]) return
    const controller = new AbortController()
    controllers.current[sensor] = controller
    const current = () => controllers.current[sensor] === controller && !controller.signal.aborted
    const failed = () => {
      if (!current()) return
      stop(sensor)
      setStatus(previous => ({ ...previous, [sensor]: 'unavailable' }))
      setMessage(`${sensor === 'camera' ? 'Camera' : 'Microphone'} unavailable. Check browser permission or device use in another app. You can continue without it.`)
    }
    setStatus(previous => ({ ...previous, [sensor]: 'starting' }))
    setMessage('')
    try {
      if (!window.isSecureContext || !navigator.mediaDevices?.getUserMedia) throw new Error('Unavailable')
      await recordConsent('engagement_monitoring', true)
      if (!current()) return
      await recordConsent(sensor, true)
      if (!current()) return
      if (sensor === 'camera') {
        await startCamera(controller.signal, value => {
          if (!current()) return
          samples.current.face.push(value)
          samples.current.face = samples.current.face.slice(-40)
          samples.current.faceAt = performance.now()
          setFace(value)
        }, failed)
      } else {
        await startMicrophone(controller.signal, value => {
          if (!current()) return
          if (value !== null) samples.current.speech.push(value)
          samples.current.speech = samples.current.speech.slice(-200)
          samples.current.speechAt = value === null ? 0 : performance.now()
          setSpeaking(value)
        }, failed)
      }
      if (current()) setStatus(previous => ({ ...previous, [sensor]: 'on' }))
    } catch { failed() }
  }

  const running = status.camera === 'on' || status.microphone === 'on'
  const pending = status.camera === 'starting' || status.microphone === 'starting'
  return (
    <section aria-label="Optional local indicators" className="mt-5 rounded-xl border border-border bg-card p-5">
      <h2 className="text-lg font-semibold">Optional local indicators</h2>
      <p className="mt-2 text-sm text-muted-foreground">
        Camera frames and audio stay on this device. If you opt in, only five-second summaries of
        face presence, estimated camera-facing gaze and voice activity are shared with this session.
        These estimates do not prove attention or understanding. Neither device is required.
      </p>
      <p role="status" className="mt-3 font-medium">
        {running ? 'Local sensing active — raw media is not uploaded' : pending ? 'Starting — your device may be active while models load' : 'Local sensing off'}
      </p>
      <div className="mt-3 flex flex-wrap gap-4">
        {(['camera', 'microphone'] as const).map(sensor => (
          <label key={sensor} className="flex items-center gap-2 text-sm">
            <input type="checkbox" checked={choice[sensor]} disabled={status[sensor] === 'on' || status[sensor] === 'starting'}
              onChange={event => setChoice(previous => ({ ...previous, [sensor]: event.target.checked }))} />
            I opt in to {sensor} indicators
          </label>
        ))}
      </div>
      <div className="mt-3 flex flex-wrap gap-2">
        <button type="button" disabled={!enabled || pending || (!choice.camera && !choice.microphone)}
          onClick={() => { if (choice.camera) void enable('camera'); if (choice.microphone) void enable('microphone') }}
          className="rounded-lg bg-primary px-4 py-2 text-sm text-primary-foreground disabled:opacity-50">Enable selected</button>
        <button type="button" onClick={stopAll} className="rounded-lg border border-border px-4 py-2 text-sm font-semibold">Disable all now</button>
        {running && (['camera', 'microphone'] as const).filter(sensor => status[sensor] === 'on').map(sensor => (
          <button key={sensor} type="button" onClick={() => stop(sensor)} className="rounded-lg border border-border px-3 py-2 text-sm">Stop {sensor}</button>
        ))}
      </div>
      <p className="mt-3 text-sm">Camera: {status.camera}. Microphone: {status.microphone}.</p>
      {status.camera === 'on' && <p className="text-sm">Face: {face.face === null ? 'unavailable' : face.face ? 'detected' : 'not detected'}. Head direction: {face.head}. Gaze estimate: {face.forward === null ? 'unavailable' : face.forward ? 'camera-facing' : 'away from camera'}.</p>}
      {status.microphone === 'on' && <p className="text-sm">Voice activity: {speaking === null ? 'unavailable' : speaking ? 'detected' : 'not detected'}.</p>}
      {!enabled && <p className="mt-2 text-sm text-muted-foreground">Available while connected to an active, unpaused session.</p>}
      <p className="mt-2 text-xs text-muted-foreground">Sensing stops when you leave, hide this page, or disconnect. It never resumes automatically. Disable stops sensing without changing saved consent.</p>
      {message && <p role="alert" className="mt-3 text-sm">{message}</p>}
    </section>
  )
}
