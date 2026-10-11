import { FaceLandmarker, FilesetResolver } from '@mediapipe/tasks-vision'
import { observeFace } from './signals'

let detector: FaceLandmarker | undefined
self.onmessage = async (event: MessageEvent) => {
  const { type, base, frame, timestamp } = event.data
  try {
    if (type === 'init') {
      const files = await FilesetResolver.forVisionTasks(`${base}vision`, true)
      detector = await FaceLandmarker.createFromOptions(files, {
        baseOptions: { modelAssetPath: `${base}face_landmarker.task`, delegate: 'CPU' },
        runningMode: 'VIDEO', numFaces: 2,
      })
      self.postMessage({ type: 'ready' })
    } else if (type === 'frame' && detector) {
      const result = detector.detectForVideo(frame, timestamp)
      self.postMessage({ type: 'observation', value: observeFace(result.faceLandmarks) })
    }
  } catch {
    self.postMessage({ type: 'error' })
  } finally {
    frame?.close()
  }
}
