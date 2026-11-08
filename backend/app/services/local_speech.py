"""Bounded local ASR. Audio stays in RAM; inference never contacts a provider."""

from __future__ import annotations

import asyncio
import importlib.util
import io
import logging
import wave
from functools import lru_cache
from pathlib import Path

from app.core.config import Settings
from app.core.errors import ServiceUnavailableError, ValidationError

MAX_WAV_BYTES = 390_000
SAMPLE_RATE = 16_000


class SpeechUnavailable(ServiceUnavailableError):
    log_traceback = False


def configured(settings: Settings) -> bool:
    return bool(
        settings.live_transcription_enabled
        and settings.live_transcription_model_path
        and Path(settings.live_transcription_model_path).is_dir()
        and importlib.util.find_spec("faster_whisper") is not None
    )


def validate_wav(raw: bytes) -> float:
    if len(raw) > MAX_WAV_BYTES:
        raise ValidationError("Audio chunk exceeds the live transcription limit.")
    try:
        with wave.open(io.BytesIO(raw), "rb") as reader:
            if (
                reader.getnchannels() != 1
                or reader.getsampwidth() != 2
                or reader.getframerate() != SAMPLE_RATE
                or reader.getcomptype() != "NONE"
            ):
                raise ValueError("Expected mono 16 kHz 16-bit PCM")
            frames = reader.getnframes()
            if not SAMPLE_RATE <= frames <= 12 * SAMPLE_RATE:
                raise ValueError("Expected 1–12 seconds")
            if len(reader.readframes(frames)) != frames * 2:
                raise ValueError("Incomplete audio")
            return frames / SAMPLE_RATE
    except (wave.Error, EOFError, ValueError) as exc:
        raise ValidationError("Use a complete 1–12 second mono 16 kHz PCM WAV chunk.") from exc


@lru_cache(maxsize=1)
def _model(path: str, threads: int):
    import onnxruntime as ort

    ort.disable_telemetry_events()
    from faster_whisper import WhisperModel

    logging.getLogger("faster_whisper").setLevel(logging.WARNING)
    return WhisperModel(
        path, device="cpu", compute_type="int8", cpu_threads=threads, local_files_only=True
    )


def _recognize(raw: bytes, settings: Settings) -> str:
    import numpy as np

    with wave.open(io.BytesIO(raw), "rb") as reader:
        samples = np.frombuffer(reader.readframes(reader.getnframes()), dtype="<i2")
    audio = samples.astype(np.float32) / 32768.0
    segments, _ = _model(
        settings.live_transcription_model_path, settings.live_transcription_cpu_threads
    ).transcribe(
        audio,
        language=settings.live_transcription_language,
        beam_size=1,
        vad_filter=True,
        condition_on_previous_text=False,
        no_speech_threshold=0.6,
        hallucination_silence_threshold=1.0,
    )
    return " ".join(segment.text.strip() for segment in segments).strip()


class LocalSpeech:
    def __init__(self):
        self.running: asyncio.Task | None = None

    async def transcribe(self, raw: bytes, settings: Settings) -> str:
        if not configured(settings):
            raise SpeechUnavailable("Local speech transcription is not configured on this server.")
        if self.running is not None and not self.running.done():
            raise SpeechUnavailable(
                "The speech processor is busy. Live capture has stopped; try again."
            )
        task = asyncio.create_task(asyncio.to_thread(_recognize, raw, settings))
        self.running = task
        # A client cancellation cannot interrupt native inference. Keep the slot
        # until it really finishes; never spawn an unbounded series of threads.
        task.add_done_callback(lambda done: None if done.cancelled() else done.exception())
        try:
            return await asyncio.wait_for(asyncio.shield(task), timeout=25)
        except TimeoutError as exc:
            raise SpeechUnavailable(
                "Local speech processing timed out. Stop and try a faster model."
            ) from exc
        except Exception as exc:
            if isinstance(exc, SpeechUnavailable):
                raise
            raise SpeechUnavailable(
                "Local speech processing failed. Check the server's model setup."
            ) from exc


speech = LocalSpeech()
