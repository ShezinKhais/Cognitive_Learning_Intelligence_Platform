import { Camera, Crosshair, Info, Mic, Power, ShieldCheck } from 'lucide-react'
import { useCallback, useEffect, useRef, useState } from 'react'
import { getCurrentUser, recordConsent } from '../../api'
import { calibrateCamera, startCamera, startMicrophone, type CalibrationResult } from './localSensors'
import { awayDurationSeconds, nextAwayStart } from './awayDuration'
import { useAttentionReporter } from './useAttentionReporter'
import { useLocalSensor } from './useLocalSensor'
import type { AttentionSummary, FaceObservation } from './signals'

type Sensor = 'camera' | 'microphone'
const unknownFace: FaceObservation = { face: null, forward: null, head: 'unavailable' }

export function AttentionControls({ enabled, onSignal, consentRejected }: {
  enabled: boolean
  onSignal: (value: AttentionSummary) => boolean
  consentRejected: number
}) {
  const [choice, setChoice] = useState({ camera: false, microphone: false })
  const [savedConsent, setSavedConsent] = useState({ monitoring: false, camera: false, microphone: false })
  const [savingConsent, setSavingConsent] = useState(false)
  const [message, setMessage] = useState('')
  const awayStart = useRef<number | null>(null)
  const lastFaceObservationAt = useRef<number | null>(null)
  const [awaySeconds, setAwaySeconds] = useState<number | null>(null)
  const [calibration, setCalibration] = useState<'none' | 'running' | CalibrationResult>('none')
  const {
    status: cameraStatus, latest: face, start: enableCamera, stop: stopCamera,
    drain: drainCamera, isActive: cameraActive, isStartingOrActive: cameraStartingOrActive,
    startedAt: cameraStartedAt,
  } = useLocalSensor('Camera', startCamera, unknownFace, 40, setMessage)
  const {
    status: microphoneStatus, latest: speaking, start: enableMicrophone, stop: stopMicrophone,
    drain: drainMicrophone, isActive: microphoneActive, isStartingOrActive: microphoneStartingOrActive,
    startedAt: microphoneStartedAt,
  } = useLocalSensor<boolean | null>('Microphone', startMicrophone, null, 200, setMessage)
  // Local-only timer. Missing or stale observations never count as away.
  useEffect(() => {
    if (!enabled || cameraStatus !== 'on') {
      awayStart.current = null
      lastFaceObservationAt.current = null
      setAwaySeconds(null)
      return
    }

    if (face.forward === null) {
      lastFaceObservationAt.current = null
      awayStart.current = null
      setAwaySeconds(null)
      return
    }

    const now = performance.now()
    lastFaceObservationAt.current = now
    awayStart.current = nextAwayStart(awayStart.current, face.forward, now)
    setAwaySeconds(awayDurationSeconds(awayStart.current, now))
  }, [enabled, cameraStatus, face])

  useEffect(() => {
    if (!enabled || cameraStatus !== 'on') return

    const timer = window.setInterval(() => {
      const now = performance.now()
      if (
        lastFaceObservationAt.current === null ||
        now - lastFaceObservationAt.current >= 2000
      ) {
        awayStart.current = null
        setAwaySeconds(null)
        return
      }

      setAwaySeconds(awayDurationSeconds(awayStart.current, now))
    }, 250)

    return () => window.clearInterval(timer)
  }, [enabled, cameraStatus])
  const stopAll = useCallback(() => { stopCamera(); stopMicrophone() }, [stopCamera, stopMicrophone])
  const refuseSignal = useCallback(() => {
    stopAll()
    setMessage('This session is not accepting indicators. Local sensing has stopped.')
  }, [stopAll])
  useAttentionReporter(
    enabled, cameraActive, cameraStartedAt, drainCamera,
    microphoneActive, microphoneStartedAt, drainMicrophone, onSignal, refuseSignal,
  )

  useEffect(() => {
    if (!consentRejected) return
    stopAll()
    setSavedConsent(previous => ({ ...previous, monitoring: false }))
    setMessage('The session did not accept monitoring consent. Local sensing has stopped. Save your opt-in again before retrying.')
  }, [consentRejected, stopAll])

  useEffect(() => {
    if (!enabled) stopAll()
    const hide = () => { if (document.hidden) stopAll() }
    document.addEventListener('visibilitychange', hide)
    window.addEventListener('pagehide', stopAll)
    return () => {
      document.removeEventListener('visibilitychange', hide)
      window.removeEventListener('pagehide', stopAll)
    }
  }, [enabled, stopAll])

  useEffect(() => {
    if (!enabled) return
    let disposed = false
    let checking = false
    const timer = setInterval(async () => {
      if (checking || (!cameraStartingOrActive() && !microphoneStartingOrActive())) return
      checking = true
      try {
        const user = await getCurrentUser()
        if (disposed) return
        if (!user.consents.includes('engagement_monitoring')) {
          setSavedConsent(previous => ({ ...previous, monitoring: false }))
          stopAll(); setMessage('Monitoring consent is unavailable. Sensors have stopped.'); return
        }
        for (const sensor of ['camera', 'microphone'] as const) {
          if (!user.consents.includes(sensor)) {
            setSavedConsent(previous => ({ ...previous, [sensor]: false }))
            if (sensor === 'camera') stopCamera()
            else stopMicrophone()
          }
        }
      } catch {
        if (!disposed) {
          stopAll()
          setSavedConsent(previous => ({ ...previous, monitoring: false }))
          setMessage('Consent could not be verified. Sensors have stopped; save your opt-in again before retrying.')
        }
      } finally { checking = false }
    }, 5000)
    return () => { disposed = true; clearInterval(timer) }
  }, [enabled, cameraStartingOrActive, microphoneStartingOrActive, stopCamera, stopMicrophone, stopAll])

  async function saveOptIn() {
    if (!enabled || savingConsent || (!choice.camera && !choice.microphone)) return
    setSavingConsent(true)
    setMessage('')
    try {
      await recordConsent('engagement_monitoring', true)
      if (choice.camera) await recordConsent('camera', true)
      if (choice.microphone) await recordConsent('microphone', true)
      setSavedConsent(previous => ({
        monitoring: true,
        camera: previous.camera || choice.camera,
        microphone: previous.microphone || choice.microphone,
      }))
      setMessage('Choice saved. Press Turn on to start.')
    } catch {
      setMessage('Opt-in could not be saved. No device was started.')
    } finally {
      setSavingConsent(false)
    }
  }

  async function enable(sensor: Sensor) {
    if (!enabled || !savedConsent.monitoring || !savedConsent[sensor]) return
    setMessage('')
    if (sensor === 'camera') await enableCamera()
    else await enableMicrophone()
  }

  // A new camera start forgets the old calibration, as the worker does.
  useEffect(() => { if (cameraStatus !== 'on') setCalibration('none') }, [cameraStatus])
  function startCalibration() {
    if (calibrateCamera(setCalibration)) setCalibration('running')
  }

  const running = cameraStatus === 'on' || microphoneStatus === 'on'
  const pending = cameraStatus === 'starting' || microphoneStatus === 'starting'
  const selectedConsented = savedConsent.monitoring &&
    (!choice.camera || savedConsent.camera) &&
    (!choice.microphone || savedConsent.microphone)
  const sensing = running ? 'Local sensing active Ã¢â‚¬â€ raw media is not uploaded'
    : pending ? 'Starting Ã¢â‚¬â€ your device may be active while models load' : 'Local sensing off'
  const statusOf = (sensor: Sensor) => sensor === 'camera' ? cameraStatus : microphoneStatus
  return (
    <section aria-label="Optional local indicators"
      className="mt-5 rounded-xl border border-border bg-card p-5 shadow-[var(--shadow-card)] sm:p-6">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="flex min-w-0 items-start gap-3">
          <span aria-hidden="true" className="grid size-10 shrink-0 place-items-center rounded-full bg-info/10 text-info">
            <ShieldCheck size={20} />
          </span>
          <div className="min-w-0">
            <h2 className="text-lg font-semibold">Optional local indicators</h2>
            <p className="mt-1 text-sm text-muted-foreground">
              Your camera and microphone stay on this device. Only a short summary is shared every
              five seconds. Neither is required.
            </p>
          </div>
        </div>
        <p role="status" className="inline-flex items-center gap-2 rounded-full border border-border bg-card px-3 py-1.5 text-xs font-semibold text-foreground">
          <span aria-hidden="true" className={`size-2 rounded-full ${running ? 'bg-success' : pending ? 'bg-warning' : 'bg-muted-foreground'}`} />
          {sensing}
        </p>
      </div>

      <div className="mt-4 grid gap-3 sm:grid-cols-2">
        {(['camera', 'microphone'] as const).map(sensor => {
          const Icon = sensor === 'camera' ? Camera : Mic
          const deviceStatus = statusOf(sensor)
          return (
            <label key={sensor}
              className="flex cursor-pointer items-start gap-3 rounded-lg border border-border p-3 transition-colors hover:bg-muted/50 has-[:checked]:border-info has-[:checked]:bg-info/5">
              <input type="checkbox" className="mt-1 size-4 shrink-0 accent-[var(--info)]" checked={choice[sensor]}
                disabled={savingConsent || deviceStatus === 'on' || deviceStatus === 'starting'}
                onChange={event => setChoice(previous => ({ ...previous, [sensor]: event.target.checked }))} />
              <span className="min-w-0 flex-1">
                <span className="flex items-center gap-2 text-sm font-medium">
                  <Icon aria-hidden="true" size={16} className="shrink-0 text-info" />
                  I opt in to {sensor} indicators
                </span>
                <span className="mt-1 block text-xs text-muted-foreground">
                  {sensor === 'camera'
                    ? 'Whether a face is in view and roughly facing the screen.'
                    : 'Whether you are speaking. No words are heard or kept.'}
                </span>
              </span>
              <DevicePill status={deviceStatus} />
            </label>
          )
        })}
      </div>

      <div className="mt-4 flex flex-wrap gap-2">
        <button type="button" disabled={!enabled || savingConsent || pending || running || (!choice.camera && !choice.microphone)}
          onClick={() => { void saveOptIn() }}
          className="rounded-lg border border-border px-4 py-2 text-sm font-semibold hover:bg-muted disabled:opacity-50">
          {savingConsent ? 'SavingÃ¢â‚¬Â¦' : 'Save my choice'}
        </button>
        <button type="button" disabled={!enabled || savingConsent || !selectedConsented || pending || (!choice.camera && !choice.microphone)}
          onClick={() => { if (choice.camera) void enable('camera'); if (choice.microphone) void enable('microphone') }}
          className="inline-flex items-center gap-2 rounded-lg bg-primary px-4 py-2 text-sm font-semibold text-primary-foreground disabled:opacity-50">
          <Power aria-hidden="true" size={15} />
          Turn on
        </button>
        <button type="button" onClick={stopAll}
          className="rounded-lg border border-border px-4 py-2 text-sm font-semibold hover:bg-muted">Turn everything off</button>
        {running && (['camera', 'microphone'] as const).filter(sensor => statusOf(sensor) === 'on').map(sensor => (
          <button key={sensor} type="button" onClick={() => sensor === 'camera' ? stopCamera() : stopMicrophone()}
            className="rounded-lg border border-border px-3 py-2 text-sm hover:bg-muted">Stop {sensor}</button>
        ))}
      </div>
      <p className="mt-2 text-xs text-foreground">Camera: {cameraStatus}. Microphone: {microphoneStatus}.</p>

      {(cameraStatus === 'on' || microphoneStatus === 'on') && (
        <div className="mt-4 rounded-lg bg-muted/60 p-3">
          <p className="text-xs font-semibold uppercase tracking-wide text-foreground">What your device sees right now</p>
          <div className="mt-2 flex flex-wrap gap-2">
            {cameraStatus === 'on' && <>
              <Chip good={face.face} label={`Face: ${face.face === null ? 'unavailable' : face.face ? 'detected' : 'not detected'}`} />
              <Chip good={face.head === 'unavailable' ? null : face.head === 'forward'} label={`Head: ${face.head}`} />
              <Chip good={face.forward} label={`Gaze: ${face.forward === null ? 'unavailable' : face.forward ? 'facing the screen' : 'away from the screen'}`} />
            </>}
            {microphoneStatus === 'on' && (
              <Chip good={speaking === null ? null : true} label={`Voice: ${speaking === null ? 'unavailable' : speaking ? 'speaking' : 'quiet'}`} />
            )}
          </div>
          {cameraStatus === 'on' && (
            <div className="mt-3 border-t border-border pt-3">
              <div className="flex flex-wrap items-center gap-3">
                <button type="button" disabled={calibration === 'running'} onClick={startCalibration}
                  className="inline-flex items-center gap-2 rounded-lg border border-border bg-card px-3 py-2 text-sm font-semibold hover:bg-muted disabled:opacity-60">
                  <Crosshair aria-hidden="true" size={15} />
                  {calibration === 'running' ? 'Look at the screenÃ¢â‚¬Â¦' : calibration === 'done' ? 'Calibrate again' : 'Calibrate: look at the screen for 3 seconds'}
                </button>
                <span className="text-sm text-foreground">
                  {calibration === 'done' && 'Calibrated to where you look. Only the offsets are kept, on this device.'}
                  {calibration === 'failed' && 'That did not work: your face was not clearly facing the screen. The standard settings are used.'}
                  {calibration === 'timeout' && 'The camera stopped sending pictures, so calibration did not finish. The standard settings are used.'}
                  {calibration === 'none' && 'Optional. Helps if your camera is off to one side.'}
                  {calibration === 'running' && 'Keep looking at the middle of the screen.'}
                </span>
              </div>
              {calibration === 'running' && (
                <div aria-hidden="true" className="mt-2 h-1.5 overflow-hidden rounded-full bg-card">
                  <div className="animate-fill-3s h-full rounded-full bg-info" />
                </div>
              )}
            </div>
          )}
        </div>
      )}

      {cameraStatus === 'on' && (
        <p className="mt-3 text-sm" aria-live="off">
          Continuous camera-away estimate:{' '}
          {awaySeconds === null ? 'unavailable' : `${awaySeconds} seconds`}
        </p>
      )}
      <details className="mt-4 text-sm">
        <summary className="cursor-pointer font-medium text-foreground underline underline-offset-2">What is shared, and what is not</summary>
        <ul className="mt-2 list-disc space-y-1 pl-5 text-muted-foreground">
          <li>Shared every five seconds: whether a face was present, the share of time facing the screen, and whether you spoke.</li>
          <li>Never shared or stored: video, audio, images, face measurements or what you said.</li>
          <li>These are rough estimates. They do not prove attention or understanding.</li>
          <li>Sensing stops when you leave, hide this page, or disconnect, and never restarts on its own. Turning it off does not change your saved choice.</li>
        </ul>
      </details>
      {!enabled && <p className="mt-3 text-sm text-muted-foreground">Available while connected to an active, unpaused session.</p>}
      {message && (
        <p role="alert" className="mt-3 flex items-start gap-2 rounded-lg border border-warning/30 bg-warning/10 p-3 text-sm">
          <Info aria-hidden="true" size={16} className="mt-0.5 shrink-0 text-warning" />
          <span>{message}</span>
        </p>
      )}
    </section>
  )
}

// Colour is only in the dot; the words carry the meaning and stay high-contrast.
const DOT = { good: 'bg-success', warn: 'bg-warning', bad: 'bg-critical', none: 'bg-muted-foreground' } as const

function DevicePill({ status }: { status: 'off' | 'starting' | 'on' | 'unavailable' }) {
  const dot = { on: DOT.good, starting: DOT.warn, unavailable: DOT.bad, off: DOT.none }[status]
  return (
    <span aria-hidden="true" className="inline-flex shrink-0 items-center gap-1.5 rounded-full border border-border bg-card px-2 py-0.5 text-xs font-semibold text-foreground">
      <span className={`size-1.5 rounded-full ${dot}`} />{status}
    </span>
  )
}

function Chip({ good, label }: { good: boolean | null; label: string }) {
  const dot = good === null ? DOT.none : good ? DOT.good : DOT.warn
  return (
    <span className="inline-flex items-center gap-1.5 rounded-full border border-border bg-card px-2.5 py-1 text-xs font-medium text-foreground">
      <span aria-hidden="true" className={`size-1.5 rounded-full ${dot}`} />{label}
    </span>
  )
}
