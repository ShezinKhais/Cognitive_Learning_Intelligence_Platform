"""Camera-free engagement scoring v1, dynamic prompt gating and class
comprehension alerts.

Owner: Cyber 1, Phase 3. The live classroom (app.realtime.classroom) feeds
these functions what it already observes and acts on what they return.

Camera-free: the score is built from participation the server sees for
itself -- questions attempted out of those the student was actually shown,
how quickly answers arrived within the response window, and how the student
answered attention prompts. Gaze and face presence are optional extras from a
client `signal.attention` event; nothing depends on them.

Renormalisation: a signal with no evidence yet is dropped from the average
rather than counted as zero, and `confidence` reports how many signals backed
the score. A student who has been shown fewer than MIN_QUESTIONS_SHOWN
questions has no attempt rate at all, so a late joiner is "insufficient data",
not "at risk". DISENGAGED needs at least two signals, and no prompt is ever
sent on the attempt rate alone.

`speaking` is not scored in either direction: voice activity is not evidence
of engagement with the lecture.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field

from app.schemas.events import AttentionSignalPayload
from app.schemas.session import ComprehensionLabel, EngagementStatus

# Every signal this version can score. Confidence is how many contributed,
# out of this fixed total, so it is comparable between students.
_SIGNAL_NAMES = ("attempt_rate", "response_timing", "prompt_response", "gaze", "face_presence")

ENGAGED_THRESHOLD = 0.6
AT_RISK_THRESHOLD = 0.3

# One question is not a rate. Below this many questions shown to the student,
# attempt_rate is not a signal yet.
MIN_QUESTIONS_SHOWN = 2

# A client attention signal older than this no longer describes the student.
ATTENTION_SIGNAL_MAX_AGE_SECONDS = 120

MIN_SIGNALS_FOR_STATUS = 1
MIN_SIGNALS_FOR_DISENGAGED = 2
MIN_SIGNALS_FOR_PROMPT = 2

# How each resolved attention prompt counts towards prompt_response.
PROMPT_ACKNOWLEDGED = 1.0
PROMPT_DISMISSED = 0.5
PROMPT_EXPIRED = 0.0


@dataclass(frozen=True)
class EngagementInputs:
    questions_shown: int = 0
    questions_answered: int = 0
    # Per answered question: the fraction of the response window that had
    # passed when the server received the answer, 0.0 to 1.0.
    response_times: Sequence[float] = field(default_factory=tuple)
    # Per resolved prompt: PROMPT_ACKNOWLEDGED, PROMPT_DISMISSED or PROMPT_EXPIRED.
    prompt_responses: Sequence[float] = field(default_factory=tuple)
    attention: AttentionSignalPayload | None = None


@dataclass(frozen=True)
class EngagementComputation:
    score: float | None
    status: EngagementStatus
    confidence: float
    signals_available: list[str]


def _clamp(value: float) -> float:
    return max(0.0, min(1.0, value))


def compute_engagement(inputs: EngagementInputs) -> EngagementComputation:
    components: list[float] = []
    signals: list[str] = []

    if inputs.questions_shown >= MIN_QUESTIONS_SHOWN:
        components.append(_clamp(inputs.questions_answered / inputs.questions_shown))
        signals.append("attempt_rate")

    if inputs.response_times:
        # Answering at all scores at least 0.5; answering early scores up to 1.
        used = sum(_clamp(t) for t in inputs.response_times) / len(inputs.response_times)
        components.append(1.0 - 0.5 * used)
        signals.append("response_timing")

    if inputs.prompt_responses:
        components.append(_clamp(sum(inputs.prompt_responses) / len(inputs.prompt_responses)))
        signals.append("prompt_response")

    attention = inputs.attention
    if attention is not None:
        if attention.gaze_on_screen_ratio is not None:
            components.append(attention.gaze_on_screen_ratio)
            signals.append("gaze")
        if attention.face_present is not None:
            components.append(1.0 if attention.face_present else 0.0)
            signals.append("face_presence")

    confidence = len(signals) / len(_SIGNAL_NAMES)

    if len(signals) < MIN_SIGNALS_FOR_STATUS:
        return EngagementComputation(
            score=None,
            status=EngagementStatus.INSUFFICIENT_DATA,
            confidence=confidence,
            signals_available=signals,
        )

    score = sum(components) / len(components)

    if score >= ENGAGED_THRESHOLD:
        status = EngagementStatus.ENGAGED
    elif score >= AT_RISK_THRESHOLD or len(signals) < MIN_SIGNALS_FOR_DISENGAGED:
        status = EngagementStatus.AT_RISK
    else:
        status = EngagementStatus.DISENGAGED

    return EngagementComputation(
        score=score,
        status=status,
        confidence=confidence,
        signals_available=signals,
    )


def should_send_dynamic_prompt(computation: EngagementComputation) -> bool:
    """Whether the engagement state warrants a private refocus nudge.

    Needs a low status backed by at least two signals: a low attempt rate on
    its own is exactly what a student who has just joined, or is thinking
    through a hard question, looks like. Whether a prompt may go out right
    now (cap, pause, open question, connection) is the classroom's call.
    """
    return (
        computation.status in (EngagementStatus.AT_RISK, EngagementStatus.DISENGAGED)
        and len(computation.signals_available) >= MIN_SIGNALS_FOR_PROMPT
    )


@dataclass(frozen=True)
class ComprehensionAlertDecision:
    should_alert: bool
    respondents: int
    # Share of valid respondents classified mastered, or None below the
    # minimum -- "not enough answers yet" is not "the class got it wrong".
    correct_ratio: float | None
    struggling_ratio: float | None


def evaluate_comprehension_alert(
    labels: Iterable[str],
    *,
    min_respondents: int,
    threshold: float,
) -> ComprehensionAlertDecision:
    """Class-wide "this question tripped the class up" check.

    `labels` is one comprehension classification per respondent. Anything
    that is not a known ComprehensionLabel (a free-text answer still being
    classified, say) is not a valid respondent. The alert is raised once at
    least min_respondents valid respondents exist and at least `threshold`
    of them are classified partial or struggling.
    """
    known = {label.value for label in ComprehensionLabel}
    valid = [label for label in labels if label in known]
    respondents = len(valid)
    if respondents == 0 or respondents < min_respondents:
        return ComprehensionAlertDecision(
            should_alert=False, respondents=respondents, correct_ratio=None, struggling_ratio=None
        )

    mastered = sum(1 for label in valid if label == ComprehensionLabel.MASTERED.value)
    struggling_ratio = (respondents - mastered) / respondents
    return ComprehensionAlertDecision(
        should_alert=struggling_ratio >= threshold,
        respondents=respondents,
        correct_ratio=mastered / respondents,
        struggling_ratio=struggling_ratio,
    )
