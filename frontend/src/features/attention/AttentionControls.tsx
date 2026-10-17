import { useCallback, useEffect, useState } from 'react'
import { getCurrentUser, recordConsent } from '../../api'
import { calibrateCamera, startCamera, startMicrophone } from './localSensors'
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
  const [calibration, setCalibration] = useState<'none' | 'running' | 'done' | 'failed'>('none')
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
      setMessage('Opt-in saved. Enable selected to start local sensing.')
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
    if (calibrateCamera(ok => setCalibration(ok ? 'done' : 'failed'))) setCalibration('running')
  }

  const running = cameraStatus === 'on' || microphoneStatus === 'on'
  const pending = cameraStatus === 'starting' || microphoneStatus === 'starting'
  const selectedConsented = savedConsent.monitoring &&
    (!choice.camera || savedConsent.camera) &&
    (!choice.microphone || savedConsent.microphone)
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
            <input type="checkbox" checked={choice[sensor]} disabled={savingConsent || (sensor === 'camera' ? cameraStatus : microphoneStatus) === 'on' || (sensor === 'camera' ? cameraStatus : microphoneStatus) === 'starting'}
              onChange={event => setChoice(previous => ({ ...previous, [sensor]: event.target.checked }))} />
            I opt in to {sensor} indicators
          </label>
        ))}
      </div>
      <div className="mt-3 flex flex-wrap gap-2">
        <button type="button" disabled={!enabled || savingConsent || pending || running || (!choice.camera && !choice.microphone)}
          onClick={() => { void saveOptIn() }}
          className="rounded-lg border border-border px-4 py-2 text-sm font-semibold disabled:opacity-50">
          {savingConsent ? 'Saving opt-in…' : 'Save monitoring and selected device opt-in'}
        </button>
        <button type="button" disabled={!enabled || savingConsent || !selectedConsented || pending || (!choice.camera && !choice.microphone)}
          onClick={() => { if (choice.camera) void enable('camera'); if (choice.microphone) void enable('microphone') }}
          className="rounded-lg bg-primary px-4 py-2 text-sm text-primary-foreground disabled:opacity-50">Enable selected</button>
        <button type="button" onClick={stopAll} className="rounded-lg border border-border px-4 py-2 text-sm font-semibold">Disable all now</button>
        {running && (['camera', 'microphone'] as const).filter(sensor => (sensor === 'camera' ? cameraStatus : microphoneStatus) === 'on').map(sensor => (
          <button key={sensor} type="button" onClick={() => sensor === 'camera' ? stopCamera() : stopMicrophone()} className="rounded-lg border border-border px-3 py-2 text-sm">Stop {sensor}</button>
        ))}
      </div>
      <p className="mt-3 text-sm">Camera: {cameraStatus}. Microphone: {microphoneStatus}.</p>
      {cameraStatus === 'on' && (
        <div className="mt-2 text-sm">
          <button type="button" disabled={calibration === 'running'} onClick={startCalibration}
            className="rounded-lg border border-border px-3 py-2 text-sm disabled:opacity-50">
            {calibration === 'running' ? 'Look at the screen…' : 'Calibrate: look at the screen for 3 seconds'}
          </button>
          <span className="ml-2 text-muted-foreground">
            {calibration === 'done' && 'Calibrated to where you look. Only the offsets are kept, on this device.'}
            {calibration === 'failed' && 'Calibration did not work: your face was not clearly facing the screen. The standard settings are used.'}
            {calibration === 'none' && 'Optional. It helps if your camera is off to one side.'}
          </span>
        </div>
      )}
      {cameraStatus === 'on' && <p className="text-sm">Face: {face.face === null ? 'unavailable' : face.face ? 'detected' : 'not detected'}. Head direction: {face.head}. Gaze estimate: {face.forward === null ? 'unavailable' : face.forward ? 'camera-facing' : 'away from camera'}.</p>}
      {microphoneStatus === 'on' && <p className="text-sm">Voice activity: {speaking === null ? 'unavailable' : speaking ? 'detected' : 'not detected'}.</p>}
      {!enabled && <p className="mt-2 text-sm text-muted-foreground">Available while connected to an active, unpaused session.</p>}
      <p className="mt-2 text-xs text-muted-foreground">Sensing stops when you leave, hide this page, or disconnect. It never resumes automatically. Disable stops sensing without changing saved consent.</p>
      {message && <p role="alert" className="mt-3 text-sm">{message}</p>}
    </section>
  )
}
