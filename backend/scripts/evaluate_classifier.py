"""Measures the free-text classifier against the hand-labelled answer set.

Not a test. Needs Ollama running with the chat and embedding models from
.env, and is the accuracy baseline for #55. Run from backend/:

    python -m scripts.evaluate_classifier
    python -m scripts.evaluate_classifier --labels label_luna
    python -m scripts.evaluate_classifier --out tests/eval/results.csv
    python -m scripts.evaluate_classifier --questions tests/eval/fresh/questions.json \
        --answers tests/eval/fresh/answers_to_label.csv --agree label_a label_b \
        --out tests/eval/fresh/results_qwen3b_v6.csv

It compares against label_final by default: the label both labellers agreed
after settling where they differed. It prints each answer's human and
predicted label, then accuracy, macro F1, the confusion matrix and per-label
precision and recall. With both label columns filled it also prints how often
the two labellers agreed. The
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
    confidence_buckets,
    confusion_matrix,
    label_stats,
    macro_f1,
    threshold_cuts,
)
from app.services.embeddings import OllamaEmbeddingClient
from app.services.free_text_classifier import (
    PROMPT_VERSION,
    ClassificationError,
    FreeTextClassifier,
    FreeTextQuestion,
)

EVAL_DIR = Path(__file__).resolve().parent.parent / "tests" / "eval"
# The classifier's own floor, the review threshold the UI uses, and the level
# the report calls reliable (see tests/eval/THRESHOLDS.md).
REVIEW_THRESHOLDS = (0.35, 0.6, 0.85)
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


def load_questions(path: Path = EVAL_DIR / "questions.json") -> dict[str, FreeTextQuestion]:
    raw = json.loads(path.read_text(encoding="utf-8"))
    return {
        q["question_id"]: FreeTextQuestion(
            prompt=q["question_text"],
            reference_answer=q["reference_answer"],
            key_points=tuple(q["key_points"]),
        )
        for q in raw
    }


def load_answers(path: Path = EVAL_DIR / "answers_to_label.csv") -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8-sig") as f:
        return list(csv.DictReader(f))


def _fmt(value: float | None) -> str:
    return "  -  " if value is None else f"{value:.2f}"


async def main(args: argparse.Namespace) -> None:
    label_column, limit, out = args.labels, args.limit, args.out
    settings = get_settings()
    client = AsyncOpenAI(base_url=settings.ollama_base_url, api_key="ollama")
    classifier = FreeTextClassifier(
        client, OllamaEmbeddingClient(client, settings.embedding_model), settings.ollama_model
    )
    questions = load_questions(args.questions)
    answers = [a for a in load_answers(args.answers) if a.get(label_column, "").strip()]
    if not answers:
        raise SystemExit(f"No answers have a {label_column} label yet.")
    if limit:
        answers = answers[:limit]

    print(
        f"model {settings.ollama_model}, prompt {PROMPT_VERSION}, labels {label_column}, "
        f"answers {args.answers.name}\n"
    )
    rows = []
    for answer in answers:
        human = answer[label_column].strip().lower()
        try:
            result = await classifier.classify(
                questions[answer["question_id"]], answer["student_answer"]
            )
        except ClassificationError as exc:
            print(f"{answer['answer_id']}  human={human:<10}  UNREADABLE REPLY: {exc}")
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
            sims = [
                r["similarity"]
                for r in marked
                if r["human"] == label and r["similarity"] is not None
            ]
            if sims:
                print(
                    f"{label:<12} {min(sims):.3f} / {statistics.median(sims):.3f} / {max(sims):.3f}"
                )
        confidences = [float(r["confidence"]) for r in marked]
        correct = [r["human"] == r["predicted"] for r in marked]
        print("\nright at each confidence level")
        for b in confidence_buckets(confidences, correct):
            top = "1.00" if b.high is None else f"{b.high:.2f}"
            print(f"{b.low:.2f} to {top}  {b.right} of {b.answers} right")
        print("\nif labels below a threshold were shown as 'Uncertain, ask your lecturer'")
        for cut in threshold_cuts(confidences, correct, REVIEW_THRESHOLDS):
            print(
                f"below {cut.threshold:.2f}: {cut.flagged} hidden ({cut.flagged_wrong} of them "
                f"wrong), {cut.shown} shown ({cut.shown_wrong} of them wrong)"
            )

    first, second = args.agree
    both = [a for a in load_answers(args.answers) if a.get(first) and a.get(second)]
    if both:
        x = [a[first].strip().lower() for a in both]
        y = [a[second].strip().lower() for a in both]
        print(
            f"\nlabellers ({first}, {second}) agreed on {accuracy(x, y):.1%} of {len(both)} "
            f"answers, Cohen's kappa {cohen_kappa(x, y):.2f}"
        )

    if out:
        with out.open("w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=RESULT_FIELDS, restval="")
            writer.writeheader()
            writer.writerows(rows)
        print(f"\nwrote {out}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--labels", default="label_final", help="label column to compare against")
    parser.add_argument("--limit", type=int, help="mark only the first N answers")
    parser.add_argument("--out", type=Path, help="also write every result to this CSV")
    parser.add_argument("--questions", type=Path, default=EVAL_DIR / "questions.json")
    parser.add_argument("--answers", type=Path, default=EVAL_DIR / "answers_to_label.csv")
    parser.add_argument(
        "--agree",
        nargs=2,
        default=("label_luna", "label_nour"),
        metavar=("FIRST", "SECOND"),
        help="the two independent label columns to compare with each other",
    )
    asyncio.run(main(parser.parse_args()))
