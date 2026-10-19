import type { FaceObservation } from './signals'

const assets = new URL(`${import.meta.env.BASE_URL}attention/`, location.origin).href
// The camera's worker while it runs, so the page can ask it to calibrate.
let cameraWorker: Worker | undefined
export type CalibrationResult = 'done' | 'failed' | 'timeout'
let calibrated: ((result: CalibrationResult) => void) | undefined
let calibrationTimer: ReturnType<typeof setTimeout> | undefined
// Calibration ends on frame timestamps, and no frames come while the camera is
// muted or stalled, so it gives up after this long rather than wait forever.
export const CALIBRATION_TIMEOUT_MS = 8000

/**
 * Ask the running camera to learn this student's own centre from the next
 * three seconds of frames. `done` hears whether a usable calibration was
 * found, or that frames stopped coming. False when no camera is running.
 */
export function calibrateCamera(done: (result: CalibrationResult) => void): boolean {
  if (!cameraWorker) return false
  const worker = cameraWorker
  clearTimeout(calibrationTimer)
  calibrated = done
  calibrationTimer = setTimeout(() => {
    if (calibrated !== done) return
    calibrated = undefined
    // The worker stops collecting too, so it cannot calibrate later unseen.
    worker.postMessage({ type: 'cancel-calibration' })
    done('timeout')
  }, CALIBRATION_TIMEOUT_MS)
  worker.postMessage({ type: 'calibrate' })
  return true
}

export function stopTracks(stream: MediaStream): void {
  stream.getTracks().forEach(track => track.stop())
}

async function openStream(signal: AbortSignal, constraints: MediaStreamConstraints, failed: () => void): Promise<MediaStream> {
  signal.throwIfAborted()
  const stream = await navigator.mediaDevices.getUserMedia(constraints)
  if (signal.aborted) {
    stopTracks(stream)
    signal.throwIfAborted()
  }
  stream.getTracks().forEach(track => { track.onended = failed })
  return stream
}

export async function startCamera(signal: AbortSignal, report: (value: FaceObservation) => void, failed: () => void): Promise<void> {
  let stream: MediaStream | undefined
  let worker: Worker | undefined
  let timer: ReturnType<typeof setInterval> | undefined
  let deadline: ReturnType<typeof setTimeout> | undefined
  let busy = false
  const video = document.createElement('video')
  video.muted = true
  video.playsInline = true
  const stop = () => {
    if (stream) stopTracks(stream)
    worker?.terminate()
    if (cameraWorker === worker) { cameraWorker = undefined; calibrated = undefined; clearTimeout(calibrationTimer) }
    clearInterval(timer)
    clearTimeout(deadline)
    video.pause()
    video.srcObject = null
    signal.removeEventListener('abort', stop)
  }
  signal.addEventListener('abort', stop, { once: true })
  try {
    stream = await openStream(signal, { video: { width: { ideal: 320 }, height: { ideal: 240 }, frameRate: { ideal: 5, max: 10 } }, audio: false }, () => { stop(); failed() })
    stream.getTracks().forEach(track => {
      track.onmute = () => report({ face: null, forward: null, head: 'unavailable' })
    })
    video.srcObject = stream
    await video.play()
    signal.throwIfAborted()
    worker = new Worker(new URL('./face.worker.ts', import.meta.url), { type: 'module' })
    await new Promise<void>((resolve, reject) => {
      const abort = () => reject(new DOMException('Stopped', 'AbortError'))
      signal.addEventListener('abort', abort, { once: true })
      const finish = (error?: Error) => {
        clearTimeout(deadline)
        signal.removeEventListener('abort', abort)
        if (error) reject(error)
        else resolve()
      }
      deadline = setTimeout(() => finish(new Error('Camera model timed out')), 30_000)
      worker!.onerror = () => { finish(new Error('Camera worker unavailable')); stop(); failed() }
      worker!.onmessage = event => {
        if (signal.aborted) return
        if (event.data.type === 'ready') finish()
        else if (event.data.type === 'error') { finish(new Error('Camera processing unavailable')); stop(); failed() }
        else if (event.data.type === 'observation') { busy = false; report(event.data.value) }
        else if (event.data.type === 'calibrated') {
          clearTimeout(calibrationTimer)
          calibrated?.(event.data.ok ? 'done' : 'failed')
          calibrated = undefined
        }
      }
      worker!.postMessage({ type: 'init', base: assets })
    })
    signal.throwIfAborted()
    cameraWorker = worker
    timer = setInterval(async () => {
      if (busy || signal.aborted || video.readyState < 2 || stream?.getVideoTracks()[0]?.muted) return
      busy = true
      try {
        const frame = await createImageBitmap(video)
        if (signal.aborted) { frame.close(); return }
        worker!.postMessage({ type: 'frame', frame, timestamp: performance.now() }, [frame])
      } catch { busy = false; stop(); failed() }
    }, 250)
  } catch (error) { stop(); throw error }
}

export async function startMicrophone(signal: AbortSignal, report: (speaking: boolean | null) => void, failed: () => void): Promise<void> {
  let stream: MediaStream | undefined
  let vad: import('@ricky0123/vad-web').MicVAD | undefined
  let poll: ReturnType<typeof setInterval> | undefined
  const stop = () => {
    if (stream) stopTracks(stream)
    clearInterval(poll)
    void vad?.destroy().catch(() => {})
    signal.removeEventListener('abort', stop)
  }
  signal.addEventListener('abort', stop, { once: true })
  try {
    stream = await openStream(signal, { audio: { channelCount: 1, echoCancellation: true, noiseSuppression: true }, video: false }, () => { stop(); failed() })
    stream.getTracks().forEach(track => {
      track.onmute = () => report(null)
    })
    const { MicVAD } = await import('@ricky0123/vad-web')
    signal.throwIfAborted()
    vad = await MicVAD.new({
      model: 'v5', startOnLoad: false,
      baseAssetPath: `${assets}vad/`, onnxWASMBasePath: `${assets}onnx/`,
      ortConfig: ort => { ort.env.wasm.numThreads = 1; ort.env.wasm.proxy = false },
      getStream: async () => { signal.throwIfAborted(); return stream! },
      resumeStream: async () => { signal.throwIfAborted(); return stream! },
      pauseStream: async value => stopTracks(value),
      onFrameProcessed: ({ isSpeech }) => {
        if (!signal.aborted) report(stream?.getAudioTracks()[0]?.muted ? null : isSpeech >= 0.6)
      },
      submitUserSpeechOnPause: false,
    })
    signal.throwIfAborted()
    await vad.start()
    signal.throwIfAborted()
    poll = setInterval(() => { if (vad?.errored) { stop(); failed() } }, 1000)
  } catch (error) { stop(); throw error }
}
