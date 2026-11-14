"""Rebuild minifasnet_v2_80x80.onnx from Minivision's published weights (#165).

Not run by the app or CI: the converted model is committed next to this file
so the browser build needs no Python. Run it only to check or redo the
conversion. Needs torch, onnx and onnxruntime:

    python convert_minifasnet.py

Source: https://github.com/minivision-ai/Silent-Face-Anti-Spoofing (Apache-2.0),
weights resources/anti_spoof_models/2.7_80x80_MiniFASNetV2.pth.
"""

import hashlib
import sys
import urllib.request
from pathlib import Path

import numpy as np
import onnx
import onnxruntime
import torch

HERE = Path(__file__).parent
BASE = "https://raw.githubusercontent.com/minivision-ai/Silent-Face-Anti-Spoofing/master/"
WEIGHTS = ("resources/anti_spoof_models/2.7_80x80_MiniFASNetV2.pth",
           "a5eb02e1843f19b5386b953cc4c9f011c3f985d0ee2bb9819eea9a142099bec0")
OUTPUT = HERE / "minifasnet_v2_80x80.onnx"


# -- MiniFASNetV2, transcribed from src/model_lib/MiniFASNet.py (Apache-2.0) ----
# Same layer names as the original, so its weights load without renaming.
# Only the parts MiniFASNetV2 at 80x80 uses; nothing downloaded is executed.
nn = torch.nn
KEEP = [32, 32, 103, 103, 64, 13, 13, 64, 13, 13, 64, 13, 13, 64, 13, 13, 64, 231, 231, 128,
        231, 231, 128, 52, 52, 128, 26, 26, 128, 77, 77, 128, 26, 26, 128, 26, 26, 128, 308, 308,
        128, 26, 26, 128, 26, 26, 128, 512, 512]


class ConvBlock(nn.Module):  # conv, batch norm, PReLU
    def __init__(self, i, o, kernel=1, stride=1, padding=0, groups=1, act=True):
        super().__init__()
        self.conv = nn.Conv2d(i, o, kernel, stride, padding, groups=groups, bias=False)
        self.bn = nn.BatchNorm2d(o)
        if act:
            self.prelu = nn.PReLU(o)

    def forward(self, x):
        x = self.bn(self.conv(x))
        return self.prelu(x) if hasattr(self, "prelu") else x


class DepthWise(nn.Module):  # 1x1 expand, 3x3 depthwise, 1x1 project, optional shortcut
    def __init__(self, c1, c2, c3, residual=False, stride=2):
        super().__init__()
        self.conv = ConvBlock(c1[0], c1[1])
        self.conv_dw = ConvBlock(c2[0], c2[1], 3, stride, 1, groups=c2[0])
        self.project = ConvBlock(c3[0], c3[1], act=False)
        self.residual = residual

    def forward(self, x):
        y = self.project(self.conv_dw(self.conv(x)))
        return x + y if self.residual else y


class Residual(nn.Module):
    def __init__(self, start, blocks):
        super().__init__()
        k = KEEP
        self.model = nn.Sequential(*[
            DepthWise((k[s], k[s + 1]), (k[s + 1], k[s + 2]), (k[s + 2], k[s + 3]), residual=True, stride=1)
            for s in range(start, start + 3 * blocks, 3)
        ])

    def forward(self, x):
        return self.model(x)


class MiniFASNetV2(nn.Module):
    def __init__(self, embedding=128, classes=3):
        super().__init__()
        k = KEEP
        self.conv1 = ConvBlock(3, k[0], 3, 2, 1)
        self.conv2_dw = ConvBlock(k[0], k[1], 3, 1, 1, groups=k[1])
        self.conv_23 = DepthWise((k[1], k[2]), (k[2], k[3]), (k[3], k[4]))
        self.conv_3 = Residual(4, 4)
        self.conv_34 = DepthWise((k[16], k[17]), (k[17], k[18]), (k[18], k[19]))
        self.conv_4 = Residual(19, 6)
        self.conv_45 = DepthWise((k[37], k[38]), (k[38], k[39]), (k[39], k[40]))
        self.conv_5 = Residual(40, 2)
        self.conv_6_sep = ConvBlock(k[46], k[47])
        # 80x80 input: the last kernel is ((80 + 15) // 16,) * 2 = (5, 5).
        self.conv_6_dw = ConvBlock(k[47], k[48], 5, groups=k[48], act=False)
        self.linear = nn.Linear(512, embedding, bias=False)
        self.bn = nn.BatchNorm1d(embedding)
        self.prob = nn.Linear(embedding, classes, bias=False)

    def forward(self, x):
        for layer in (self.conv1, self.conv2_dw, self.conv_23, self.conv_3, self.conv_34,
                      self.conv_4, self.conv_45, self.conv_5, self.conv_6_sep, self.conv_6_dw):
            x = layer(x)
        return self.prob(self.bn(self.linear(x.flatten(1))))


def fetch(path: str) -> bytes:
    with urllib.request.urlopen(BASE + path, timeout=60) as response:
        return response.read()


def main() -> None:
    weights = fetch(WEIGHTS[0])
    if hashlib.sha256(weights).hexdigest() != WEIGHTS[1]:
        sys.exit("weights checksum mismatch")
    model = MiniFASNetV2()
    # weights_only: tensors only, no code runs while loading.
    state = torch.load(_tmp(weights), map_location="cpu", weights_only=True)
    state = {k.removeprefix("module."): v for k, v in state.items()}
    model.load_state_dict(state)
    model.eval()

    # Input: 1 x 3 x 80 x 80, BGR, 0-255 (not divided), as in the original.
    # Output: softmax over 3 classes; index 1 is "live" (test.py in the source repo), 0 and 2 are spoofs.
    class WithSoftmax(torch.nn.Module):
        def __init__(self, net):
            super().__init__()
            self.net = net

        def forward(self, x):
            return torch.softmax(self.net(x), dim=1)

    wrapped = WithSoftmax(model).eval()
    example = torch.rand(1, 3, 80, 80) * 255
    torch.onnx.export(wrapped, example, OUTPUT, input_names=["input"], output_names=["probs"],
                      opset_version=17, dynamo=False)
    onnx.checker.check_model(onnx.load(OUTPUT))

    # The ONNX file must give the same answers as PyTorch.
    session = onnxruntime.InferenceSession(str(OUTPUT))
    for _ in range(5):
        x = torch.rand(1, 3, 80, 80) * 255
        expected = wrapped(x).detach().numpy()
        got = session.run(None, {"input": x.numpy()})[0]
        assert np.allclose(expected, got, atol=1e-4), (expected, got)
    print(OUTPUT.name, hashlib.sha256(OUTPUT.read_bytes()).hexdigest())


def _tmp(data: bytes) -> Path:
    path = HERE / ".weights.pth"
    path.write_bytes(data)
    return path


if __name__ == "__main__":
    try:
        main()
    finally:
        (HERE / ".weights.pth").unlink(missing_ok=True)
