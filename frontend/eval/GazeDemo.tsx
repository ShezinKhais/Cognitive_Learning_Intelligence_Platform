// The camera attention demo page, mounted by gaze-demo.tsx.
import { FaceLandmarker, FilesetResolver, type NormalizedLandmark } from '@mediapipe/tasks-vision'
import { Camera, CameraOff, Crosshair, RotateCcw, ShieldCheck } from 'lucide-react'
import { useEffect, useRef, useState, type ReactNode } from 'react'

import { Wordmark } from '../src/components/brand/ClipMark'
import { buttonStyles } from '../src/components/ui/button'
import { cn } from '../src/components/ui/cn'
import {
  calibrate, classifyFace, faceFeatures, summary, thresholdsFor,
  type AttentionSummary, type Calibration, type EyeFeatures, type FaceFeatures, type FaceObservation, type Thresholds,
} from '../src/features/attention/signals'

const assets = new URL(`${import.meta.env.BASE_URL}attention/`, location.origin).href
const CALIBRATION_MS = 3000
const CALIBRATION_GIVE_UP_MS = 8000
const HISTORY_MS = 30_000
const WIRE_WINDOW_MS = 5000
const DETECT_EVERY_MS = 50
const NO_CALIBRATION: Calibration = { yaw: 0, pitch: 0, roll: 0, irisX: 0.5, irisY: 0.5 }

type Layer = 'outline' | 'mesh' | 'eyes' | 'head' | 'gaze'
const LAYERS: { id: Layer; label: string }[] = [
  { id: 'outline', label: 'Tracker dots' },
  { id: 'mesh', label: 'All points' },
  { id: 'eyes', label: 'Eyes and irises' },
  { id: 'head', label: 'Head direction' },
  { id: 'gaze', label: 'Gaze box' },
]

type Verdict = 'facing' | 'away' | 'unclear' | 'none' | 'many'
const VERDICTS: Record<Verdict, { label: string; badge: string; bar: string; note: string }> = {
  facing: {
    label: 'Facing the screen', badge: 'bg-success text-success-foreground', bar: 'bg-success',
    note: 'Head within the limits and both irises inside the box.',
  },
  away: {
    label: 'Looking away', badge: 'bg-warning text-warning-foreground', bar: 'bg-warning',
    note: 'Counts against the on-screen ratio.',
  },
  unclear: {
    label: 'Eyes not clear', badge: 'bg-black/65 text-white', bar: 'bg-muted-foreground/40',
    note: 'Counted as unavailable, never as looking away.',
  },
  none: {
    label: 'No face in view', badge: 'bg-black/65 text-white', bar: 'bg-muted-foreground/40',
    note: 'Reported as no face present. Gaze is unavailable.',
  },
  many: {
    label: 'More than one face', badge: 'bg-info text-info-foreground', bar: 'bg-info',
    note: 'Not judged: C.L.I.P only reads a single face.',
  },
}

function verdictOf(features: FaceFeatures, observation: FaceObservation): Verdict {
  if (features.faces === 0) return 'none'
  if (features.faces > 1) return 'many'
  if (observation.forward === true) return 'facing'
  if (observation.forward === false) return 'away'
  return 'unclear'
}

interface Check { name: string; value: string; limit: string; pass: boolean | null }

const degrees = (value: number) => `${value > 0 ? '+' : ''}${Math.round(value)}°`
const fixed = (value: number) => value.toFixed(2)

/** The checks classifyFace makes, one per line, so the verdict can be explained. */
function checksFor(f: FaceFeatures, t: Thresholds, calibration: Calibration | null): Check[] {
  const c = calibration ?? NO_CALIBRATION
  const checks: Check[] = [{ name: 'One face', value: String(f.faces), limit: 'exactly 1', pass: f.faces === 1 }]
  if (f.faces !== 1 || !f.valid || f.width === null) return checks
  checks.push({ name: 'Face size', value: fixed(f.width), limit: `at least ${t.minFaceWidth}`, pass: f.width >= t.minFaceWidth })
  if (f.pose) {
    const yaw = f.pose.yaw - c.yaw
    const pitch = f.pose.pitch - c.pitch
    const roll = f.pose.roll - c.roll
    checks.push(
      { name: 'Head turn', value: degrees(yaw), limit: `within ${t.maxYawDegrees}°`, pass: Math.abs(yaw) < t.maxYawDegrees },
      { name: 'Head tilt', value: degrees(pitch), limit: `within ${t.maxPitchDegrees}°`, pass: Math.abs(pitch) < t.maxPitchDegrees },
      { name: 'Head lean', value: degrees(roll), limit: `within ${t.maxRollDegrees}°`, pass: Math.abs(roll) < t.maxRollDegrees },
    )
  } else {
    checks.push(
      { name: 'Turn (estimate)', value: fixed(f.yawProxy ?? 0), limit: `below ${t.maxYawProxy}`, pass: f.yawProxy !== null && f.yawProxy < t.maxYawProxy },
      { name: 'Lean (estimate)', value: fixed(f.rollProxy ?? 0), limit: `below ${t.maxRollProxy}`, pass: f.rollProxy !== null && f.rollProxy < t.maxRollProxy },
    )
  }
  // signals.ts calls landmark 33's eye "left"; it is the student's right eye.
  for (const [name, eye] of [['Left eye', f.rightEye], ['Right eye', f.leftEye]] as const) {
    const open = eyeOpen(eye, t)
    checks.push({ name: `${name} open`, value: eye ? fixed(eye.open) : 'none', limit: `at least ${t.minOpenEyeRatio}`, pass: open })
    checks.push({
      name: `${name} iris in box`,
      value: eye && open ? `${fixed(eye.irisX)}, ${fixed(eye.irisY)}` : 'unread',
      limit: 'inside the box',
      pass: eye && open ? irisInBox(eye, t, c) : null,
    })
  }
  return checks
}

