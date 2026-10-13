"""Calibration and consistency of the free-text classifier, for the AI
evaluation report (Phase 8, AI 1, #73).

Not a test, and needs no model: it reads the results files evaluate_classifier
already wrote. Run from backend/:

    python -m scripts.calibration_consistency
    python -m scripts.calibration_consistency --out tests/eval/CALIBRATION.md

Calibration: when the classifier says it is 90% sure, is it right about 90%
of the time? Measured by expected calibration error (ECE) and the Brier
score, both 0 when perfect, and by AUROC: how well confidence ranks right
labels above wrong ones (1 perfect, 0.5 a coin toss).

Consistency: two runs of the same model and prompt on the same answers, and
how often they give the same label (Cohen's kappa between the runs).
"""

from __future__ import annotations

import argparse
import csv
from pathlib import Path

from app.services.classifier_evaluation import (
    LABELS,
    brier_score,
    cohen_kappa,
    confidence_buckets,
    confidence_separation,
    expected_calibration_error,
)

EVAL_DIR = Path(__file__).resolve().parent.parent / "tests" / "eval"
RUNS = {
    "results_qwen3b_run2.csv": "qwen2.5:3b v3 run 2",
    "results_qwen7b.csv": "qwen2.5:7b v3 run 1",
    "results_qwen7b_run2.csv": "qwen2.5:7b v3 run 2",
    "results_qwen3b_v4.csv": "qwen2.5:3b v4",
}
# Runs of the same model and prompt, to compare with each other.
REPEATS = [("results_qwen7b.csv", "results_qwen7b_run2.csv")]


def read(path: Path) -> dict[str, dict[str, str]]:
    with path.open(newline="", encoding="utf-8-sig") as f:
        return {row["answer_id"]: row for row in csv.DictReader(f)}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--out", type=Path, help="also write the results to this Markdown file")
    args = parser.parse_args()

    calibration = [
        "| Run | Labels | Mean confidence | Accuracy | ECE | Brier | AUROC |",
        "|---|---|---|---|---|---|---|",
    ]
    buckets = [
        "| Run | Below 0.6 | 0.6 to 0.85 | 0.85 and up |",
        "|---|---|---|---|",
    ]
    for file, name in RUNS.items():
        path = EVAL_DIR / file
        if not path.exists():
            continue
        rows = [r for r in read(path).values() if r["predicted"] in LABELS]
        confidences = [float(r["confidence"]) for r in rows]
        correct = [r["human"] == r["predicted"] for r in rows]
        auroc = confidence_separation(confidences, correct)
        calibration.append(
            f"| {name} | {len(rows)} | {sum(confidences) / len(rows):.2f} | "
            f"{sum(correct) / len(rows):.0%} | "
            f"{expected_calibration_error(confidences, correct):.2f} | "
            f"{brier_score(confidences, correct):.2f} | "
            f"{'-' if auroc is None else f'{auroc:.2f}'} |"
        )
        cells = [
            f"{b.right} of {b.answers} right" if b.answers else "none"
            for b in confidence_buckets(confidences, correct)
        ]
        buckets.append(f"| {name} | " + " | ".join(cells) + " |")

    consistency = [
        "| Runs compared | Answers both read | Same label | Cohen's kappa |",
        "|---|---|---|---|",
    ]
    for first, second in REPEATS:
        a, b = read(EVAL_DIR / first), read(EVAL_DIR / second)
        shared = [
            i for i in a if i in b and a[i]["predicted"] in LABELS and b[i]["predicted"] in LABELS
        ]
        x = [a[i]["predicted"] for i in shared]
        y = [b[i]["predicted"] for i in shared]
        same = sum(p == q for p, q in zip(x, y, strict=True))
        consistency.append(
            f"| {RUNS[first]} vs {RUNS[second]} | {len(shared)} | "
            f"{same} ({same / len(shared):.0%}) | {cohen_kappa(x, y):.2f} |"
        )

    report = "\n".join(
        [
            "## Calibration",
            "",
            *calibration,
            "",
            "How often labels were right at each confidence level:",
            "",
            *buckets,
            "",
            "## Consistency",
            "",
            *consistency,
        ]
    )
    print(report)
    if args.out:
        args.out.write_text(
            "# Calibration and consistency\n\n"
            "Read from the classifier results in this folder; unreadable replies are "
            "left out. ECE (expected calibration error, 10 bins) and the Brier score "
            "are 0 when confidence is perfectly honest; AUROC is the chance a right "
            "label has higher confidence than a wrong one (1 perfect, 0.5 a coin "
            "toss).\n\n" + report + "\n"
        )
        print(f"\nwritten to {args.out}")


if __name__ == "__main__":
    main()
