"""Explicit administrator download of a pinned, MIT-licensed local speech model.

python scripts/prepare_live_speech.py --output /data/models/faster-whisper-base.en
Runtime inference uses only this directory and does not download or upload audio.
"""

import argparse

MODEL = "Systran/faster-whisper-base.en"
REVISION = "3d3d5dee26484f91867d81cb899cfcf72b96be6c"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    from huggingface_hub import snapshot_download

    snapshot_download(
        MODEL,
        revision=REVISION,
        local_dir=args.output,
        token=False,
        allow_patterns=["config.json", "model.bin", "tokenizer.json", "vocabulary.*"],
    )
    print(
        f"Prepared {MODEL} at revision {REVISION}. Set LIVE_TRANSCRIPTION_MODEL_PATH={args.output}"
    )


if __name__ == "__main__":
    main()