const eyeOpen = (eye: EyeFeatures | null, t: Thresholds) => Boolean(eye && eye.width >= t.minEyeWidth && eye.open >= t.minOpenEyeRatio)

function irisInBox(eye: EyeFeatures, t: Thresholds, c: Calibration): boolean {
  const x = eye.irisX - (c.irisX - 0.5)
  const y = eye.irisY - (c.irisY - 0.5)
  return x >= t.irisX[0] && x <= t.irisX[1] && y >= t.irisY[0] && y <= t.irisY[1]
}

interface Reading {
  features: FaceFeatures
  observation: FaceObservation
  verdict: Verdict
  calibration: Calibration | null
  fps: number
}

type CameraState =
  | { kind: 'off' }
  | { kind: 'starting'; text: string }
  | { kind: 'on' }
  | { kind: 'error'; text: string }

type CalibrationState =
  | { kind: 'none' }
  | { kind: 'running'; startedAt: number }
  | { kind: 'done'; value: Calibration }
  | { kind: 'failed'; text: string }

async function createLandmarker(): Promise<FaceLandmarker> {
  const files = await FilesetResolver.forVisionTasks(`${assets}vision`)
  const options = (delegate: 'GPU' | 'CPU') => ({
    baseOptions: { modelAssetPath: `${assets}face_landmarker.task`, delegate },
    runningMode: 'VIDEO' as const,
    numFaces: 2,
    outputFacialTransformationMatrixes: true,
  })
  try {
    return await FaceLandmarker.createFromOptions(files, options('GPU'))
  } catch {
    return FaceLandmarker.createFromOptions(files, options('CPU'))
  }
}

function cameraError(error: unknown): string {
  const name = error instanceof DOMException ? error.name : ''
  if (name === 'NotAllowedError') return 'Camera permission was refused. Allow it from the address bar, then try again.'
  if (name === 'NotFoundError') return 'No camera was found on this device.'
  if (name === 'NotReadableError') return 'The camera is in use by another app. Close it, then try again.'
  return 'The camera or the face model could not start. Reload the page and try again.'
}

// Overlay colours sit on live video, so they are fixed rather than themed.
const INK = {
  mesh: 'rgba(255, 255, 255, 0.35)',
  feature: 'rgba(255, 255, 255, 0.6)',
  point: '#ffffff',
  oval: 'rgba(255, 255, 255, 0.55)',
  eye: '#a9acff',
  iris: '#ffe066',
  good: '#4ade80',
  away: '#fbbf24',
}

/** Each landmark a set of connections touches, once. */
const pointsOf = (...sets: { start: number; end: number }[][]) =>
  [...new Set(sets.flat().flatMap(c => [c.start, c.end]))]
const CONTOUR_POINTS = pointsOf(
  FaceLandmarker.FACE_LANDMARKS_FACE_OVAL,
  FaceLandmarker.FACE_LANDMARKS_LEFT_EYEBROW,
  FaceLandmarker.FACE_LANDMARKS_RIGHT_EYEBROW,
  FaceLandmarker.FACE_LANDMARKS_LIPS,
)
const EYE_POINTS = pointsOf(FaceLandmarker.FACE_LANDMARKS_LEFT_EYE, FaceLandmarker.FACE_LANDMARKS_RIGHT_EYE)
// The points the judgement reads: eye corners and lids, and the nose tip.
const KEY_POINTS = [1, 33, 133, 159, 145, 362, 263, 386, 374]

