# Anti-spoofing model (#165)

`minifasnet_v2_80x80.onnx` tells a live face from a photo or video of one. It
runs in the browser, in the camera's worker, on the face crop MediaPipe finds.

- **Source:** MiniFASNetV2 from Minivision's
  [Silent-Face-Anti-Spoofing](https://github.com/minivision-ai/Silent-Face-Anti-Spoofing),
  weights `resources/anti_spoof_models/2.7_80x80_MiniFASNetV2.pth`
  (SHA-256 `a5eb02e1…bec0`).
- **Licence:** Apache-2.0, copied in `LICENSE-MiniFASNet`. The weights are
  converted to ONNX, not changed.
- **Input:** `input`, 1 x 3 x 80 x 80, blue-green-red, values 0 to 255.
- **Output:** `probs`, 3 probabilities; index 1 is "live", 0 and 2 are spoofs.
- **Checksum:** SHA-256
  `9c6b11e41aa610366c9becdebaf93f10beaf53c1be34a613c32763707b9a6fe3`, checked
  by `scripts/prepare-attention.mjs` before it is copied into
  `public/attention/`, and by `tests/liveness.test.ts`.

## Rebuilding it

Not needed for the app or CI. To check or redo the conversion, with Python,
`torch`, `onnx` and `onnxruntime` installed:

    python convert_minifasnet.py

It downloads the weights, checks their SHA-256, loads them into a network
written out in the script (no downloaded code is run), exports ONNX and checks
it gives the same answers as PyTorch. The output checksum should match the one
above; if a different PyTorch version changes it, update both places.
