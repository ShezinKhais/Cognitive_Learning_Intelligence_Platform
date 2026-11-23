"""Bootstrap confidence intervals for the AI evaluation report (Phase 8, AI 1, #73).

The test sets are small (11 retrieval questions, 25 drafts, 40 answers), so a
single score says little about how much it could move on another set of the
same size. The bootstrap estimates that from the data itself: draw a new set
of the same size from the items, with replacement, score it, and repeat many
times. The middle 95% of those scores is the 95% confidence interval.

Items are resampled whole: a question with its before and after ranks, an
answer with its human and model labels, so paired measures stay paired. The
percentile method is used, with a fixed seed so a rerun gives the same
interval.
"""

from __future__ import annotations

import random
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import TypeVar

T = TypeVar("T")

RESAMPLES = 10_000
CONFIDENCE = 0.95


@dataclass(frozen=True)
class Interval:
    value: float
    low: float
    high: float
    n: int


def bootstrap(
    items: Sequence[T],
    statistic: Callable[[Sequence[T]], float],
    *,
    resamples: int = RESAMPLES,
    confidence: float = CONFIDENCE,
    seed: int = 0,
) -> Interval:
    """`statistic` on `items`, and its percentile bootstrap interval."""
    if not items:
        raise ValueError("no items to resample")
    rng = random.Random(seed)
    n = len(items)
    scores = sorted(
        statistic([items[rng.randrange(n)] for _ in range(n)]) for _ in range(resamples)
    )
    tail = (1 - confidence) / 2
    low = scores[int(tail * resamples)]
    high = scores[min(resamples - 1, int((1 - tail) * resamples))]
    return Interval(statistic(items), low, high, n)


def mean(values: Sequence[float]) -> float:
    return sum(values) / len(values)


def proportion(successes: int, total: int) -> Interval:
    """A share, such as 9 of 25 drafts accepted, with its interval."""
    return bootstrap([1.0] * successes + [0.0] * (total - successes), mean)


def markdown_table(rows: Sequence[tuple[str, Interval, str]]) -> str:
    """One row per measure: (name, interval, how to print it: "%" or "2dp")."""
    lines = ["| Measure | Value | 95% interval | n |", "|---|---|---|---|"]
    for name, interval, style in rows:
        show = (lambda v: f"{v:.0%}") if style == "%" else (lambda v: f"{v:.2f}")
        lines.append(
            f"| {name} | {show(interval.value)} | {show(interval.low)} to "
            f"{show(interval.high)} | {interval.n} |"
        )
    return "\n".join(lines)
