import { FaceLandmarker, FilesetResolver } from '@mediapipe/tasks-vision'
import {
  ADAPTATION, GAZE_MODEL, calibrate, classifyAdaptive, classifyFace, faceFeatures, learn, startAdaptation, thresholdsFor,
  type AdaptiveState, type Calibration, type FaceFeatures,
} from './signals'

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

self.onmessage = async (event: MessageEvent) => {
  const { type, base, frame, timestamp } = event.data
  try {
    if (type === 'init') {
      // The recorder (eval/attention-recorder.html) asks for the features
      // too; the classroom never does, so they stay in this worker there.
      withFeatures = Boolean(event.data.withFeatures)
      const files = await FilesetResolver.forVisionTasks(`${base}vision`, true)
      detector = await FaceLandmarker.createFromOptions(files, {
        baseOptions: { modelAssetPath: `${base}face_landmarker.task`, delegate: 'CPU' },
        runningMode: 'VIDEO', numFaces: 2,
        // Real yaw, pitch and roll, so looking down at notes is not forward.
        outputFacialTransformationMatrixes: true,
      })
      self.postMessage({ type: 'ready' })
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
      const base = thresholdsFor(calibration)
      if (ADAPTATION && adaptive && !calibrating && timestamp < learnUntil) adaptive = learn(adaptive, features, base, ADAPTATION, GAZE_MODEL)
      self.postMessage({
        type: 'observation',
        value: ADAPTATION && adaptive
          ? classifyAdaptive(features, adaptive, base, ADAPTATION, GAZE_MODEL)
          : classifyFace(features, base, calibration, GAZE_MODEL),
        ...(withFeatures ? { features } : {}),
      })
    }
  } catch {
    self.postMessage({ type: 'error' })
  } finally {
    frame?.close()
  }
}
