// Derived observations only: no media, landmarks or device identifiers on the wire.
export interface AttentionSummary {
  gaze_on_screen_ratio: number | null
  face_present: boolean | null
  speaking: boolean | null
  window_seconds: number
}
export interface FaceObservation {
  face: boolean | null
  forward: boolean | null
  head: 'forward' | 'turned' | 'unavailable'
}
interface Point { x: number; y: number; z: number }

/** Coarse camera-facing proxy, not eye tracking or an attention judgement. */
export function observeFace(faces: Point[][]): FaceObservation {
  const unavailable: FaceObservation = { face: null, forward: null, head: 'unavailable' }
  if (!faces.length) return { ...unavailable, face: false }
  if (faces.length !== 1) return unavailable
  const p = faces[0]
  const ids = [1, 33, 133, 159, 145, 362, 263, 386, 374, 468, 473]
  if (ids.some(i => !p[i] || ![p[i].x, p[i].y, p[i].z].every(Number.isFinite))) return unavailable
  const width = Math.abs(p[263].x - p[33].x)
  if (width < 0.03) return { ...unavailable, face: true }
  const yaw = Math.abs(p[1].x - (p[33].x + p[263].x) / 2) / width
  const roll = Math.abs(p[33].y - p[263].y) / width
  const head = yaw < 0.22 && roll < 0.3 ? 'forward' : 'turned'
  function eye(a: number, b: number, top: number, bottom: number, iris: number) {
    const w = Math.abs(p[a].x - p[b].x)
    const h = Math.abs(p[top].y - p[bottom].y)
    if (w < 0.005 || h / w < 0.12) return null
    const x = (p[iris].x - Math.min(p[a].x, p[b].x)) / w
    const y = (p[iris].y - Math.min(p[top].y, p[bottom].y)) / h
    return x >= 0.2 && x <= 0.8 && y >= 0.1 && y <= 0.9
  }
  const left = eye(33, 133, 159, 145, 468)
  const right = eye(362, 263, 386, 374, 473)
  return { face: true, head, forward: left === null || right === null ? null : head === 'forward' && left && right }
}

/** Null is absence, not a negative signal. Only the frozen wire shape leaves. */
export function summary(samples: FaceObservation[], speech: boolean[], seconds: number): AttentionSummary {
  const gaze = samples.filter(s => s.forward !== null)
  const faces = samples.filter(s => s.face !== null)
  return {
    gaze_on_screen_ratio: gaze.length ? gaze.filter(s => s.forward).length / gaze.length : null,
    face_present: faces.length ? faces.some(s => s.face) : null,
    speaking: speech.length ? speech.some(Boolean) : null,
    window_seconds: Math.min(3600, Math.max(0.001, seconds)),
  }
}
