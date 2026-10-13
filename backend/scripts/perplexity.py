"""Perplexity of the sample lectures for the AI evaluation report (Phase 8,
AI 1, #73).

Not a test, and not part of the app. Needs Hugging Face transformers and
torch, which the backend does not install:

    pip install torch transformers accelerate

Run from backend/ (the first run downloads each model):

    python -m scripts.perplexity
    python -m scripts.perplexity --models Qwen/Qwen2.5-0.5B Qwen/Qwen2.5-1.5B Qwen/Qwen2.5-3B
    python -m scripts.perplexity --out tests/eval/PERPLEXITY.md

The defaults are the 0.5B and 1.5B base models, which fit in 8 GB of memory.
The 3B needs about 6 GB on its own in bfloat16; try it only with little else
open. Each model reads every chunk of every sample lecture, the same chunks
the app embeds, plus a short passage of everyday English as a reference.
"""

from __future__ import annotations

import argparse
import gc
import uuid
from pathlib import Path

from app.services.extraction import process_material
from app.services.perplexity import perplexity

SAMPLES = Path(__file__).resolve().parent.parent / "tests" / "samples"
# Ordinary English with no subject matter, so a lecture's perplexity can be
# read against it: higher than this means the lecture is harder text for the
# model than everyday writing.
EVERYDAY = (
    "The weather was warm, so we walked to the park after lunch. My sister "
    "brought a book and I bought two coffees from the small cafe on the corner. "
    "We sat on a bench near the pond and watched the ducks for an hour before "
    "heading home to make dinner."
)


def score_text(model, tokenizer, text: str) -> tuple[float, int]:
    """(summed negative log-likelihood, tokens predicted) for one text."""
    import torch

    ids = tokenizer(text, return_tensors="pt").input_ids
    if ids.shape[1] < 2:
        return 0.0, 0
    with torch.no_grad():
        loss = model(ids, labels=ids).loss.item()
    # The loss is a mean over the tokens predicted: every one but the first.
    predicted = ids.shape[1] - 1
    return loss * predicted, predicted


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--models", nargs="+", default=["Qwen/Qwen2.5-0.5B", "Qwen/Qwen2.5-1.5B"])
    parser.add_argument("--out", type=Path, help="also write the table to this Markdown file")
    args = parser.parse_args()

    import torch
    from transformers import AutoModelForCausalLM, AutoTokenizer

    texts = {"everyday English": [EVERYDAY]}
    for path in sorted(p for p in SAMPLES.iterdir() if p.is_file()):
        chunks = process_material(str(path), uuid.uuid4()).chunks
        texts[path.name] = [c.chunk_text for c in chunks]

    rows = []
    for name in args.models:
        print(f"loading {name}")
        tokenizer = AutoTokenizer.from_pretrained(name)
        model = AutoModelForCausalLM.from_pretrained(
            name, torch_dtype=torch.bfloat16, low_cpu_mem_usage=True
        )
        model.eval()
        for label, items in texts.items():
            value = perplexity(score_text(model, tokenizer, t) for t in items)
            print(f"  {label:<18} {value:8.2f}")
            rows.append((name, label, value))
        del model
        gc.collect()

    labels = list(texts)
    table = [
        "| Model | " + " | ".join(labels) + " |",
        "|---|" + "---|" * len(labels),
    ]
    for name in args.models:
        cells = [f"{v:.2f}" for m, label, v in rows if m == name]
        table.append(f"| {name} | " + " | ".join(cells) + " |")
    print("\n" + "\n".join(table))
    if args.out:
        args.out.write_text(
            "# Perplexity\n\nPerplexity of each sample lecture's chunks, pooled by token, "
            "and of a passage of everyday English for reference. Lower is more "
            "predictable to the model.\n\n" + "\n".join(table) + "\n"
        )
        print(f"\nwritten to {args.out}")


if __name__ == "__main__":
    main()
