"""Writes the prompts GuideLLM sends when load testing the local model.

Not a test. Each line is the real free-text classifier prompt for one of the
forty hand-labelled answers in tests/eval, so the benchmark measures the
model on the work it does in a live class instead of on random text. No
model or database is needed. Run from backend/:

    python -m scripts.build_benchmark_prompts
    python -m scripts.build_benchmark_prompts --out benchmarks/prompts.jsonl

Then follow docs/local-model-benchmark.md.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from app.services.free_text_classifier import build_classifier_prompt
from scripts.evaluate_classifier import load_answers, load_questions

DEFAULT_OUT = Path(__file__).resolve().parent.parent / "benchmarks" / "prompts.jsonl"
# The classifier's reply is a short JSON object: one verdict and a quote per
# key point. Asking for this many keeps the load close to the real thing.
OUTPUT_TOKENS = 200


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    args = parser.parse_args()

    questions = load_questions()
    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open("w", encoding="utf-8") as f:
        for row in load_answers():
            prompt = build_classifier_prompt(questions[row["question_id"]], row["student_answer"])
            f.write(json.dumps({"prompt": prompt, "output_tokens_count": OUTPUT_TOKENS}) + "\n")
    print(f"wrote {sum(1 for _ in args.out.open())} prompts to {args.out}")


if __name__ == "__main__":
    main()
