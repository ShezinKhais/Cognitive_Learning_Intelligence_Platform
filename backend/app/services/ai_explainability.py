"""Safe reasons, confidence reasons and lecturer recommendations for AI alerts.

Owner: Cyber 1, Phase 5. PHASES.md: "Every AI alert and recommendation has a
safe reason and fallback explanation."

An alert tells a lecturer something about their class, so the lecturer has to
be able to see why, and how far to trust it. Three rules follow, and every
function here keeps them:

* The reason and the confidence reasons are built from numbers the server
  holds (counts, coverage, confidence, signals), never from text a model wrote.
  They cannot carry an injected instruction, and they cannot disagree with the
  alert they explain.
* The explanation is what a model wrote when it passes screening, and the
  deterministic account of the same numbers when it does not. Missing, unsafe
  and over-long model text all land on the same fallback, so an alert is never
  held back, and never shown without one.
* The recommendation is rules over the same numbers, not model output. It says
  what to do, and says when the evidence is too thin to act on.

Everything here is pure: no I/O, no clock, and no failure mode that should
stop an alert. A caller that still meets an error uses fallback_explanation.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Literal

from app.schemas.events import AlertKind
from app.schemas.session import ComprehensionLabel, EngagementStatus
from app.services.engagement import EngagementComputation
from app.services.text_screening import safe_display_text

MAX_TOPIC_CHARS = 80
MAX_EXPLANATION_CHARS = 400

# Fewer than half of the students who saw a question have an answer on record.
LOW_COVERAGE = 0.5
# Below this the classifier is unsure of its own labels.
LOW_CLASSIFIER_CONFIDENCE = 0.6
# At least this share of the classified answers struggling means the idea did
# not land, rather than landing only in part.
STRUGGLING_MAJORITY = 0.5

# What each engagement signal is called to a lecturer. Keys are the names
# engagement.py scores; a test keeps the two in step.
SIGNAL_LABELS = {
    "attempt_rate": "questions attempted",
    "response_timing": "how quickly answers arrived",
    "prompt_response": "responses to attention prompts",
    "gaze": "gaze on screen",
    "face_presence": "face presence",
}

ExplanationSource = Literal["ai", "fallback"]


@dataclass(frozen=True)
class AlertExplanation:
    """Everything a lecturer is shown about why an alert was raised."""

    message: str
    reason: str
    explanation: str
    explanation_source: ExplanationSource
    confidence: float
    confidence_reasons: tuple[str, ...]
    recommendation: str


@dataclass(frozen=True)
class TopicEvidence:
    """What a class comprehension alert is built from."""

    # One comprehension label per respondent, as AI 1 recorded them.
    labels: Sequence[str]
    # Students who were shown the question.
    eligible: int
    min_respondents: int
    threshold: float
    # The classifier's confidence in each label, when it reports one.
    confidences: Sequence[float] = ()
    topic: str | None = None
    source_slide: int | None = None


def _percent(value: float) -> int:
    return round(max(0.0, min(1.0, value)) * 100)


def _mean(values: Sequence[float]) -> float | None:
    clamped = [max(0.0, min(1.0, v)) for v in values]
    return sum(clamped) / len(clamped) if clamped else None


def explain_topic_difficulty(
    evidence: TopicEvidence, *, model_explanation: str | None = None
) -> AlertExplanation:
    """Explain a class comprehension alert.

    Works for any evidence, including none: with no classified answers the
    reason says so and the recommendation is to wait.
    """
    known = {label.value for label in ComprehensionLabel}
    valid = [label for label in evidence.labels if label in known]
    respondents = len(valid)
    mastered = valid.count(ComprehensionLabel.MASTERED.value)
    partial = valid.count(ComprehensionLabel.PARTIAL.value)
    struggling = valid.count(ComprehensionLabel.STRUGGLING.value)
    behind = respondents - mastered

    eligible = max(evidence.eligible, respondents, 1)
    coverage = respondents / eligible
    classifier_confidence = _mean(evidence.confidences)
    confidence = coverage * (1.0 if classifier_confidence is None else classifier_confidence)

    topic = safe_display_text(evidence.topic, limit=MAX_TOPIC_CHARS)
    about = f" on {topic}" if topic else ""
    message = f"Much of the class is struggling{about}."

    if respondents == 0:
        reason = "No classified answers have been recorded for this question yet."
        fallback = (
            "No answers to this question have been classified, so there is nothing "
            "to explain yet. The alert will be explained once answers arrive."
        )
        recommendation = (
            "Wait for more answers before acting: nothing has been classified for this question."
        )
        reasons = (
            f"0 of {eligible} students shown the question have a classified answer.",
            f"An alert needs at least {evidence.min_respondents} classified answers.",
        )
    else:
        reason = f"{behind} of {respondents} classified answers were partial or struggling."
        fallback = (
            f"{reason} That is {struggling} struggling and {partial} partial, against an "
            f"alert threshold of {_percent(evidence.threshold)}%."
            + (f" The question was on {topic}." if topic else "")
        )
        reasons_list = [
            f"{respondents} of {eligible} students shown the question have a classified "
            f"answer ({_percent(coverage)}% coverage).",
        ]
        if classifier_confidence is not None:
            reasons_list.append(
                f"The classifier's confidence averages {_percent(classifier_confidence)}% "
                "across those answers."
            )
            if classifier_confidence < LOW_CLASSIFIER_CONFIDENCE:
                reasons_list.append(
                    "Several classifications are low-confidence, so treat this as provisional."
                )
        reasons_list.append(
            f"An alert needs at least {evidence.min_respondents} classified answers and "
            f"{_percent(evidence.threshold)}% of them partial or struggling; this has "
            f"{respondents} and {_percent(behind / respondents)}%."
        )
        reasons = tuple(reasons_list)

        provisional = coverage < LOW_COVERAGE or (
            classifier_confidence is not None and classifier_confidence < LOW_CLASSIFIER_CONFIDENCE
        )
        label = topic or "this topic"
        slide = (
            f" Slide {evidence.source_slide} of the lecture material covers it."
            if evidence.source_slide is not None
            else ""
        )
        if provisional:
            recommendation = (
                f"Ask a quick follow-up question before re-teaching {label}: few answers "
                "are in, or the classifications are uncertain, so this may not reflect "
                "the whole class."
            )
        elif struggling / respondents >= STRUGGLING_MAJORITY:
            recommendation = (
                f"Re-teach {label}: most classified answers show the core idea was not "
                f"understood. Walk through it again with a worked example.{slide}"
            )
        else:
            recommendation = (
                f"Clarify {label}: most students have part of the idea but not all of it. "
                f"A short recap of the key distinction should close the gap.{slide}"
            )

    shown = safe_display_text(model_explanation, limit=MAX_EXPLANATION_CHARS)
    return AlertExplanation(
        message=message,
        reason=reason,
        explanation=shown or fallback,
        explanation_source="ai" if shown else "fallback",
        confidence=max(0.0, min(1.0, confidence)),
        confidence_reasons=reasons,
        recommendation=recommendation,
    )


def explain_student_engagement(
    computation: EngagementComputation, *, model_explanation: str | None = None
) -> AlertExplanation:
    """Explain why one student was flagged, from the signals that scored them.

    Only the signals in computation.signals_available are named: the classroom
    already drops the ones a student has not consented to, so an explanation
    can never mention a camera or microphone signal that was not collected.
    """
    used = [SIGNAL_LABELS.get(name, name) for name in computation.signals_available]
    missing = [
        label for name, label in SIGNAL_LABELS.items() if name not in computation.signals_available
    ]
    total = len(SIGNAL_LABELS)
    count = len(used)
    confidence = max(0.0, min(1.0, computation.confidence))

    reasons: list[str] = [
        f"{count} of {total} engagement signals were available"
        + (f": {', '.join(used)}." if used else ".")
    ]
    if missing:
        reasons.append(f"Not available: {', '.join(missing)}.")
    if count < 3:
        reasons.append("With so few signals, treat this as an early indication, not a finding.")

    if computation.score is None or computation.status is EngagementStatus.INSUFFICIENT_DATA:
        reason = "There is not enough evidence yet to say how engaged this student is."
        recommendation = (
            "No action needed yet: wait for more of this student's answers before drawing "
            "any conclusion."
        )
        fallback = reason
    else:
        status = computation.status.value.replace("_", " ")
        reason = f"Engagement score {_percent(computation.score)}% ({status}) from {count} signals."
        fallback = (
            f"{reason} A low score reflects participation the server observed, "
            "such as questions attempted and answer timing. It is not a judgement of the student."
        )
        if computation.status is EngagementStatus.ENGAGED:
            recommendation = "No action needed: this student is taking part as expected."
        else:
            recommendation = (
                "Check in privately and ask whether they need help. Do not single the "
                "student out in front of the class: a low score is not proof of disengagement."
            )

    shown = safe_display_text(model_explanation, limit=MAX_EXPLANATION_CHARS)
    return AlertExplanation(
        message="A student may be disengaging.",
        reason=reason,
        explanation=shown or fallback,
        explanation_source="ai" if shown else "fallback",
        confidence=confidence,
        confidence_reasons=tuple(reasons),
        recommendation=recommendation,
    )


def fallback_explanation(kind: AlertKind, message: str | None = None) -> AlertExplanation:
    """The explanation for an alert nothing else could explain.

    Used when building the real one fails, and for any kind added later before
    its own explainer exists: a new AlertKind is covered by the generic branch,
    so an alert can never go out without a reason and a recommendation.
    """
    generic_reason = "The system flagged this automatically, but could not produce the detail."
    generic_explanation = (
        "This alert was raised automatically. The detail behind it was not available, "
        "so treat it as a prompt to look, not as a finding."
    )
    text = {
        AlertKind.TOPIC_DIFFICULTY: (
            "Much of the class may be struggling with the last question.",
            "Ask a quick follow-up question to see whether the class understood it.",
        ),
        AlertKind.STUDENT_DISENGAGEMENT: (
            "A student may be disengaging.",
            "Check in privately with the student, and use your own judgement.",
        ),
        AlertKind.BREAKOUT_INACTIVE: (
            "A breakout room may be inactive.",
            "Look in on the room to see whether the group needs help.",
        ),
    }
    default_message, recommendation = text.get(
        kind,
        ("Something needs your attention.", "Look into this and use your own judgement."),
    )
    return AlertExplanation(
        message=message or default_message,
        reason=generic_reason,
        explanation=generic_explanation,
        explanation_source="fallback",
        confidence=0.0,
        confidence_reasons=("No confidence information was available for this alert.",),
        recommendation=recommendation,
    )
