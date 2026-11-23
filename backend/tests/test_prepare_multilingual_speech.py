"""Verify pinned model selection without downloading model files."""

import sys
from types import SimpleNamespace

import pytest

from scripts import prepare_live_speech


@pytest.mark.parametrize(
    ("choice", "model"),
    [
        ("english", "Systran/faster-whisper-base.en"),
        ("multilingual", "Systran/faster-whisper-base"),
    ],
)
def test_preparation_downloads_selected_pinned_model(
    monkeypatch, tmp_path, choice, model
):
    calls = []

    def fake_download(*args, **kwargs):
        calls.append((args, kwargs))

    monkeypatch.setitem(
        sys.modules,
        "huggingface_hub",
        SimpleNamespace(snapshot_download=fake_download),
    )
    monkeypatch.setattr(
        sys,
        "argv",
        ["prepare_live_speech.py", "--output", str(tmp_path), "--model", choice],
    )

    prepare_live_speech.main()

    assert len(calls) == 1
    args, kwargs = calls[0]
    assert args == (model,)
    assert kwargs["revision"] == prepare_live_speech.MODELS[choice][1]
    assert len(kwargs["revision"]) == 40
    assert kwargs["local_dir"] == str(tmp_path)
    assert kwargs["token"] is False


def test_default_remains_english(monkeypatch, tmp_path):
    calls = []

    monkeypatch.setitem(
        sys.modules,
        "huggingface_hub",
        SimpleNamespace(snapshot_download=lambda *a, **k: calls.append(a)),
    )
    monkeypatch.setattr(
        sys, "argv", ["prepare_live_speech.py", "--output", str(tmp_path)]
    )

    prepare_live_speech.main()

    assert calls == [("Systran/faster-whisper-base.en",)]
