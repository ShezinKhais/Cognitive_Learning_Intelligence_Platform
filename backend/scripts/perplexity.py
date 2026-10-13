"""Perplexity of the sample lectures for the AI evaluation report (Phase 8,
AI 1, #73).

Not a test, and not part of the app. Needs Hugging Face transformers and
torch, which the backend does not install:

    pip install torch transformers accelerate

Run from backend/ (the first run downloads each model):

    python -m scripts.perplexity
    python -m scripts.perplexity --models Qwen/Qwen2.5-0.5B Qwen/Qwen2.5-1.5B Qwen/Qwen2.5-3B
    python -m scripts.perplexity --out tests/eval/PERPLEXITY.md
    python -m scripts.perplexity --models Qwen/Qwen2.5-0.5B-Instruct Qwen/Qwen2.5-1.5B-Instruct

The -Instruct models are the chat-tuned versions, the kind the app runs
through Ollama. The defaults are the 0.5B and 1.5B base models, which fit in 8 GB of memory.
The 3B needs about 6 GB on its own in bfloat16; try it only with little else
open. Each model reads every chunk of every sample lecture, the same chunks
the app embeds, plus two controls:

- everyday English: several paragraphs with no subject matter. A lecture
  scoring above it is harder text for the model than ordinary writing.
- lecture.pptx saved as a PDF (tests/eval/lecture_pptx_as_pdf.pdf, exported
  with LibreOffice): the same words as lecture.pptx in another format. The
  sample lectures cover different topics, so only this pair separates the
  effect of the file format from the effect of the topic.
"""

from __future__ import annotations

import argparse
import gc
import uuid
from pathlib import Path

from app.services.extraction import process_material
from app.services.perplexity import perplexity

BACKEND = Path(__file__).resolve().parent.parent
SAMPLES = BACKEND / "tests" / "samples"
SAME_AS_PPTX = BACKEND / "tests" / "eval" / "lecture_pptx_as_pdf.pdf"
# Ordinary English with no subject matter, written for this script so no
# model has seen it, scored paragraph by paragraph like a lecture's chunks.
EVERYDAY = [
    "The weather was warm, so we walked to the park after lunch. My sister "
    "brought a book and I bought two coffees from the small cafe on the corner. "
    "We sat on a bench near the pond and watched the ducks for an hour before "
    "heading home to make dinner.",
    "On Saturday morning the market was busier than usual. People queued for "
    "fresh bread, and a man at the fruit stall kept calling out the price of "
    "strawberries. I bought onions, a bag of rice and some flowers for the "
    "kitchen table, then took the bus back because my bags were too heavy.",
    "My neighbour has a small dog that barks whenever the postman arrives. "
    "Most days it stops after a minute, but on rainy days it keeps going until "
    "someone opens the door. The children on our street like to stop and pat "
    "it on their way to school.",
    "Last week I tried to fix the shelf in my room. I found the right screws "
    "in a drawer, but the drill battery was flat, so I had to wait for it to "
    "charge. By the evening the shelf was straight again and I could put my "
    "books and photos back on it.",
    "We visited my grandparents during the holiday. My grandmother cooked a "
    "large meal and refused to let anyone help in the kitchen. After dinner "
    "we played cards, drank tea and listened to my grandfather tell the same "
    "stories he tells every year.",
]


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

    def chunk_texts(path: Path) -> list[str]:
        return [c.chunk_text for c in process_material(str(path), uuid.uuid4()).chunks]

    texts = {"everyday English": EVERYDAY}
    for path in sorted(p for p in SAMPLES.iterdir() if p.is_file()):
        texts[path.name] = chunk_texts(path)
    texts["lecture.pptx as PDF"] = chunk_texts(SAME_AS_PPTX)

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
            "# Perplexity\n\nPerplexity of each sample lecture's chunks, pooled by token. "
            "Lower is more predictable to the model. Everyday English is the "
            "reference for ordinary writing; lecture.pptx as PDF has the same "
            "words as lecture.pptx, so the pair shows the effect of the file "
            "format alone.\n\n" + "\n".join(table) + "\n"
        )
        print(f"\nwritten to {args.out}")


if __name__ == "__main__":
    main()
