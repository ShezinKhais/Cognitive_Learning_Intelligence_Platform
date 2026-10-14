"""What staff are shown about the evidence behind an engagement score.

Owner: Cyber 1, Phase 6. The scorer keeps fine-grained evidence internally: which
signals contributed, and how much of what could have applied did. For a student
with an accommodation, answer speed, gaze and face presence are never scored, so
that detail, shown per student, would tell a lecturer who has an accommodation
even though the accommodation itself is never sent anywhere.

So staff see one view, computed the same way for every student from one thing:
whether any *participation* signal (questions attempted, answer timing, attention
prompt responses) backed the score. Not how many: an accommodated student can
never have the answer-speed signal, so a count, even a capped one, would still
tell a student with one signal from one with two.
Camera-derived signals are never named to staff: they only ever added to a score,
and a per-student camera detail is not something a lecturer should act on.

The internal EngagementComputation is unchanged and is what scoring, prompting
and tests use. Anything shown to staff goes through here.

This module imports nothing from the application, and is identical on every
branch that uses it.
"""

from __future__ import annotations

from collections.abc import Iterable

PARTICIPATION_SIGNALS = ("attempt_rate", "response_timing", "prompt_response")

# The one name staff see. Not a scorer signal: a summary of the ones above.
PARTICIPATION = "participation"

# The most participation evidence that cannot tell students apart: every
# student with any participation signal has at least one (questions attempted).
COMMON_CEILING = 1


def participation_count(signals: Iterable[str]) -> int:
    return sum(1 for name in signals if name in PARTICIPATION_SIGNALS)


def staff_signals(signals: Iterable[str]) -> list[str]:
    """['participation'] when any participation signal scored the student, else []."""
    return [PARTICIPATION] if participation_count(signals) else []


def staff_confidence(signals: Iterable[str]) -> float:
    """1.0 when participation evidence backed the score, else 0.0. Whether there was
    evidence, not a probability that the score is right."""
    return min(participation_count(signals), COMMON_CEILING) / COMMON_CEILING
