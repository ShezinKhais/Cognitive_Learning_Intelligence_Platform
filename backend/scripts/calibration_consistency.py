"""Calibration and consistency of the free-text classifier, for the AI
evaluation report (Phase 8, AI 1, #73).

Not a test, and needs no model: it reads the results files evaluate_classifier
already wrote. Run from backend/:

    python -m scripts.calibration_consistency
    python -m scripts.calibration_consistency --out tests/eval/CALIBRATION.md
    python -m scripts.calibration_consistency \
        --run tests/eval/results_qwen3b_v6.csv "qwen2.5:3b v6 run 1" \
        --run tests/eval/results_qwen3b_v6_run2.csv "qwen2.5:3b v6 run 2" \
        --repeat tests/eval/results_qwen3b_v6.csv tests/eval/results_qwen3b_v6_run2.csv

With --run, only the runs named are read (a file and a name for it); without
it, the older runs listed in RUNS below.

Calibration: when the classifier says it is 90% sure, is it right about 90%
of the time? Measured by expected calibration error (ECE) and the Brier
score, both 0 when perfect, and by AUROC: how well confidence ranks right
labels above wrong ones (1 perfect, 0.5 a coin toss).

Consistency: two runs of the same model and prompt on the same answers, and
how often they give the same label (Cohen's kappa between the runs).

Thresholds: for 0.35, 0.6 and 0.85, how many labels would be hidden as
"Uncertain, ask your lecturer" and how many wrong labels would still be shown.
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
    threshold_cuts,
)
from scripts.evaluate_classifier import REVIEW_THRESHOLDS

EVAL_DIR = Path(__file__).resolve().parent.parent / "tests" / "eval"
RUNS = {
    "results_qwen3b_run2.csv": "qwen2.5:3b v3 run 2",
    "results_qwen7b.csv": "qwen2.5:7b v3 run 1",
    "results_qwen7b_run2.csv": "qwen2.5:7b v3 run 2",
    "results_qwen3b_v4.csv": "qwen2.5:3b v4",
    "results_qwen3b_v5.csv": "qwen2.5:3b v5",
}
# Runs of the same model and prompt, to compare with each other.
REPEATS = [("results_qwen7b.csv", "results_qwen7b_run2.csv")]


def read(path: Path) -> dict[str, dict[str, str]]:
    with path.open(newline="", encoding="utf-8-sig") as f:
        return {row["answer_id"]: row for row in csv.DictReader(f)}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--out", type=Path, help="also write the results to this Markdown file")
    parser.add_argument(
        "--run", nargs=2, action="append", metavar=("FILE", "NAME"), help="a results file to read"
    )
    parser.add_argument(
        "--repeat",
        nargs=2,
        action="append",
        metavar=("FIRST", "SECOND"),
        help="two results files of the same model and prompt, to compare",
    )
    args = parser.parse_args()
    runs = (
        {Path(file): name for file, name in args.run}
        if args.run
        else {EVAL_DIR / file: name for file, name in RUNS.items()}
    )
    repeats = (
        [(Path(a), Path(b)) for a, b in args.repeat]
        if args.repeat
        else []
        if args.run
        else [(EVAL_DIR / a, EVAL_DIR / b) for a, b in REPEATS]
    )

    calibration = [
        "| Run | Labels | Mean confidence | Accuracy | ECE | Brier | AUROC |",
        "|---|---|---|---|---|---|---|",
    ]
    buckets = [
        "| Run | Below 0.6 | 0.6 to 0.85 | 0.85 and up |",
        "|---|---|---|---|",
    ]
    cuts = [
        "| Run | "
        + " | ".join(f"Below {t:.2f}: hidden (wrong) / shown (wrong)" for t in REVIEW_THRESHOLDS)
        + " |",
        "|---|" + "---|" * len(REVIEW_THRESHOLDS),
    ]
    for path, name in runs.items():
        if not path.exists():
            print(f"skipped {path}: not found")
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
        cuts.append(
            f"| {name} | "
            + " | ".join(
                f"{c.flagged} ({c.flagged_wrong}) / {c.shown} ({c.shown_wrong})"
                for c in threshold_cuts(confidences, correct, REVIEW_THRESHOLDS)
            )
            + " |"
        )

    consistency = [
        "| Runs compared | Answers both read | Same label | Cohen's kappa |",
        "|---|---|---|---|",
    ]
    for first, second in repeats:
        a, b = read(first), read(second)
        shared = [
            i for i in a if i in b and a[i]["predicted"] in LABELS and b[i]["predicted"] in LABELS
        ]
        x = [a[i]["predicted"] for i in shared]
        y = [b[i]["predicted"] for i in shared]
        same = sum(p == q for p, q in zip(x, y, strict=True))
        consistency.append(
            f"| {runs.get(first, first.name)} vs {runs.get(second, second.name)} | {len(shared)} | "
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
            "What each review threshold would do: labels below it are shown as "
            '"Uncertain, ask your lecturer" (hidden), the rest with their label (shown); '
            "wrong counts in brackets:",
            "",
            *cuts,
            *(["", "## Consistency", "", *consistency] if repeats else []),
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
