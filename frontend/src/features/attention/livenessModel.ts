// Runs the anti-spoofing model (#165) inside the face worker. The worker calls
// loadLivenessModel only while LIVENESS is on or the recorder asks for live
// scores, so the model and the ONNX engine (.wasm, about 12 MB) are not
// downloaded while the check is off. The worker is built as one file (IIFE),
// so the onnxruntime JavaScript itself (about 50 KB) is part of face.worker's
// download either way. Same-origin assets only: the model and the engine are
// copied into public/attention/ at build time (scripts/prepare-attention.mjs),
// checksum pinned.
import { LIVE_CLASS, MODEL_INPUT, MODEL_SIZE, cropBox, faceBox } from './liveness'

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
  return {
    async check(frame, points) {
      const face = faceBox(points, frame.width, frame.height)
      if (!face) return null
      const started = performance.now()
      const crop = cropBox(face, frame.width, frame.height)
      // The crop, resized, as a new bitmap; ONNX Runtime turns it into the
      // model's input itself. No pixels are handled here or kept.
      const face80 = await createImageBitmap(frame, crop.x, crop.y, crop.width, crop.height, {
        resizeWidth: MODEL_SIZE, resizeHeight: MODEL_SIZE, resizeQuality: 'medium',
      })
      let output
      try {
        const input = await ort.Tensor.fromImage(face80, MODEL_INPUT)
        output = await session.run({ input })
      } finally {
        face80.close()
      }
      const live = Number((output.probs.data as Float32Array)[LIVE_CLASS])
      return { live, ms: performance.now() - started }
    },
  }
}
