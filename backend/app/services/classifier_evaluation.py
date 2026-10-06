"""How well one set of labels agrees with another.

Owner: AI 1, Phase 5 (#55). Used to measure the free-text classifier against
the hand-labelled answers in tests/eval, and the two labellers against each
other. Plain functions over lists of label strings, so they need no model.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

LABELS = ("mastered", "partial", "struggling")


@dataclass(frozen=True)
class LabelStats:
    label: str
    precision: float | None
    recall: float | None
    f1: float | None
    # How many of `expected` carry this label.
    support: int


def _paired(expected: Sequence[str], predicted: Sequence[str]) -> list[tuple[str, str]]:
    if len(expected) != len(predicted):
        raise ValueError(f"{len(expected)} expected labels but {len(predicted)} predicted")
    if not expected:
        raise ValueError("no labels to compare")
    return list(zip(expected, predicted, strict=True))


def accuracy(expected: Sequence[str], predicted: Sequence[str]) -> float:
    pairs = _paired(expected, predicted)
    return sum(e == p for e, p in pairs) / len(pairs)


def confusion_matrix(
    expected: Sequence[str], predicted: Sequence[str], labels: Sequence[str] = LABELS
) -> dict[str, dict[str, int]]:
    """matrix[expected][predicted] = how many answers had that pair."""
    matrix = {e: dict.fromkeys(labels, 0) for e in labels}
    for e, p in _paired(expected, predicted):
        matrix[e][p] += 1
    return matrix


def label_stats(
    expected: Sequence[str], predicted: Sequence[str], labels: Sequence[str] = LABELS
) -> list[LabelStats]:
    pairs = _paired(expected, predicted)
    stats = []
    for label in labels:
        true_pos = sum(e == label and p == label for e, p in pairs)
        predicted_as = sum(p == label for _, p in pairs)
        actual = sum(e == label for e, _ in pairs)
        precision = true_pos / predicted_as if predicted_as else None
        recall = true_pos / actual if actual else None
        f1 = (
            2 * precision * recall / (precision + recall)
            if precision is not None and recall is not None and precision + recall
            else None
        )
        stats.append(LabelStats(label, precision, recall, f1, actual))
    return stats


def macro_f1(
    expected: Sequence[str], predicted: Sequence[str], labels: Sequence[str] = LABELS
) -> float:
    """The average F1 across labels, so a rare label counts as much as a common one."""
    scores = [s.f1 or 0.0 for s in label_stats(expected, predicted, labels) if s.support]
    return sum(scores) / len(scores) if scores else 0.0


def cohen_kappa(a: Sequence[str], b: Sequence[str], labels: Sequence[str] = LABELS) -> float:
    """Agreement between two labellers beyond what chance alone would give.

    1 is perfect agreement, 0 is no better than chance. Used for the two hand
    labellings, to show how clear the labelling rules are.
    """
    pairs = _paired(a, b)
    n = len(pairs)
    observed = sum(x == y for x, y in pairs) / n
    chance = sum(
        (sum(x == label for x, _ in pairs) / n) * (sum(y == label for _, y in pairs) / n)
        for label in labels
    )
    if chance == 1:
        return 1.0
    return (observed - chance) / (1 - chance)
