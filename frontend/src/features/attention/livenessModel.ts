// Runs the anti-spoofing model (#165) inside the face worker. Loaded only when
// LIVENESS is on or the recorder asks for live scores, so the classroom does
// not download it while the check is off. Same-origin assets only: the model
// and the ONNX runtime files are copied into public/attention/ at build time
// (scripts/prepare-attention.mjs), checksum pinned.
import { LIVE_CLASS, MODEL_SIZE, cropBox, faceBox, toModelInput } from './liveness'

type Ort = typeof import('ort-extern-wasm')

export interface LivenessModel {
  /** Live probability (0 to 1) of the face in `points`, and how long the check took. */
  check(frame: ImageBitmap, points: { x: number; y: number }[]): Promise<{ live: number; ms: number } | null>
}

export async function loadLivenessModel(base: string): Promise<LivenessModel> {
  const ort: Ort = await import('ort-extern-wasm')
  ort.env.wasm.wasmPaths = `${base}onnx/`
  // One thread: no cross-origin isolation is needed, and weak laptops keep a core free.
  ort.env.wasm.numThreads = 1
  ort.env.wasm.proxy = false
  const session = await ort.InferenceSession.create(`${base}minifasnet_v2_80x80.onnx`, { executionProviders: ['wasm'] })
  const canvas = new OffscreenCanvas(MODEL_SIZE, MODEL_SIZE)
  const context = canvas.getContext('2d', { willReadFrequently: true })
  if (!context) throw new Error('No 2D canvas in this worker')
  context.imageSmoothingQuality = 'medium'
  return {
    async check(frame, points) {
      const face = faceBox(points, frame.width, frame.height)
      if (!face) return null
      const started = performance.now()
      const crop = cropBox(face, frame.width, frame.height)
      context.drawImage(frame, crop.x, crop.y, crop.width, crop.height, 0, 0, MODEL_SIZE, MODEL_SIZE)
      const pixels = context.getImageData(0, 0, MODEL_SIZE, MODEL_SIZE).data
      const input = new ort.Tensor('float32', toModelInput(pixels), [1, 3, MODEL_SIZE, MODEL_SIZE])
      const output = await session.run({ input })
      const live = Number((output.probs.data as Float32Array)[LIVE_CLASS])
      return { live, ms: performance.now() - started }
    },
  }
}
