"""Camera-free engagement scoring v2, dynamic prompt gating and class
comprehension alerts.

Owner: Cyber 1, Phases 3 and 6. The live classroom (app.realtime.classroom)
feeds these functions what it already observes and acts on what they return.

Camera-free: the score is built from participation the server sees for
itself -- questions attempted out of those the student was actually shown,
how quickly answers arrived within the response window, and how the student
answered attention prompts. Gaze and face presence are optional extras from a
client `signal.attention` event; nothing depends on them.

Fairness (Phase 6), the judgment calls:

* Weighted renormalisation. A signal with no evidence is dropped from the
  average rather than counted as zero, and the rest are re-weighted. Participation
  signals weigh PARTICIPATION_WEIGHT, camera-derived ones VISUAL_WEIGHT.
* The camera corroborates, it never accuses. A status needs at least one
  participation signal, so a student with only a camera reading is "insufficient
  data". A student whose participation alone reads ENGAGED stays ENGAGED
  whatever the camera says: looking away is not disengagement from someone who
  is answering. Where participation is low, the camera adds to the evidence.
* Personal baselines (engagement_baseline.py). Gaze, face presence and answer
  speed are read against the student's own session, not a fixed ideal, so
  looking at notes, a poorly placed camera or slow typing are not penalised.
  A camera that rarely finds the student's face is set aside as unreliable.
* Availability. Every signal that is not scored has an internal reason
  (EngagementComputation.unavailable), so "no data" is never mistaken for
  "low". Reasons are for the classroom and explanations, not a public field.
* Accessibility. For a student with a recorded accommodation, signals that
  assume a particular way of interacting (gaze, face presence) are not scored,
  and answer speed counts as a neutral typical value (NEUTRAL_TIMING), a prompt
  left to expire is not held against them, they are never classed DISENGAGED
  and never sent an automatic prompt. Only the fact that an accommodation
  exists is used, never what it says.

A student who has been shown fewer than MIN_QUESTIONS_SHOWN questions has no
attempt rate at all, so a late joiner is "insufficient data", not "at risk".
DISENGAGED needs at least two signals, and no prompt is ever sent on the
attempt rate alone.

`speaking` is not scored in either direction: voice activity is not evidence
of engagement with the lecture.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from statistics import median

from app.schemas.events import AttentionSignalPayload
from app.schemas.session import ComprehensionLabel, EngagementStatus
from app.services.engagement_baseline import MIN_BASELINE_SAMPLES, PersonalBaseline

PARTICIPATION_SIGNALS = ("attempt_rate", "response_timing", "prompt_response")
VISUAL_SIGNALS = ("gaze", "face_presence")

# Every signal this version can score. Confidence is how much of the weight
# that could apply to the student contributed, so it is comparable between
# students.
_SIGNAL_NAMES = (*PARTICIPATION_SIGNALS, *VISUAL_SIGNALS)

PARTICIPATION_WEIGHT = 1.0
VISUAL_WEIGHT = 0.5
_WEIGHTS = {
    **{name: PARTICIPATION_WEIGHT for name in PARTICIPATION_SIGNALS},
    **{name: VISUAL_WEIGHT for name in VISUAL_SIGNALS},
}

# Signals that assume a particular way of interacting, and so are not scored
# for a student with an accommodation.
ACCOMMODATED_UNSCORED = ("gaze", "face_presence")

# Answer speed for a student with an accommodation. It is not measured, but
# leaving the term out would make their score a different shape from everyone
# else's (a student who answered both of their first two questions would score
# exactly 1.0 where nobody else can), and staff see the score. So where another
# student would have an answer-speed term, theirs is this typical value: neither
# a reward nor a penalty. Staff see the score banded as well (engagement_view.py).
NEUTRAL_TIMING = 0.75

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

# Why a signal was not scored. Internal: never sent to a client.
REASON_TOO_FEW_QUESTIONS = "too_few_questions"
REASON_NO_ANSWERS = "no_answers"
REASON_NO_PROMPTS = "no_prompts"
REASON_NO_CAMERA_SIGNAL = "no_camera_signal"
REASON_CAMERA_UNRELIABLE = "camera_unreliable"
REASON_ACCOMMODATION = "accommodation"


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
    # The student's own normal for this session, if one has been kept.
    baseline: PersonalBaseline | None = None
    # Whether the student has a recorded accommodation. A fact, not its content.
    accommodated: bool = False


@dataclass(frozen=True)
class EngagementComputation:
    score: float | None
    status: EngagementStatus
    confidence: float
    signals_available: list[str]
    # signal name -> internal reason it was not scored.
    unavailable: dict[str, str] = field(default_factory=dict)
    accommodated: bool = False


def _clamp(value: float) -> float:
    return max(0.0, min(1.0, value))


def _timing_component(times: Sequence[float]) -> float:
    """How promptly the student answers, against how they usually answer.

    Answering at all scores at least 0.5; answering early scores up to 1.
    Once there is a pattern, only slowing down from the student's own median
    costs anything, so a consistently slow answerer is not penalised for it.
    """
    used = [_clamp(t) for t in times]
    if len(used) < MIN_BASELINE_SAMPLES:
        return 1.0 - 0.5 * (sum(used) / len(used))
    usual = median(used)
    recent = sum(used[-2:]) / 2
    drift = max(0.0, recent - usual) / max(1.0 - usual, 0.1)
    return 1.0 - 0.5 * _clamp(drift)


def _gaze_component(ratio: float, baseline: PersonalBaseline | None) -> float:
    """Gaze relative to how much this student normally looks at the screen."""
    usual = baseline.gaze_reference() if baseline is not None else None
    return _clamp(ratio / usual) if usual is not None else ratio


def compute_engagement(inputs: EngagementInputs) -> EngagementComputation:
    values: dict[str, float] = {}
    unavailable: dict[str, str] = {}
    accommodated = inputs.accommodated
    baseline = inputs.baseline

    if inputs.questions_shown >= MIN_QUESTIONS_SHOWN:
        values["attempt_rate"] = _clamp(inputs.questions_answered / inputs.questions_shown)
    else:
        unavailable["attempt_rate"] = REASON_TOO_FEW_QUESTIONS

    if not inputs.response_times:
        unavailable["response_timing"] = REASON_NO_ANSWERS
    elif accommodated:
        values["response_timing"] = NEUTRAL_TIMING
    else:
        values["response_timing"] = _timing_component(inputs.response_times)

    prompts = inputs.prompt_responses
    if accommodated:
        # A prompt that ran out is not proof of anything for someone who may
        # need longer, or another way, to respond.
        prompts = [p for p in prompts if p != PROMPT_EXPIRED]
    if prompts:
        values["prompt_response"] = _clamp(sum(prompts) / len(prompts))
    else:
        unavailable["prompt_response"] = REASON_NO_PROMPTS

    attention = inputs.attention
    for name in VISUAL_SIGNALS:
        if accommodated:
            unavailable[name] = REASON_ACCOMMODATION
        elif attention is None:
            unavailable[name] = REASON_NO_CAMERA_SIGNAL
    if not accommodated and attention is not None:
        if attention.gaze_on_screen_ratio is not None:
            values["gaze"] = _gaze_component(attention.gaze_on_screen_ratio, baseline)
        else:
            unavailable["gaze"] = REASON_NO_CAMERA_SIGNAL
        if attention.face_present is None:
            unavailable["face_presence"] = REASON_NO_CAMERA_SIGNAL
        elif baseline is not None and not baseline.face_reliable():
            unavailable["face_presence"] = REASON_CAMERA_UNRELIABLE
        else:
            values["face_presence"] = 1.0 if attention.face_present else 0.0

    signals = [name for name in _SIGNAL_NAMES if name in values]
    applicable = [
        name for name in _SIGNAL_NAMES if not (accommodated and name in ACCOMMODATED_UNSCORED)
    ]
    confidence = sum(_WEIGHTS[n] for n in signals) / sum(_WEIGHTS[n] for n in applicable)

    participation = [name for name in signals if name in PARTICIPATION_SIGNALS]
    if len(signals) < MIN_SIGNALS_FOR_STATUS or not participation:
        # Nothing, or only the camera: the camera alone is never grounds to
        # call a student anything.
        return EngagementComputation(
            score=None,
            status=EngagementStatus.INSUFFICIENT_DATA,
            confidence=confidence,
            signals_available=signals,
            unavailable=unavailable,
            accommodated=accommodated,
        )

    total = sum(_WEIGHTS[n] for n in signals)
    score = sum(_WEIGHTS[n] * values[n] for n in signals) / total
    participation_score = sum(values[n] for n in participation) / len(participation)
    if participation_score >= ENGAGED_THRESHOLD:
        # The camera may corroborate, but cannot pull down someone whose
        # participation says they are engaged.
        score = max(score, participation_score)

    if score >= ENGAGED_THRESHOLD:
        status = EngagementStatus.ENGAGED
    elif score >= AT_RISK_THRESHOLD or len(signals) < MIN_SIGNALS_FOR_DISENGAGED or accommodated:
        status = EngagementStatus.AT_RISK
    else:
        status = EngagementStatus.DISENGAGED

    return EngagementComputation(
        score=score,
        status=status,
        confidence=confidence,
        signals_available=signals,
        unavailable=unavailable,
        accommodated=accommodated,
    )


def should_send_dynamic_prompt(computation: EngagementComputation) -> bool:
    """Whether the engagement state warrants a private refocus nudge.

    Needs a low status backed by at least two signals, one of them
    participation: a low attempt rate on its own is exactly what a student who
    has just joined, or is thinking through a hard question, looks like. A
    student with an accommodation is never nudged automatically. Whether a
    prompt may go out right now (cap, pause, open question, connection) is the
    classroom's call.
    """
    return (
        not computation.accommodated
        and computation.status in (EngagementStatus.AT_RISK, EngagementStatus.DISENGAGED)
        and len(computation.signals_available) >= MIN_SIGNALS_FOR_PROMPT
        and any(n in PARTICIPATION_SIGNALS for n in computation.signals_available)
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
