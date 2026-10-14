"""A student's summary of one session, built from stored values only.

Owner: Cyber 1, Phase 7. Everything in it is counted or read from what the
session stored (responses, missed questions, comprehension labels); nothing is
written by a model, so there is no sentence in it that could invent a fact.
Every action item is a fixed template filled with a counted number or a topic
name that passed text screening.

What it will not do (see report_validation.py for the checks):

* Engagement is reported only for a student who has consented to engagement
  monitoring, and from the running class's scores only. Otherwise it reads
  "insufficient data" with no signals, not zero.
* Engagement never produces an action item.
* A topic is labelled only when at least one of the student's answers on it was
  classified with enough confidence; a topic whose every label is uncertain is
  left out rather than reported as a weakness.
* A topic name that carries an instruction or markup is left out.
"""

from __future__ import annotations

import logging
from collections import defaultdict
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.audit_log import AuditLog
from app.models.delivered_question import DeliveredQuestion
from app.models.missed_response import MissedResponse
from app.models.student_response import StudentResponse
from app.realtime.classroom import classroom
from app.repositories.topic_difficulty_repository import DatabaseTopicAnswers
from app.schemas.session import (
    ActionItem,
    ComprehensionLabel,
    EngagementOut,
    EngagementStatus,
    StudentSessionSummary,
)
from app.services.engagement_view import staff_confidence, staff_score, staff_signals
from app.services.report_validation import MAX_ACTION_ITEMS, summary_problems, topic_name_problems
from app.services.text_screening import safe_display_text
from app.services.topic_difficulty import (
    EASY_BELOW,
    HARD_FROM,
    LABEL_WEIGHT,
    NO_TOPIC,
    UNCERTAIN_BELOW,
    LabelledAnswer,
    latest_answers,
    topic_key,
)

log = logging.getLogger("clip.student_report")

MAX_TOPIC_NAME_LENGTH = 80


def topic_labels(answers: list[LabelledAnswer]) -> dict[str, ComprehensionLabel]:
    """One label per topic from a student's own answers: their average, read on
    the same thirds as the class's topic difficulty. Every classified answer
    counts, uncertain or not, exactly as topic_difficulty and AI 1's student
    summary count them, so the same student reads the same label everywhere.
    How sure the classifier was is kept apart (confident_topics) and decides
    only what the report *suggests*, not what it says happened."""
    names: dict[str, str] = {}
    weights: dict[str, list[float]] = defaultdict(list)
    for answer in latest_answers(answers):
        if answer.label not in LABEL_WEIGHT:
            continue
        key = topic_key(answer.topic)
        if key not in names:
            shown = (
                NO_TOPIC
                if not key
                else safe_display_text(answer.topic, limit=MAX_TOPIC_NAME_LENGTH)
            )
            if shown is None:
                continue  # unsafe name: not shown
            names[key] = shown
        weights[key].append(LABEL_WEIGHT[answer.label])
    labels: dict[str, ComprehensionLabel] = {}
    for key, values in weights.items():
        mean = sum(values) / len(values)
        if mean < EASY_BELOW:
            label = ComprehensionLabel.MASTERED
        elif mean >= HARD_FROM:
            label = ComprehensionLabel.STRUGGLING
        else:
            label = ComprehensionLabel.PARTIAL
        labels[names[key]] = label
    return labels


def confident_topics(answers: list[LabelledAnswer]) -> set[str]:
    """The (safely shown) topics where at least one of the student's answers was
    classified with enough confidence to act on."""
    found: set[str] = set()
    for answer in latest_answers(answers):
        if answer.label in LABEL_WEIGHT and answer.confidence >= UNCERTAIN_BELOW:
            key = topic_key(answer.topic)
            shown = (
                NO_TOPIC
                if not key
                else safe_display_text(answer.topic, limit=MAX_TOPIC_NAME_LENGTH)
            )
            if shown is not None:
                found.add(shown)
    return found


def action_items(
    labels: dict[str, ComprehensionLabel],
    missed: int,
    confident: set[str] | None = None,
) -> list[ActionItem]:
    """Next steps from comprehension and missed questions, and nothing else.

    Topics the student is struggling with first, then partial ones, then missed
    questions; at most MAX_ACTION_ITEMS. A topic is only suggested for review
    when the classifier was sure of at least one answer on it (confident=None
    means every topic): an uncertain label is reported, not acted on.
    """
    items: list[ActionItem] = []
    for wanted, text in (
        (
            ComprehensionLabel.STRUGGLING,
            "Revisit {topic}: your answers show the main ideas are not secure yet.",
        ),
        (
            ComprehensionLabel.PARTIAL,
            "Practise {topic}: you have part of it and a little more work would complete it.",
        ),
    ):
        for topic, label in sorted(labels.items()):
            if label is wanted and (confident is None or topic in confident):
                items.append(
                    ActionItem(kind="revisit_topic", text=text.format(topic=topic), topic=topic)
                )
    if missed > 0:
        noun = "question was" if missed == 1 else "questions were"
        items.append(
            ActionItem(
                kind="review_missed",
                text=f"{missed} {noun} not answered in class; try again from your review.",
            )
        )
    return items[:MAX_ACTION_ITEMS]


