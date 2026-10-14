// Build-time downloads only. All inference assets are served from our own origin.
import { mkdir, copyFile, readdir, readFile, writeFile } from 'node:fs/promises'
import { createHash } from 'node:crypto'
import { fileURLToPath } from 'node:url'
import path from 'node:path'

const root = fileURLToPath(new URL('../', import.meta.url))
const output = path.join(root, 'public/attention')
async function copyPackage(folder, destination, accept) {
  await mkdir(path.join(output, destination), { recursive: true })
  const source = path.join(root, 'node_modules', folder)
  for (const name of await readdir(source)) {
    if (accept(name)) await copyFile(path.join(source, name), path.join(output, destination, name))
  }
}
await copyPackage('@mediapipe/tasks-vision/wasm', 'vision', name => /\.(js|wasm)$/.test(name))
await copyPackage('@ricky0123/vad-web/dist', 'vad', name => ['silero_vad_v5.onnx', 'vad.worklet.bundle.min.js'].includes(name))
await copyPackage('onnxruntime-web/dist', 'onnx', name => /^ort-wasm-simd-threaded\.(wasm|mjs)$/.test(name))
const target = path.join(output, 'face_landmarker.task')
const expected = '64184e229b263107bc2b804c6625db1341ff2bb731874b0bcc2fe6544e0bc9ff'
const valid = data => createHash('sha256').update(data).digest('hex') === expected
let existing
try { existing = await readFile(target) } catch (error) { if (error.code !== 'ENOENT') throw error }
if (!existing || !valid(existing)) {
  const response = await fetch('https://storage.googleapis.com/mediapipe-models/face_landmarker/face_landmarker/float16/1/face_landmarker.task', { signal: AbortSignal.timeout(60000) })
  if (!response.ok) throw new Error(`Face model download failed: ${response.status}`)
  const data = Buffer.from(await response.arrayBuffer())
  if (!valid(data)) throw new Error('Face model checksum mismatch')
  await writeFile(target, data)
}
console.log('Local attention assets ready (pinned face model checksum verified).')
