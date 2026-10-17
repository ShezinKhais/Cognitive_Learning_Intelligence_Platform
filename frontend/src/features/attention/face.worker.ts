import { FaceLandmarker, FilesetResolver } from '@mediapipe/tasks-vision'
import { calibrate, classifyFace, faceFeatures, type Calibration, type FaceFeatures } from './signals'

// How long the student looks at the screen to calibrate, in the timestamps
// the frames carry (milliseconds).
const CALIBRATION_MS = 3000

let detector: FaceLandmarker | undefined
let withFeatures = false
let calibration: Calibration | null = null
let calibrating: { until: number | null; frames: FaceFeatures[] } | null = null

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
          calibrating = null
          self.postMessage({ type: 'calibrated', ok: calibration !== null })
        }
      }
      self.postMessage({
        type: 'observation',
        value: classifyFace(features, undefined, calibration),
        ...(withFeatures ? { features } : {}),
      })
    }
  } catch {
    self.postMessage({ type: 'error' })
  } finally {
    frame?.close()
  }
}
