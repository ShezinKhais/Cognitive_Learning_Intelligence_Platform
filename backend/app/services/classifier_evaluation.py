"""How well one set of labels agrees with another.

Owner: AI 1, Phase 5 (#55). Used to measure the free-text classifier against
the hand-labelled answers in tests/eval, and the two labellers against each
other, and whether the classifier's confidence tells right labels from
wrong ones. Plain functions over lists, so they need no model.
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
    """The average F1 across labels, so a rare label counts as much as a common one.

    Every label that was expected or predicted counts: a label the classifier
    gives where the human never did scores 0 rather than dropping out.
    """
    seen = set(expected) | set(predicted)
    scores = [s.f1 or 0.0 for s in label_stats(expected, predicted, labels) if s.label in seen]
    return sum(scores) / len(scores) if scores else 0.0


@dataclass(frozen=True)
class ConfidenceBucket:
    low: float
    # Exclusive, except the top bucket, which holds everything from `low` up.
    high: float | None
    answers: int
    right: int
    accuracy: float | None


def _checked(confidences: Sequence[float], correct: Sequence[bool]) -> None:
    if len(confidences) != len(correct):
        raise ValueError(f"{len(confidences)} confidences but {len(correct)} results")


def confidence_buckets(
    confidences: Sequence[float], correct: Sequence[bool], edges: Sequence[float] = (0.6, 0.85)
) -> list[ConfidenceBucket]:
    """How often labels were right at each level of confidence.

    Trustworthy confidence is right more often the higher it is. `edges`
    splits 0 to 1 into buckets: the default gives below 0.6, 0.6 to 0.85 and
    0.85 up.
    """
    _checked(confidences, correct)
    bounds = [0.0, *edges]
    buckets = []
    for i, low in enumerate(bounds):
        high = bounds[i + 1] if i + 1 < len(bounds) else None
        inside = [
            ok
            for c, ok in zip(confidences, correct, strict=True)
            if c >= low and (high is None or c < high)
        ]
        accuracy = sum(inside) / len(inside) if inside else None
        buckets.append(ConfidenceBucket(low, high, len(inside), sum(inside), accuracy))
    return buckets


def confidence_separation(confidences: Sequence[float], correct: Sequence[bool]) -> float | None:
    """The chance a right label has higher confidence than a wrong one.

    The area under the ROC curve: 1 means confidence always ranks right labels
    above wrong ones, 0.5 is no better than a coin. None when every label was
    right, or every one wrong, since there is nothing to separate.
    """
    _checked(confidences, correct)
    right = [c for c, ok in zip(confidences, correct, strict=True) if ok]
    wrong = [c for c, ok in zip(confidences, correct, strict=True) if not ok]
    if not right or not wrong:
        return None
    wins = sum((r > w) + 0.5 * (r == w) for r in right for w in wrong)
    return wins / (len(right) * len(wrong))


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
