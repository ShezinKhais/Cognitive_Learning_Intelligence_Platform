"""Check that the deployed, opted-in speech model loads locally without a microphone."""

from hashlib import file_digest
from importlib.metadata import version
from pathlib import Path

from app.core.config import get_settings
from app.services.local_speech import _model, configured


def main() -> None:
    settings = get_settings()
    if not configured(settings):
        raise SystemExit("Enable speech and prepare the complete local model in this image.")
    try:
        _model(settings.live_transcription_model_path, settings.live_transcription_cpu_threads)
        with (Path(settings.live_transcription_model_path) / "model.bin").open("rb") as model:
            digest = file_digest(model, "sha256").hexdigest()
    except Exception:
        raise SystemExit(
            "Local speech model could not load. Check the prepared files and CPU runtime."
        ) from None
    print(f"Loaded faster-whisper {version('faster-whisper')} locally; model SHA-256: {digest}")
    print(
        f"Language: {settings.live_transcription_language}; "
        f"CPU threads: {settings.live_transcription_cpu_threads}"
    )
    print("Model setup only. No audio, recognition quality or Teams delivery was tested.")


if __name__ == "__main__":
    main()
