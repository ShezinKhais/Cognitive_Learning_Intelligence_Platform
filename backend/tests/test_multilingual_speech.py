"""Multilingual language selection for the local Whisper recognizer."""

from types import SimpleNamespace

import pytest

from app.core.config import Settings
from app.services import local_speech

from .test_live_transcription import wav


@pytest.mark.parametrize(
    ("configured_language", "expected_language"),
    [
        ("auto", None),
        ("en", "en"),
        ("ar", "ar"),
        ("fr", "fr"),
    ],
)
def test_whisper_receives_expected_language(
    monkeypatch, configured_language, expected_language
):
    requests = []

    class FakeWhisper:
        def transcribe(self, audio, **kwargs):
            requests.append(kwargs)
            return [SimpleNamespace(text="Recognized speech")], SimpleNamespace()

    monkeypatch.setattr(local_speech, "_model", lambda *_: FakeWhisper())

    settings = SimpleNamespace(
        live_transcription_model_path="test-model",
        live_transcription_cpu_threads=2,
        live_transcription_language=configured_language,
    )

    assert local_speech._recognize(wav(seconds=1), settings) == "Recognized speech"
    assert len(requests) == 1
    assert requests[0]["language"] == expected_language
    assert requests[0]["condition_on_previous_text"] is False


def test_configuration_accepts_autodetection():
    settings = Settings(live_transcription_language="auto")
    assert settings.live_transcription_language == "auto"


def test_configuration_rejects_invalid_language():
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        Settings(live_transcription_language="english")
