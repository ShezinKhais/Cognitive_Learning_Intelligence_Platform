"""Measures the free-text classifier against the hand-labelled answer set.

Not a test. Needs Ollama running with the chat and embedding models from
.env, and is the accuracy baseline for #55. Run from backend/:

    python -m scripts.evaluate_classifier
    python -m scripts.evaluate_classifier --labels label_nour
    python -m scripts.evaluate_classifier --out tests/eval/results.csv

It prints each answer's human and predicted label, then accuracy, macro F1,
the confusion matrix and per-label precision and recall. With both label
columns filled it also prints how often the two labellers agreed. The
similarity range per human label is printed so SIMILARITY_FLOOR and
SIMILARITY_CEILING can be set from data.
"""

from __future__ import annotations

import argparse
import asyncio
import csv
import json
import statistics
from pathlib import Path

from openai import AsyncOpenAI

from app.core.config import get_settings
from app.services.classifier_evaluation import (
    LABELS,
    accuracy,
    cohen_kappa,
    confusion_matrix,
    label_stats,
    macro_f1,
)
from app.services.embeddings import OllamaEmbeddingClient
from app.services.free_text_classifier import (
    PROMPT_VERSION,
    ClassificationError,
    FreeTextClassifier,
    FreeTextQuestion,
)

EVAL_DIR = Path(__file__).resolve().parent.parent / "tests" / "eval"
RESULT_FIELDS = (
    "answer_id",
    "human",
    "predicted",
    "confidence",
    "score",
    "similarity",
    "coverage",
    "evidence",
    "wrong_claim",
    "reasons",
    "model",
    "prompt_version",
)


def load_questions() -> dict[str, FreeTextQuestion]:
    raw = json.loads((EVAL_DIR / "questions.json").read_text(encoding="utf-8"))
    return {
        q["question_id"]: FreeTextQuestion(
            prompt=q["question_text"],
            reference_answer=q["reference_answer"],
            key_points=tuple(q["key_points"]),
        )
        for q in raw
    }


def load_answers() -> list[dict[str, str]]:
    with (EVAL_DIR / "answers_to_label.csv").open(newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def _fmt(value: float | None) -> str:
    return "  -  " if value is None else f"{value:.2f}"


async def main(label_column: str, limit: int | None, out: Path | None) -> None:
    settings = get_settings()
    client = AsyncOpenAI(base_url=settings.ollama_base_url, api_key="ollama")
    classifier = FreeTextClassifier(
        client, OllamaEmbeddingClient(client, settings.embedding_model), settings.ollama_model
    )
    questions = load_questions()
    answers = [a for a in load_answers() if a.get(label_column, "").strip()]
    if not answers:
        raise SystemExit(f"No answers have a {label_column} label yet.")
    if limit:
        answers = answers[:limit]

    print(f"model {settings.ollama_model}, prompt {PROMPT_VERSION}, labels {label_column}\n")
    rows = []
    for answer in answers:
        human = answer[label_column].strip().lower()
        try:
            result = await classifier.classify(
                questions[answer["question_id"]], answer["student_answer"]
            )
        except ClassificationError as exc:
            print(
                f"{answer['answer_id']}  human={human:<10}  UNREADABLE REPLY: {exc}: "
                f"{exc.reply[:200]!r}"
            )
            rows.append({"answer_id": answer["answer_id"], "human": human, "predicted": "error"})
            continue
        predicted = result.label.value
        mark = "  " if predicted == human else "XX"
        print(
            f"{mark} {answer['answer_id']}  human={human:<10} predicted={predicted:<10} "
            f"conf={result.confidence:.2f} sim={_fmt(result.similarity)} "
            f"points={[c.value for c in result.coverage]}"
        )
        rows.append(
            {
                "answer_id": answer["answer_id"],
                "human": human,
                "predicted": predicted,
                "confidence": result.confidence,
                "score": result.score,
                "similarity": result.similarity,
                "coverage": " ".join(c.value for c in result.coverage),
                "evidence": " | ".join(result.evidence),
                "wrong_claim": result.wrong_claim or "",
                "reasons": " | ".join(result.reasons),
                "model": result.model or "",
                "prompt_version": result.prompt_version,
            }
        )

    marked = [r for r in rows if r["predicted"] != "error"]
    errors = len(rows) - len(marked)
    expected = [r["human"] for r in marked]
    predicted = [r["predicted"] for r in marked]
    print(f"\n{len(marked)} marked, {errors} unreadable replies")
    if marked:
        print(f"accuracy  {accuracy(expected, predicted):.1%}")
        print(f"macro F1  {macro_f1(expected, predicted):.2f}")
        print("\nconfusion (rows: human, columns: predicted)")
        print(" " * 12 + "".join(f"{label:>12}" for label in LABELS))
        for human_label, row in confusion_matrix(expected, predicted).items():
            print(f"{human_label:<12}" + "".join(f"{row[p]:>12}" for p in LABELS))
        print("\nlabel        precision  recall  f1    support")
        for s in label_stats(expected, predicted):
            print(
                f"{s.label:<12} {_fmt(s.precision):>9}  {_fmt(s.recall):>6}  "
                f"{_fmt(s.f1):>4}  {s.support:>7}"
            )
        print("\nsimilarity by human label (min / median / max)")
        for label in LABELS:
            sims = [r["similarity"] for r in marked if r["human"] == label and r["similarity"]]
            if sims:
                print(
                    f"{label:<12} {min(sims):.3f} / {statistics.median(sims):.3f} / {max(sims):.3f}"
                )

    both = [a for a in load_answers() if a.get("label_luna") and a.get("label_nour")]
    if both:
        luna = [a["label_luna"].strip().lower() for a in both]
        nour = [a["label_nour"].strip().lower() for a in both]
        print(
            f"\nlabellers agreed on {accuracy(luna, nour):.1%} of {len(both)} answers, "
            f"Cohen's kappa {cohen_kappa(luna, nour):.2f}"
        )

    if out:
        with out.open("w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=RESULT_FIELDS, restval="")
            writer.writeheader()
            writer.writerows(rows)
        print(f"\nwrote {out}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--labels", default="label_luna", help="label column to compare against")
    parser.add_argument("--limit", type=int, help="mark only the first N answers")
    parser.add_argument("--out", type=Path, help="also write every result to this CSV")
    args = parser.parse_args()
    asyncio.run(main(args.labels, args.limit, args.out))
