import { fileURLToPath } from 'node:url'

// #165: the anti-spoofing model runs on the ONNX runtime build that loads its
// engine from public/attention/onnx/ (the copy the microphone already uses),
// instead of the default build, which makes Vite add a second 14 MB copy.
// Only livenessModel.ts imports this name; the microphone's imports are untouched.
export const ortExternAlias = {
  'ort-extern-wasm': fileURLToPath(new URL('./node_modules/onnxruntime-web/dist/ort.wasm.min.mjs', import.meta.url)),
}