const EYES = [
  { corners: [33, 133], top: 159, bottom: 145, iris: 468, features: 'leftEye' },
  { corners: [362, 263], top: 386, bottom: 374, iris: 473, features: 'rightEye' },
] as const

function drawOverlay(
  ctx: CanvasRenderingContext2D,
  lm: NormalizedLandmark[],
  features: FaceFeatures,
  observation: FaceObservation,
  layers: Record<Layer, boolean>,
  t: Thresholds,
  calibration: Calibration | null,
) {
  const { width: w, height: h } = ctx.canvas
  const px = (i: number) => ({ x: lm[i].x * w, y: lm[i].y * h })
  const scale = w / 640
  const dots = (indices: Iterable<number>, colour: string, radius: number) => {
    ctx.fillStyle = colour
    ctx.beginPath()
    for (const i of indices) {
      if (!lm[i]) continue
      const p = px(i)
      ctx.moveTo(p.x + radius * scale, p.y)
      ctx.arc(p.x, p.y, radius * scale, 0, Math.PI * 2)
    }
    ctx.fill()
  }

  if (layers.mesh) dots(lm.keys(), INK.mesh, 0.9)
  if (layers.outline) {
    dots(CONTOUR_POINTS, INK.feature, 1.3)
    dots(KEY_POINTS, INK.point, 2.2)
  }
  if (layers.eyes) {
    dots(EYE_POINTS, INK.eye, 1.3)
    // Each iris as a ring round its centre, the point the gaze box checks.
    for (const centre of [468, 473]) {
      if (!lm[centre + 1]) continue
      const c = px(centre)
      const edge = px(centre + 1)
      ctx.strokeStyle = INK.iris
      ctx.lineWidth = 1.3 * scale
      ctx.beginPath()
      ctx.arc(c.x, c.y, Math.hypot(edge.x - c.x, edge.y - c.y), 0, Math.PI * 2)
      ctx.stroke()
    }
    dots([468, 473], INK.iris, 1.8)
  }
  if (layers.head) {
    // From the middle of the face through the nose tip, so the arrow points
    // where the head points in the picture, whatever the pose convention.
    const ends = [234, 454, 10, 152].map(px)
    const centre = { x: ends.reduce((s, p) => s + p.x, 0) / 4, y: ends.reduce((s, p) => s + p.y, 0) / 4 }
    const nose = px(1)
    const tip = { x: nose.x + (nose.x - centre.x) * 2.5, y: nose.y + (nose.y - centre.y) * 2.5 }
    ctx.strokeStyle = ctx.fillStyle = observation.head === 'forward' ? INK.good : INK.away
    ctx.lineWidth = 3 * scale
    ctx.lineCap = 'round'
    ctx.beginPath()
    ctx.moveTo(centre.x, centre.y)
    ctx.lineTo(tip.x, tip.y)
    ctx.stroke()
    const angle = Math.atan2(tip.y - centre.y, tip.x - centre.x)
    const head = 10 * scale
    ctx.beginPath()
    ctx.moveTo(tip.x, tip.y)
    ctx.lineTo(tip.x - head * Math.cos(angle - 0.5), tip.y - head * Math.sin(angle - 0.5))
    ctx.lineTo(tip.x - head * Math.cos(angle + 0.5), tip.y - head * Math.sin(angle + 0.5))
    ctx.closePath()
    ctx.fill()
    ctx.beginPath()
    ctx.arc(centre.x, centre.y, 3 * scale, 0, Math.PI * 2)
    ctx.fill()
  }
  if (layers.gaze) {
    const c = calibration ?? NO_CALIBRATION
    for (const eye of EYES) {
      const [a, b] = eye.corners.map(px)
      const left = Math.min(a.x, b.x)
      const eyeWidth = Math.abs(a.x - b.x)
      const top = px(eye.top).y
      const eyeHeight = px(eye.bottom).y - top
      const data = features[eye.features]
      const inside = data && eyeOpen(data, t) ? irisInBox(data, t, c) : null
      const colour = inside === null ? INK.oval : inside ? INK.good : INK.away
      const x0 = left + (t.irisX[0] + c.irisX - 0.5) * eyeWidth
      const x1 = left + (t.irisX[1] + c.irisX - 0.5) * eyeWidth
      const y0 = top + (t.irisY[0] + c.irisY - 0.5) * eyeHeight
      const y1 = top + (t.irisY[1] + c.irisY - 0.5) * eyeHeight
      ctx.setLineDash([4 * scale, 3 * scale])
      ctx.strokeStyle = colour
      ctx.lineWidth = 1.4 * scale
      ctx.strokeRect(x0, y0, x1 - x0, Math.max(y1 - y0, 2 * scale))
      ctx.setLineDash([])
      const iris = px(eye.iris)
      ctx.fillStyle = colour
      ctx.beginPath()
      ctx.arc(iris.x, iris.y, 2.6 * scale, 0, Math.PI * 2)
      ctx.fill()
    }
  }
}

