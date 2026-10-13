"""95% confidence intervals for the evaluation results, for the AI evaluation
report (Phase 8, AI 1, #73).

Not a test. Needs no model: it reads the results the other evaluation scripts
saved in tests/eval and bootstraps each measure (see
app/services/confidence_intervals.py). Run from backend/:

    python -m scripts.confidence_intervals
    python -m scripts.confidence_intervals --out tests/eval/CONFIDENCE_INTERVALS.md
"""

from __future__ import annotations

import argparse
import csv
import re
from pathlib import Path

from app.services.classifier_evaluation import LABELS, accuracy, cohen_kappa, macro_f1
from app.services.confidence_intervals import Interval, bootstrap, markdown_table, mean, proportion
from app.services.grounding_evaluation import grounding_precision

EVAL_DIR = Path(__file__).resolve().parent.parent / "tests" / "eval"
CLASSIFIER_RUNS = {
    "results_qwen3b_run2.csv": "qwen2.5:3b run 2",
    "results_qwen7b.csv": "qwen2.5:7b run 1",
    "results_qwen7b_run2.csv": "qwen2.5:7b run 2",
}
TOP_K = 5


def retrieval_ranks(path: Path) -> list[tuple[int | None, int | None]]:
    """(rank before, rank after) per question, from RETRIEVAL_RESULTS.md. A
    rank of "-" means no chunk came from an answering page: None."""

    def rank(cell: str) -> int | None:
        first = cell.strip().split(" ")[0]
        return None if first == "-" else int(first)

    ranks = []
    for line in path.read_text().splitlines():
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        # Results from before the Material column have one cell fewer.
        if len(cells) == 6:
            cells = cells[1:]
        if len(cells) == 5 and cells[0] in {"image", "text"}:
            ranks.append((rank(cells[3]), rank(cells[4])))
    return ranks


def hit(rank: int | None) -> float:
    return float(rank is not None and rank <= TOP_K)


def reciprocal(rank: int | None) -> float:
    return 1 / rank if rank else 0.0


def grounding_counts(path: Path) -> tuple[int, int]:
    """(accepted, drafts) from GROUNDING_RESULTS.md."""
    text = path.read_text()
    drafts = int(re.search(r"\| Drafts \| (\d+) \|", text).group(1))
    accepted = int(re.search(r"\| Accepted \| (\d+) \|", text).group(1))
    return accepted, drafts


def classifier_pairs(path: Path) -> list[tuple[str, str]]:
    with path.open(newline="", encoding="utf-8-sig") as f:
        return [(row["human"], row["predicted"]) for row in csv.DictReader(f)]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--out", type=Path, help="also write the table to this Markdown file")
    args = parser.parse_args()

    rows: list[tuple[str, Interval, str]] = []

    ranks = retrieval_ranks(EVAL_DIR / "RETRIEVAL_RESULTS.md")
    rows += [
        (
            "Retrieval hit@5, before captions",
            bootstrap(ranks, lambda s: mean([hit(b) for b, _ in s])),
            "2dp",
        ),
        (
            "Retrieval hit@5, after captions",
            bootstrap(ranks, lambda s: mean([hit(a) for _, a in s])),
            "2dp",
        ),
        (
            "Retrieval hit@5, gain from captions",
            bootstrap(ranks, lambda s: mean([hit(a) - hit(b) for b, a in s])),
            "2dp",
        ),
        (
            "Retrieval MRR, after captions",
            bootstrap(ranks, lambda s: mean([reciprocal(a) for _, a in s])),
            "2dp",
        ),
        (
            "Retrieval MRR, gain from captions",
            bootstrap(ranks, lambda s: mean([reciprocal(a) - reciprocal(b) for b, a in s])),
            "2dp",
        ),
    ]

    accepted, drafts = grounding_counts(EVAL_DIR / "GROUNDING_RESULTS.md")
    supported, judged = grounding_precision(EVAL_DIR / "grounding_accepted.csv")
    rows += [
        ("Grounding: drafts passing the checks", proportion(accepted, drafts), "%"),
        ("Grounding precision (accepted, judged correct)", proportion(supported, judged), "%"),
    ]

    for file, name in CLASSIFIER_RUNS.items():
        path = EVAL_DIR / file
        if not path.exists():
            continue
        pairs = classifier_pairs(path)
        read = [(h, p) for h, p in pairs if p in LABELS]
        rows += [
            (
                f"Marking accuracy, {name} (all 40)",
                bootstrap(pairs, lambda s: accuracy([h for h, _ in s], [p for _, p in s])),
                "%",
            ),
            (
                f"Marking macro F1, {name} (replies read)",
                bootstrap(read, lambda s: macro_f1([h for h, _ in s], [p for _, p in s])),
                "2dp",
            ),
        ]

    with (EVAL_DIR / "answers_to_label.csv").open(newline="", encoding="utf-8") as f:
        labels = [(row["label_luna"], row["label_nour"]) for row in csv.DictReader(f)]
    rows.append(
        (
            "Cohen's kappa, Luna vs Nour",
            bootstrap(labels, lambda s: cohen_kappa([a for a, _ in s], [b for _, b in s])),
            "2dp",
        )
    )

    table = markdown_table(rows)
    print(table)
    if args.out:
        args.out.write_text(
            "# Confidence intervals\n\n"
            "95% percentile bootstrap intervals, 10,000 resamples with a fixed seed. Each "
            "item (a question, a draft, an answer) is resampled whole, so before and after "
            "ranks and human and model labels stay paired. A wide interval means the test "
            "set is too small to pin the score down; an interval for a gain that stays "
            "above 0 means the gain is unlikely to be chance.\n\n" + table + "\n"
        )
        print(f"\nwritten to {args.out}")


if __name__ == "__main__":
    main()
