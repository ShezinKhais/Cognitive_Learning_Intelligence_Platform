"""Camera-free engagement scoring v1, dynamic prompt gating and class
comprehension alerts.

Owner: Cyber 1, Phase 3.

"Camera-free" means no signal here requires a camera: v1 scores whatever a
student's device reports (a checkpoint attempt rate that always exists once a
question has gone out, plus an optional, client-computed `signal.attention`
event) without depending on any of it. Phase 6 adds the actual local gaze/VAD
indicators this schema already has room for; this module does not change when
that lands; it just receives more populated payloads.

Renormalisation: a missing signal is dropped from the average rather than
counted as zero, so a student who never sent an attention signal is not
scored as if they were visibly absent. `EngagementOut.confidence` reports how
much of the score is backed by evidence, and a low-confidence result is
rendered as "insufficient data", never as "disengaged" -- see
`app.schemas.session.EngagementOut`'s own docstring. For the same reason,
`DISENGAGED` itself is never returned from a single signal -- attempt_rate
alone, the first thing available once a question has gone out, is not enough
evidence to make the module's strongest judgement call; that reading is
reported as `AT_RISK` until a second signal corroborates it.

`speaking` is recorded on the payload but does not contribute to the score
in either direction: voice activity is not evidence of engagement with the
lecture (a student chatting to a neighbour scores as high as one answering a
question aloud), and there is no validated read on it yet.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.schemas.events import AttentionSignalPayload
from app.schemas.session import EngagementStatus

# Every signal this version can score, in the order signals_available reports
# them when present. Confidence is how many of these actually contributed,
# out of the total -- a fixed denominator so confidence is comparable across
# students who happened to send different signals. `speaking` is not in this
# list: it's recorded on the payload but never scored (see module docstring).
_SIGNAL_NAMES = ("attempt_rate", "gaze", "face_presence")

ENGAGED_THRESHOLD = 0.6
AT_RISK_THRESHOLD = 0.3

# Below this, the score is backed by too little evidence to call a status at
# all: zero signals available. Any single signal (attempt_rate, gaze or face
# presence) already clears it, which is deliberate -- attempt_rate is
# available from the first delivered question onward, and a student must not
# be called "insufficient data" for the entire session just because their
# device never sent an attention event.
MIN_CONFIDENCE_FOR_STATUS = 1 / len(_SIGNAL_NAMES)

# A single signal clears MIN_CONFIDENCE_FOR_STATUS but is not enough evidence
# to call the module's strongest judgement, DISENGAGED -- see module
# docstring. Two or more signals agreeing is required.
MIN_CONFIDENCE_FOR_DISENGAGED = 2 / len(_SIGNAL_NAMES)


@dataclass(frozen=True)
class EngagementComputation:
    score: float | None
    status: EngagementStatus
    confidence: float
    signals_available: list[str]


def compute_engagement(
    attempt_rate: float | None,
    attention: AttentionSignalPayload | None,
) -> EngagementComputation:
    components: list[float] = []
    signals: list[str] = []

    if attempt_rate is not None:
        components.append(max(0.0, min(1.0, attempt_rate)))
        signals.append("attempt_rate")

    if attention is not None:
        if attention.gaze_on_screen_ratio is not None:
            components.append(attention.gaze_on_screen_ratio)
            signals.append("gaze")
        if attention.face_present is not None:
            components.append(1.0 if attention.face_present else 0.0)
            signals.append("face_presence")

    confidence = len(signals) / len(_SIGNAL_NAMES)

    if not components or confidence < MIN_CONFIDENCE_FOR_STATUS:
        return EngagementComputation(
            score=None,
            status=EngagementStatus.INSUFFICIENT_DATA,
            confidence=confidence,
            signals_available=signals,
        )

    score = sum(components) / len(components)

    if score >= ENGAGED_THRESHOLD:
        status = EngagementStatus.ENGAGED
    elif score >= AT_RISK_THRESHOLD or confidence < MIN_CONFIDENCE_FOR_DISENGAGED:
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

    Never fires on insufficient data -- a status this module itself refuses
    to call disengaged must not trigger the same nudge disengagement does.
    This only decides whether engagement warrants a nudge; whether one is
    currently allowed to go out (per-student cap, pause state, an open
    question, connection status) is the live classroom's call, not this
    module's -- it owns that state and would otherwise drift out of sync
    with a second copy of the same limits kept here.
    """
    return computation.status in (EngagementStatus.AT_RISK, EngagementStatus.DISENGAGED)


@dataclass(frozen=True)
class ComprehensionAlertDecision:
    should_alert: bool
    correct_ratio: float | None


def evaluate_comprehension_alert(
    *,
    respondents: int,
    correct_count: int,
    min_respondents: int,
    threshold: float,
) -> ComprehensionAlertDecision:
    """Class-wide "this question tripped the class up" check.

    The minimum-respondent guard exists because a 1-in-2 correct ratio from
    two early answers is noise, not a signal -- comprehension_alert_min_
    respondents (default 5) is the smallest sample this module treats as
    meaningful, regardless of how low the ratio looks. `correct_ratio` is
    `None` in that case, not `0.0` -- "not enough answers yet" is a different
    fact from "the class got it wrong," and a dashboard or log reading the
    field must not confuse the two.
    """
    if respondents < min_respondents or respondents == 0:
        return ComprehensionAlertDecision(should_alert=False, correct_ratio=None)

    correct_ratio = correct_count / respondents
    return ComprehensionAlertDecision(
        should_alert=correct_ratio < threshold,
        correct_ratio=correct_ratio,
    )