function Switch({ checked, onChange, disabled, children }: {
  checked: boolean; onChange: (value: boolean) => void; disabled?: boolean; children: ReactNode
}) {
  return (
    <button type="button" role="switch" aria-checked={checked} disabled={disabled} onClick={() => onChange(!checked)}
      className="inline-flex items-center gap-2 rounded-full border border-border bg-card py-1.5 pl-1.5 pr-3 text-sm font-medium transition-colors hover:bg-muted disabled:cursor-not-allowed disabled:opacity-50">
      <span aria-hidden className={cn('relative h-5 w-9 rounded-full transition-colors', checked ? 'bg-primary' : 'bg-input')}>
        <span className={cn('absolute top-0.5 size-4 rounded-full bg-white shadow-sm transition-[left] duration-150',
          checked ? 'left-[1.125rem]' : 'left-0.5')} />
      </span>
      {children}
    </button>
  )
}

function Card({ title, aside, children, className }: { title: string; aside?: ReactNode; children: ReactNode; className?: string }) {
  return (
    <section className={cn('rounded-xl border border-border bg-card p-5 shadow-[var(--shadow-card)]', className)}>
      <div className="flex items-baseline justify-between gap-3">
        <h2 className="text-sm font-semibold uppercase tracking-wide text-muted-foreground">{title}</h2>
        {aside}
      </div>
      <div className="mt-4">{children}</div>
    </section>
  )
}

/** One head angle against its allowed band, centred on the calibration. */
function AngleGauge({ label, value, centre, limit, span = 45 }: {
  label: string; value: number | null; centre: number; limit: number; span?: number
}) {
  const at = (v: number) => ((Math.max(-span, Math.min(span, v)) + span) / (2 * span)) * 100
  const pass = value !== null && Math.abs(value - centre) < limit
  return (
    <div>
      <div className="flex items-baseline justify-between text-sm">
        <span className="font-medium">{label}</span>
        <span className="tabular-nums text-muted-foreground">
          <span className={cn('font-semibold', value === null ? '' : pass ? 'text-success' : 'text-warning')}>
            {value === null ? 'n/a' : degrees(value)}
          </span>{' '}
          / limit {limit}°
        </span>
      </div>
      <div className="relative mt-2 h-2.5 rounded-full bg-muted">
        <div className="absolute inset-y-0 rounded-full bg-success/25"
          style={{ left: `${at(centre - limit)}%`, width: `${at(centre + limit) - at(centre - limit)}%` }} />
        <div className="absolute inset-y-[-3px] w-px bg-muted-foreground/50" style={{ left: `${at(centre)}%` }} />
        {value !== null && (
          <div className={cn('absolute top-1/2 size-3.5 -translate-x-1/2 -translate-y-1/2 rounded-full border-2 border-card transition-[left] duration-100',
            pass ? 'bg-success' : 'bg-warning')} style={{ left: `${at(value)}%` }} />
        )}
      </div>
    </div>
  )
}

/** One eye as the camera sees it, mirrored like the preview, with its iris box. */
function EyeDiagram({ label, eye, t, c }: { label: string; eye: EyeFeatures | null; t: Thresholds; c: Calibration }) {
  const open = eyeOpen(eye, t)
  const inside = eye && open ? irisInBox(eye, t, c) : null
  const mapX = (v: number) => 10 + (1 - v) * 100
  const mapY = (v: number) => 14 + v * 36
  const bx0 = mapX(t.irisX[1] + c.irisX - 0.5)
  const bx1 = mapX(t.irisX[0] + c.irisX - 0.5)
  const by0 = mapY(t.irisY[0] + c.irisY - 0.5)
  const by1 = mapY(t.irisY[1] + c.irisY - 0.5)
  const tone = inside === null ? 'text-muted-foreground' : inside ? 'text-success' : 'text-warning'
  return (
    <figure className="min-w-0">
      <svg viewBox="0 0 120 64" className="w-full" role="img"
        aria-label={`${label}: ${!eye ? 'not found' : !open ? 'closed or too small' : inside ? 'iris inside the box' : 'iris outside the box'}`}>
        <path d="M8 32 Q60 -2 112 32 Q60 66 8 32 Z" className="fill-muted stroke-border" strokeWidth="1.5" />
        <rect x={bx0} y={by0} width={bx1 - bx0} height={by1 - by0} rx="2"
          className={cn('fill-none stroke-current', tone)} strokeWidth="1.2" strokeDasharray="3 2" />
        {eye && open && (
          <circle cx={mapX(Math.max(0, Math.min(1, eye.irisX)))} cy={mapY(Math.max(0, Math.min(1, eye.irisY)))} r="7"
            className={cn('fill-current transition-[cx,cy] duration-100', tone)} />
        )}
        {eye && !open && <line x1="20" y1="32" x2="100" y2="32" className="stroke-muted-foreground" strokeWidth="2" strokeLinecap="round" />}
      </svg>
      <figcaption className="mt-1 flex items-baseline justify-between text-sm">
        <span className="font-medium">{label}</span>
        <span className={cn('tabular-nums', tone)}>
          {!eye ? 'not found' : !open ? 'closed' : `open ${fixed(eye.open)}`}
        </span>
      </figcaption>
    </figure>
  )
}

