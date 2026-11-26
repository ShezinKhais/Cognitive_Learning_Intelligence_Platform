"""Explicit administrator download of a pinned, MIT-licensed local speech model.

python scripts/prepare_live_speech.py --output /data/models/faster-whisper-base.en
Runtime inference uses only this directory and does not download or upload audio.
"""

import argparse

MODELS = {
    "english": (
        "Systran/faster-whisper-base.en",
        "3d3d5dee26484f91867d81cb899cfcf72b96be6c",
    ),
    "multilingual": (
        "Systran/faster-whisper-base",
        "ebe41f70d5b6dfa9166e2c581c45c9c0cfc57b66",
    ),
}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True)
    parser.add_argument(
        "--model",
        choices=tuple(MODELS),
        default="english",
        help="Default: english. Use multilingual for auto language detection.",
    )
    args = parser.parse_args()
    from huggingface_hub import snapshot_download

    model, revision = MODELS[args.model]
    snapshot_download(
        model,
        revision=revision,
        local_dir=args.output,
        token=False,
        allow_patterns=["config.json", "model.bin", "tokenizer.json", "vocabulary.*"],
    )
    print(
        f"Prepared {model} at revision {revision}. Set LIVE_TRANSCRIPTION_MODEL_PATH={args.output}"
    )


if __name__ == "__main__":
    main()
