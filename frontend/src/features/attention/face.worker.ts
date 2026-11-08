import { FaceLandmarker, FilesetResolver } from '@mediapipe/tasks-vision'
import {
  ADAPTATION, GAZE_MODEL, calibrate, classifyAdaptive, classifyFace, faceFeatures, learn, startAdaptation, thresholdsFor,
  type AdaptiveState, type Calibration, type FaceFeatures,
} from './signals'
import {
  LIVENESS, applyLiveness, dueForCheck, isSpoof, noteFrame, recordCheck, startLiveness, type LivenessState,
} from './liveness'
import type { LivenessModel } from './livenessModel'

// How long the student looks at the screen to calibrate, in the timestamps
// the frames carry (milliseconds).
const CALIBRATION_MS = 3000

let detector: FaceLandmarker | undefined
let withFeatures = false
let calibration: Calibration | null = null
let calibrating: { until: number | null; frames: FaceFeatures[] } | null = null
// #166: this student's learned normal, in this worker only. Null while
// ADAPTATION is off. Frames before `learnUntil` are a good moment to learn from.
let adaptive: AdaptiveState | null = ADAPTATION ? startAdaptation(null) : null
let learnUntil = -Infinity
// How long one "looking at the screen" hint (a key typed in an answer) counts for.
const GOOD_MOMENT_MS = 1500
// #165: the anti-spoofing model, loaded only while LIVENESS is on or the
// recorder asks for a live score on every frame. Its recent checks stay here.
let livenessModel: LivenessModel | null = null
let withLiveScores = false
let liveness: LivenessState = startLiveness()

self.onmessage = async (event: MessageEvent) => {
  const { type, base, frame, timestamp } = event.data
  try {
    if (type === 'init') {
      // The recorder (eval/attention-recorder.html) asks for the features
      // too; the classroom never does, so they stay in this worker there.
      withFeatures = Boolean(event.data.withFeatures)
      withLiveScores = Boolean(event.data.withLiveScores)
      const files = await FilesetResolver.forVisionTasks(`${base}vision`, true)
      detector = await FaceLandmarker.createFromOptions(files, {
        baseOptions: { modelAssetPath: `${base}face_landmarker.task`, delegate: 'CPU' },
        runningMode: 'VIDEO', numFaces: 2,
        // Real yaw, pitch and roll, so looking down at notes is not forward.
        outputFacialTransformationMatrixes: true,
      })
      if (LIVENESS || withLiveScores) {
        // If the model cannot load, faces are judged as before: never reject
        // a real student because the check itself is unavailable.
        try {
          const { loadLivenessModel } = await import('./livenessModel')
          livenessModel = await loadLivenessModel(base)
        } catch { livenessModel = null }
      }
      self.postMessage({ type: 'ready', liveness: livenessModel !== null })
    } else if (type === 'calibrate') {
      calibration = null
      calibrating = { until: null, frames: [] }
    } else if (type === 'cancel-calibration') {
      calibrating = null
    } else if (type === 'looking') {
      learnUntil = Math.max(learnUntil, timestamp + GOOD_MOMENT_MS)
    } else if (type === 'frame' && detector) {
      const result = detector.detectForVideo(frame, timestamp)
      const features = faceFeatures(
        result.faceLandmarks,
        result.facialTransformationMatrixes?.map(matrix => matrix.data),
      )
      if (calibrating) {
        const until = (calibrating.until ??= timestamp + CALIBRATION_MS)
        calibrating.frames.push(features)
        if (timestamp >= until) {
          // Only the offsets are kept, here in the browser; nothing new is sent.
          calibration = calibrate(calibrating.frames)
          if (ADAPTATION) {
            // A new calibration starts the learned normal again, from its frames.
            adaptive = startAdaptation(calibration)
            for (const f of calibrating.frames) adaptive = learn(adaptive, f, thresholdsFor(calibration), ADAPTATION, GAZE_MODEL)
          }
          calibrating = null
          self.postMessage({ type: 'calibrated', ok: calibration !== null })
        }
      }
      // #165: check now and then that the one face in view is a live person.
      const faces = result.faceLandmarks.length
      if (LIVENESS) liveness = noteFrame(liveness, faces, timestamp, LIVENESS)
      let live: { live: number; ms: number } | null = null
      if (livenessModel && faces === 1 && (withLiveScores || (LIVENESS && dueForCheck(liveness, timestamp, LIVENESS)))) {
        live = await livenessModel.check(frame, result.faceLandmarks[0]).catch(() => null)
        if (LIVENESS) liveness = recordCheck(liveness, live?.live ?? Number.NaN, timestamp, LIVENESS)
      }
      const spoof = LIVENESS !== null && isSpoof(liveness, LIVENESS)
      const base = thresholdsFor(calibration)
      // A photo is not this student's normal, so nothing is learned from it.
      if (ADAPTATION && adaptive && !calibrating && !spoof && timestamp < learnUntil) adaptive = learn(adaptive, features, base, ADAPTATION, GAZE_MODEL)
      const value = ADAPTATION && adaptive
        ? classifyAdaptive(features, adaptive, base, ADAPTATION, GAZE_MODEL)
        : classifyFace(features, base, calibration, GAZE_MODEL)
      self.postMessage({
        type: 'observation',
        value: applyLiveness(value, spoof),
        ...(withFeatures ? { features, live } : {}),
      })
    }
  } catch {
    self.postMessage({ type: 'error' })
  } finally {
    frame?.close()
  }
}
