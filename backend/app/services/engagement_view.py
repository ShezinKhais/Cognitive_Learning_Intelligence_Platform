"""What staff are shown about the evidence behind an engagement score.

Owner: Cyber 1, Phase 6. The scorer keeps fine-grained evidence internally: which
signals contributed, and how much of what could have applied did. For a student
with an accommodation, answer speed, gaze and face presence are never scored, so
that detail, shown per student, would tell a lecturer who has an accommodation
even though the accommodation itself is never sent anywhere.

So staff see one view, computed the same way for every student from one thing:
how many *participation* signals (questions attempted, answer timing, attention
prompt responses) backed the score, capped at what every student can have.
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

# The most participation evidence every student can have: an accommodated
# student is never scored on answer speed, so two is what all can reach.
COMMON_CEILING = 2


def participation_count(signals: Iterable[str]) -> int:
    return sum(1 for name in signals if name in PARTICIPATION_SIGNALS)


def staff_signals(signals: Iterable[str]) -> list[str]:
    """['participation'] when any participation signal scored the student, else []."""
    return [PARTICIPATION] if participation_count(signals) else []


def staff_confidence(signals: Iterable[str]) -> float:
    """0, 0.5 or 1.0: participation evidence, capped at what every student can have."""
    return min(participation_count(signals), COMMON_CEILING) / COMMON_CEILING
