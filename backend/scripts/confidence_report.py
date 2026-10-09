"""Checks whether the classifier's confidence tells its right labels from its
wrong ones, using a results file the evaluation already wrote.

Not a test, and needs no model: run evaluate_classifier with --out first,
then from backend/:

    python -m scripts.confidence_report tests/eval/results.csv

Confidence is worth showing a lecturer only if a confident label is right
more often than an unsure one.
"""

from __future__ import annotations

import argparse
import csv
import statistics
from pathlib import Path

from app.services.classifier_evaluation import (
    LABELS,
    confidence_buckets,
    confidence_separation,
)


def _mean(values: list[float]) -> str:
    return f"{statistics.mean(values):.2f}" if values else "  -  "


def main(results: Path) -> None:
    with results.open(newline="", encoding="utf-8") as f:
        # An unreadable reply has no label or confidence to check.
        rows = [row for row in csv.DictReader(f) if row["predicted"] != "error"]
    confidences = [float(row["confidence"]) for row in rows]
    correct = [row["human"] == row["predicted"] for row in rows]

    print(f"{len(rows)} labels, {sum(correct)} right\n")
    print("confidence    answers  right  accuracy")
    for bucket in confidence_buckets(confidences, correct):
        top = "+" if bucket.high is None else f"-{bucket.high:.2f}"
        span = f"{bucket.low:.2f}{top}"
        accuracy = "  -" if bucket.accuracy is None else f"{bucket.accuracy:.0%}"
        print(f"{span:<12}  {bucket.answers:>7}  {bucket.right:>5}  {accuracy:>8}")

    separation = confidence_separation(confidences, correct)
    print(
        "\nseparation (AUROC, 0.5 is a coin flip, 1 is perfect): "
        + ("  -" if separation is None else f"{separation:.2f}")
    )

    # Each label's confidence has its own range, so it can rank right above
    # wrong within a label even where the overall separation is weak.
    print("\nby predicted label: mean confidence and separation within the label")
    print("label         labels  right   wrong   separation")
    for label in LABELS:
        mine = [
            (c, ok)
            for c, ok, row in zip(confidences, correct, rows, strict=True)
            if row["predicted"] == label
        ]
        within = confidence_separation([c for c, _ in mine], [ok for _, ok in mine])
        print(
            f"{label:<12}  {len(mine):>6}  {_mean([c for c, ok in mine if ok]):>5}   "
            f"{_mean([c for c, ok in mine if not ok]):>5}   "
            + ("  -" if within is None else f"{within:.2f}")
        )

    print("\nmost confident wrong labels")
    wrong = sorted(
        (row for row, ok in zip(rows, correct, strict=True) if not ok),
        key=lambda row: -float(row["confidence"]),
    )
    for row in wrong[:5]:
        print(
            f"{row['answer_id']}  human={row['human']:<10} predicted={row['predicted']:<10} "
            f"conf={float(row['confidence']):.2f}"
        )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("results", type=Path, help="a CSV written by evaluate_classifier --out")
    main(parser.parse_args().results)