async def _counts(db: AsyncSession, session_id: UUID, student_id: UUID) -> tuple[int, int]:
    attempted = await db.scalar(
        select(func.count(func.distinct(StudentResponse.question_id))).where(
            StudentResponse.session_id == session_id, StudentResponse.student_id == student_id
        )
    )
    missed = await db.scalar(
        select(func.count(MissedResponse.missed_response_id))
        .join(DeliveredQuestion, DeliveredQuestion.delivery_id == MissedResponse.delivery_id)
        .where(DeliveredQuestion.session_id == session_id, MissedResponse.student_id == student_id)
    )
    return int(attempted or 0), int(missed or 0)


def no_engagement(session_id: UUID, student_id: UUID) -> EngagementOut:
    return EngagementOut(
        student_id=student_id,
        session_id=session_id,
        score=None,
        status=EngagementStatus.INSUFFICIENT_DATA,
        confidence=0.0,
        signals_available=[],
        computed_at=datetime.now(UTC),
    )


def engagement_of(
    session_id: UUID, student_id: UUID, user_id: UUID, *, may_report: bool
) -> EngagementOut:
    """The student's latest engagement score, if they have consented to it and
    this process is running the class; otherwise 'insufficient data'."""
    if may_report:
        for scored in classroom.engagement(session_id):
            if scored.user_id == user_id:
                return EngagementOut(
                    student_id=student_id,
                    session_id=session_id,
                    score=staff_score(scored.engagement.score),
                    status=scored.engagement.status,
                    # The same view staff get on /engagement, for every student:
                    # see engagement_view.py.
                    confidence=staff_confidence(scored.engagement.signals_available),
                    signals_available=staff_signals(scored.engagement.signals_available),
                    computed_at=scored.scored_at,
                )
    return no_engagement(session_id, student_id)


SUMMARY_VIEWED_ACTION = "STUDENT_SUMMARY_VIEWED"


async def record_staff_view(
    db: AsyncSession, *, viewer: UUID, student_id: UUID, session_id: UUID, ip_address: str
) -> None:
    """Note that staff read a student's summary. Reading someone else's results
    leaves a trace; reading your own does not need one.

    The log line names the student and session; the audit row (which has no
    column for them yet) records who looked and when. Failing to write the row
    never blocks the read, and never hides the log line.
    """
    log.info(
        "security_event=%s viewer=%s student=%s session=%s",
        SUMMARY_VIEWED_ACTION,
        viewer,
        student_id,
        session_id,
    )
    try:
        db.add(AuditLog(user_id=viewer, action_type=SUMMARY_VIEWED_ACTION, ip_address=ip_address))
        await db.commit()
    except Exception:
        await db.rollback()
        log.warning("could not write the audit row for a student summary view")


async def build_student_summary(
    db: AsyncSession,
    session_id: UUID,
    student_id: UUID,
    user_id: UUID,
    *,
    engagement_consented: bool,
) -> StudentSessionSummary:
    """The summary, checked before it leaves. A summary that fails its checks is
    rebuilt without its action items and engagement; if it still fails, nothing
    is returned."""
    attempted, missed = await _counts(db, session_id, student_id)
    answers = [
        a
        for a in await DatabaseTopicAnswers(db).session_answers(session_id)
        if a.student_id == student_id
    ]
    labels = topic_labels(answers)
    summary = StudentSessionSummary(
        student_id=student_id,
        session_id=session_id,
        questions_attempted=attempted,
        questions_missed=missed,
        engagement=engagement_of(session_id, student_id, user_id, may_report=engagement_consented),
        comprehension_by_topic=labels,
        action_items=action_items(labels, missed, confident_topics(answers)),
    )
    problems = summary_problems(summary, session_id=session_id, student_id=student_id)
    if problems:
        log.error("a student summary failed its checks and was reduced: %s", "; ".join(problems))
        summary = summary.model_copy(
            update={
                "comprehension_by_topic": {
                    t: label
                    for t, label in summary.comprehension_by_topic.items()
                    if not topic_name_problems(t)
                },
                "action_items": [],
                "engagement": no_engagement(session_id, student_id),
            }
        )
        if summary_problems(summary, session_id=session_id, student_id=student_id):
            raise ValueError("a student summary could not be made to meet the report rules")
    return summary
