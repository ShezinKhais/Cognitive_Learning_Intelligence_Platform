import { FaceLandmarker, FilesetResolver } from '@mediapipe/tasks-vision'
import {
  ADAPTATION, GAZE_MODEL, calibrate, classifyAdaptive, classifyFace, faceFeatures, learn, startAdaptation, thresholdsFor,
  type AdaptiveState, type Calibration, type FaceFeatures,
} from './signals'
import {
  LIVENESS, applyLiveness, forCalibration, livenessFrame, loadInBackground, mayLearn, startLiveness, wantsLivenessModel, type LivenessState,
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
      // The camera is ready now; the anti-spoofing model, if wanted, loads
      // afterwards so a slow or failed load never holds attention up. Until it
      // arrives, or if it never does, faces are judged as before.
      self.postMessage({ type: 'ready' })
      if (wantsLivenessModel(LIVENESS, withLiveScores)) {
        void loadInBackground(async () => (await import('./livenessModel')).loadLivenessModel(base)).then(model => {
          livenessModel = model
          self.postMessage({ type: 'liveness', ok: model !== null })
        })
      }
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
      // #165: check now and then that the one face in view is a live person,
      // first, so a face judged not live is kept out of calibration too.
      const model = livenessModel
      const step = await livenessFrame(
        liveness, result.faceLandmarks.length, timestamp, LIVENESS,
        model ? () => model.check(frame, result.faceLandmarks[0]) : null, withLiveScores,
      )
      liveness = step.state
      const { live, spoof } = step
      if (calibrating) {
        const until = (calibrating.until ??= timestamp + CALIBRATION_MS)
        // A face judged not live is not this student's centre, and calibration
        // frames also seed adaptation (#166), so neither learns from a photo.
        calibrating.frames = forCalibration(calibrating.frames, features, spoof)
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
      // A photo is not this student's normal, so nothing is learned from it.
      if (ADAPTATION && adaptive && mayLearn(spoof, calibrating !== null, timestamp, learnUntil)) adaptive = learn(adaptive, features, base, ADAPTATION, GAZE_MODEL)
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