function Timeline({ history, now }: { history: { at: number; verdict: Verdict }[]; now: number }) {
  const buckets = 60
  const size = HISTORY_MS / buckets
  const cells: (Verdict | null)[] = Array.from({ length: buckets }, () => null)
  for (const entry of history) {
    const index = Math.floor((entry.at - (now - HISTORY_MS)) / size)
    if (index >= 0 && index < buckets) cells[index] = entry.verdict
  }
  return (
    <div className="flex h-7 gap-px overflow-hidden rounded-md" aria-hidden>
      {cells.map((verdict, i) => (
        <div key={i} className={cn('flex-1', verdict ? VERDICTS[verdict].bar : 'bg-muted')} />
      ))}
    </div>
  )
}

export function GazeDemo() {
  const videoRef = useRef<HTMLVideoElement>(null)
  const canvasRef = useRef<HTMLCanvasElement>(null)
  const landmarker = useRef<FaceLandmarker | null>(null)
  const stream = useRef<MediaStream | null>(null)
  const generation = useRef(0)
  const layersRef = useRef<Record<Layer, boolean>>({ outline: true, mesh: false, eyes: true, head: true, gaze: true })
  const trackersRef = useRef(true)
  const calibrationRef = useRef<Calibration | null>(null)
  const calibrating = useRef<{ startedAt: number; until: number | null; frames: FaceFeatures[] } | null>(null)
  const history = useRef<{ at: number; verdict: Verdict }[]>([])
  const wireSamples = useRef<{ at: number; observation: FaceObservation }[]>([])

  const [camera, setCamera] = useState<CameraState>({ kind: 'off' })
  const [trackers, setTrackers] = useState(true)
  const [layers, setLayers] = useState(layersRef.current)
  const [calibration, setCalibration] = useState<CalibrationState>({ kind: 'none' })
  const [reading, setReading] = useState<Reading | null>(null)
  const [now, setNow] = useState(() => performance.now())

  useEffect(() => { layersRef.current = layers }, [layers])
  useEffect(() => { trackersRef.current = trackers }, [trackers])

  function stopCamera() {
    generation.current += 1
    stream.current?.getTracks().forEach(track => track.stop())
    stream.current = null
    if (videoRef.current) videoRef.current.srcObject = null
    calibrating.current = null
    history.current = []
    wireSamples.current = []
    setReading(null)
    setCalibration(current => current.kind === 'running' ? { kind: 'none' } : current)
    setCamera({ kind: 'off' })
  }

  async function startCamera() {
    const mine = ++generation.current
    setCamera({ kind: 'starting', text: 'Waiting for camera permission' })
    try {
      const acquired = await navigator.mediaDevices.getUserMedia({
        video: { width: { ideal: 640 }, height: { ideal: 480 }, facingMode: 'user' }, audio: false,
      })
      if (mine !== generation.current) { acquired.getTracks().forEach(track => track.stop()); return }
      stream.current = acquired
      acquired.getVideoTracks()[0].onended = () => { if (mine === generation.current) stopCamera() }
      const video = videoRef.current!
      video.srcObject = acquired
      await video.play()
      if (!landmarker.current) {
        setCamera({ kind: 'starting', text: 'Loading the face model' })
        landmarker.current = await createLandmarker()
      }
      if (mine !== generation.current) return
      setCamera({ kind: 'on' })
    } catch (error) {
      if (mine !== generation.current) return
      stream.current?.getTracks().forEach(track => track.stop())
      stream.current = null
      setCamera({ kind: 'error', text: cameraError(error) })
    }
  }

  // The detection loop: every new video frame, at most every DETECT_EVERY_MS.
  useEffect(() => {
    if (camera.kind !== 'on') return
    const video = videoRef.current!
    const canvas = canvasRef.current!
    const ctx = canvas.getContext('2d')!
    let frame = 0
    let lastRun = 0
    let lastVideoTime = -1
    let lastPublish = 0
    const runs: number[] = []
    const tick = () => {
      frame = requestAnimationFrame(tick)
      const at = performance.now()
      if (!landmarker.current || video.readyState < 2 || video.currentTime === lastVideoTime || at - lastRun < DETECT_EVERY_MS) return
      lastRun = at
      lastVideoTime = video.currentTime
      const result = landmarker.current.detectForVideo(video, at)
      const features = faceFeatures(result.faceLandmarks, result.facialTransformationMatrixes?.map(matrix => matrix.data))

      const pending = calibrating.current
      if (pending) {
        if (features.faces === 1) {
          pending.until ??= at + CALIBRATION_MS
          pending.frames.push(features)
        }
        if (pending.until !== null && at >= pending.until) {
          calibrating.current = null
          const value = calibrate(pending.frames)
          calibrationRef.current = value
          setCalibration(value
            ? { kind: 'done', value }
            : { kind: 'failed', text: 'That did not work: your face was not clearly facing the screen. The standard limits are used.' })
        } else if (at - pending.startedAt > CALIBRATION_GIVE_UP_MS) {
          calibrating.current = null
          setCalibration({ kind: 'failed', text: 'No face was seen, so calibration did not finish. The standard limits are used.' })
        }
      }

      const t = thresholdsFor(calibrationRef.current)
      const observation = classifyFace(features, t, calibrationRef.current)
      const verdict = verdictOf(features, observation)
      history.current.push({ at, verdict })
      wireSamples.current.push({ at, observation })
      while (history.current.length && history.current[0].at < at - HISTORY_MS) history.current.shift()
      while (wireSamples.current.length && wireSamples.current[0].at < at - WIRE_WINDOW_MS) wireSamples.current.shift()
      runs.push(at)
      while (runs.length && runs[0] < at - 1000) runs.shift()

      if (canvas.width !== video.videoWidth || canvas.height !== video.videoHeight) {
        canvas.width = video.videoWidth
        canvas.height = video.videoHeight
      }
      ctx.clearRect(0, 0, canvas.width, canvas.height)
      if (trackersRef.current && result.faceLandmarks.length) {
        for (const face of result.faceLandmarks) {
          drawOverlay(ctx, face, features, observation, result.faceLandmarks.length === 1
            ? layersRef.current
            : { ...layersRef.current, head: false, gaze: false }, t, calibrationRef.current)
        }
      }

      if (at - lastPublish >= 100) {
        lastPublish = at
        setReading({ features, observation, verdict, calibration: calibrationRef.current, fps: runs.length })
        setNow(at)
      }
    }
    frame = requestAnimationFrame(tick)
    return () => {
      cancelAnimationFrame(frame)
      ctx.clearRect(0, 0, canvas.width, canvas.height)
    }
  }, [camera.kind])

  useEffect(() => () => { stream.current?.getTracks().forEach(track => track.stop()) }, [])

  function startCalibration() {
    calibrating.current = { startedAt: performance.now(), until: null, frames: [] }
    calibrationRef.current = null
    setCalibration({ kind: 'running', startedAt: performance.now() })
  }

  function resetCalibration() {
    calibrating.current = null
    calibrationRef.current = null
    setCalibration({ kind: 'none' })
  }

  const on = camera.kind === 'on'
  const f = reading?.features
  const cal = reading?.calibration ?? null
  const c = cal ?? NO_CALIBRATION
  const t = thresholdsFor(cal)
  const checks = f ? checksFor(f, t, cal) : []
  const failing = checks.find(check => check.pass === false)
  const judged = history.current.filter(entry => entry.verdict === 'facing' || entry.verdict === 'away')
  const ratio = judged.length ? judged.filter(entry => entry.verdict === 'facing').length / judged.length : null
  const wire: AttentionSummary | null = on && reading
    ? summary(wireSamples.current.map(sample => sample.observation), [], WIRE_WINDOW_MS / 1000)
    : null
  const calibrationProgress = calibration.kind === 'running'
    ? Math.min(100, ((now - calibration.startedAt) / CALIBRATION_MS) * 100)
    : 0

  return (
    <div className="mx-auto max-w-5xl px-4 py-8 sm:py-10">
      <header className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <Wordmark />
          <h1 className="mt-5 text-[1.75rem] font-bold leading-tight">Camera attention demo</h1>
          <p className="mt-1 max-w-2xl text-muted-foreground">
            What the optional camera signal sees, and how it decides whether a student is facing the screen.
            This is the same judgement the classroom uses.
          </p>
        </div>
        <p className="inline-flex items-center gap-1.5 rounded-full bg-accent px-3 py-1 text-sm font-semibold text-accent-foreground">
          <ShieldCheck size={15} aria-hidden /> Runs on this device. No picture is sent or kept.
        </p>
      </header>

      <section className="mt-6 overflow-hidden rounded-xl border border-border bg-card shadow-[var(--shadow-card)]">
        <div className="relative aspect-[4/3] w-full bg-[#101119] sm:aspect-video">
          <video ref={videoRef} muted playsInline
            className={cn('absolute inset-0 size-full -scale-x-100 object-contain', !on && 'invisible')} />
          <canvas ref={canvasRef} aria-hidden
            className={cn('pointer-events-none absolute inset-0 size-full -scale-x-100 object-contain', !on && 'invisible')} />

          {!on && (
            <div className="absolute inset-0 grid place-items-center p-6 text-center text-white">
              <div className="max-w-sm">
                <span className="mx-auto grid size-14 place-items-center rounded-full bg-white/10">
                  {camera.kind === 'error' ? <CameraOff size={26} aria-hidden /> : <Camera size={26} aria-hidden />}
                </span>
                <p className="mt-4 text-lg font-semibold" role="status">
                  {camera.kind === 'starting' ? `${camera.text}…` : camera.kind === 'error' ? 'The camera did not start' : 'Camera off'}
                </p>
                <p className="mt-1 text-sm text-white/70">
                  {camera.kind === 'error' ? camera.text
                    : camera.kind === 'starting' ? 'The face model loads once, from this site.'
                    : 'Turn the camera on to see the trackers and the live reading.'}
                </p>
                {(camera.kind === 'off' || camera.kind === 'error') && (
                  <button type="button" onClick={() => { void startCamera() }} className={cn(buttonStyles(), 'mt-5')}>
                    <Camera size={16} aria-hidden /> {camera.kind === 'error' ? 'Try again' : 'Turn on camera'}
                  </button>
                )}
              </div>
            </div>
          )}

          {on && reading && (
            <>
              <p role="status" aria-live="polite"
                className={cn('absolute left-3 top-3 rounded-full px-3 py-1 text-sm font-semibold shadow-sm', VERDICTS[reading.verdict].badge)}>
                {VERDICTS[reading.verdict].label}
              </p>
              <p className="absolute right-3 top-3 rounded-full bg-black/60 px-2.5 py-1 text-xs font-medium tabular-nums text-white">
                {reading.fps} checks/s{cal ? ' · calibrated' : ''}
              </p>
            </>
          )}
          {calibration.kind === 'running' && (
            <div className="absolute inset-x-0 bottom-0 bg-black/70 px-4 py-3 text-white">
              <p className="text-sm font-semibold">Look at the middle of the screen</p>
              <div className="mt-2 h-1.5 overflow-hidden rounded-full bg-white/20">
                <div className="h-full rounded-full bg-highlight" style={{ width: `${calibrationProgress}%` }} />
              </div>
            </div>
          )}
        </div>

        <div className="flex flex-wrap items-center gap-x-3 gap-y-3 border-t border-border p-4">
          {on || camera.kind === 'starting' ? (
            <button type="button" onClick={stopCamera} className={buttonStyles({ intent: 'secondary' })}>
              <CameraOff size={16} aria-hidden /> Turn off camera
            </button>
          ) : (
            <button type="button" onClick={() => { void startCamera() }} className={buttonStyles()}>
              <Camera size={16} aria-hidden /> Turn on camera
            </button>
          )}
          <button type="button" onClick={startCalibration} disabled={!on || calibration.kind === 'running'}
            className={buttonStyles({ intent: 'secondary' })}>
            <Crosshair size={16} aria-hidden />
            {calibration.kind === 'running' ? 'Calibrating…' : calibration.kind === 'done' ? 'Calibrate again' : 'Calibrate (3 s)'}
          </button>
          {calibration.kind === 'done' && (
            <button type="button" onClick={resetCalibration} className={buttonStyles({ intent: 'quiet' })}>
              <RotateCcw size={16} aria-hidden /> Use standard limits
            </button>
          )}

          <div className="flex flex-wrap items-center gap-2 sm:ml-auto" role="group" aria-label="Trackers shown on the camera">
            <Switch checked={trackers} onChange={setTrackers}>Trackers</Switch>
            {LAYERS.map(layer => (
              <Switch key={layer.id} checked={layers[layer.id]} disabled={!trackers}
                onChange={value => setLayers(current => ({ ...current, [layer.id]: value }))}>
                {layer.label}
              </Switch>
            ))}
          </div>
        </div>
        {(calibration.kind === 'failed' || calibration.kind === 'done') && (
          <p className={cn('border-t border-border px-4 py-3 text-sm', calibration.kind === 'failed' ? 'text-warning' : 'text-foreground')} role="status">
            {calibration.kind === 'done'
              ? `Calibrated to where you look: centre at turn ${degrees(calibration.value.yaw)}, tilt ${degrees(calibration.value.pitch)}, lean ${degrees(calibration.value.roll)}. Tighter limits now apply.`
              : calibration.text}
          </p>
        )}
      </section>

      <div className="mt-5 grid gap-5 lg:grid-cols-2">
        <Card title="Reading" aside={on && reading && <span className="text-sm text-muted-foreground">{cal ? 'Calibrated limits' : 'Standard limits'}</span>}>
          {on && reading ? (
            <>
              <p className="text-2xl font-bold">{VERDICTS[reading.verdict].label}</p>
              <p className="mt-1 text-sm text-muted-foreground">
                {reading.verdict === 'away' && failing ? `${failing.name} is ${failing.value} (${failing.limit}).` : VERDICTS[reading.verdict].note}
              </p>
              <ul className="mt-4 divide-y divide-border text-sm">
                {checks.map(check => (
                  <li key={check.name} className="flex items-center justify-between gap-3 py-1.5">
                    <span className="flex items-center gap-2">
                      <span aria-hidden className={cn('size-2 rounded-full',
                        check.pass === null ? 'bg-muted-foreground/40' : check.pass ? 'bg-success' : 'bg-warning')} />
                      {check.name}
                    </span>
                    <span className="tabular-nums text-muted-foreground">
                      <span className="font-semibold text-foreground">{check.value}</span>
                      <span className="sr-only">{check.pass === null ? ', not checked' : check.pass ? ', passes' : ', fails'}</span>
                      {' '}· {check.limit}
                    </span>
                  </li>
                ))}
              </ul>
            </>
          ) : (
            <p className="text-sm text-muted-foreground">Turn the camera on to see each check as it is made.</p>
          )}
        </Card>

        <Card title="Head pose" aside={<span className="text-sm text-muted-foreground">from the face model</span>}>
          <div className="space-y-5">
            <AngleGauge label="Turn (left / right)" value={f?.pose?.yaw ?? null} centre={c.yaw} limit={t.maxYawDegrees} />
            <AngleGauge label="Tilt (up / down)" value={f?.pose?.pitch ?? null} centre={c.pitch} limit={t.maxPitchDegrees} />
            <AngleGauge label="Lean (sideways)" value={f?.pose?.roll ?? null} centre={c.roll} limit={t.maxRollDegrees} />
          </div>
          <p className="mt-5 text-sm text-muted-foreground">
            The green band is what counts as facing the screen. Calibrating moves its centre to where you
            look and narrows it, so notes on the desk are told apart from the screen.
          </p>
        </Card>

        <Card title="Eyes" aside={<span className="text-sm text-muted-foreground">iris inside the dashed box</span>}>
          <div className="grid grid-cols-2 gap-5">
            <EyeDiagram label="Left eye" eye={f?.rightEye ?? null} t={t} c={c} />
            <EyeDiagram label="Right eye" eye={f?.leftEye ?? null} t={t} c={c} />
          </div>
          <p className="mt-4 text-sm text-muted-foreground">
            Both eyes must be open and both irises inside the box. A closed or unreadable eye makes the
            reading unavailable, not a mark against the student.
          </p>
        </Card>

        <Card title="Last 30 seconds" aside={
          <span className="text-sm tabular-nums text-muted-foreground">
            {ratio === null ? 'no judged frames' : `${Math.round(ratio * 100)}% facing the screen`}
          </span>
        }>
          <Timeline history={on ? history.current : []} now={now} />
          <ul className="mt-3 flex flex-wrap gap-x-4 gap-y-1 text-xs text-muted-foreground">
            {(['facing', 'away', 'unclear', 'many'] as const).map(v => (
              <li key={v} className="flex items-center gap-1.5">
                <span aria-hidden className={cn('size-2.5 rounded-sm', VERDICTS[v].bar)} />
                {v === 'unclear' ? 'No face or unclear' : VERDICTS[v].label}
              </li>
            ))}
          </ul>
          <h3 className="mt-5 text-sm font-semibold">What would be sent to the lecturer</h3>
          <p className="mt-1 text-sm text-muted-foreground">
            Only this summary of the last {WIRE_WINDOW_MS / 1000} seconds leaves the device in a class. No
            picture, landmarks or angles. Microphone off here, so speaking is unavailable.
          </p>
          <pre className="mt-3 overflow-x-auto rounded-lg bg-muted px-4 py-3 text-xs leading-relaxed">
            {JSON.stringify(wire ?? { gaze_on_screen_ratio: null, face_present: null, speaking: null, window_seconds: 5 }, (_, v) =>
              typeof v === 'number' && !Number.isInteger(v) ? Number(v.toFixed(2)) : v, 2)}
          </pre>
        </Card>
      </div>
    </div>
  )
}
