"""Recheck closed questions after their asynchronous classifications commit.

The delivery row serializes competing close/classification callbacks. Checking
and storing the alert in that transaction prevents duplicate alerts, including
after a process restart. Never alert on a question whose window is still open.
"""

from datetime import UTC, datetime
from uuid import UUID, uuid4

from sqlalchemy import select

from app.core.config import get_settings
from app.core.database import get_session_factory
from app.models.ai_alert import AIAlert
from app.models.delivered_question import DeliveredQuestion
from app.repositories.alert_repository import save_alert
from app.repositories.comprehension_repository import DatabaseComprehensionSource
from app.schemas.events import AlertKind
from app.schemas.session import ClassComprehensionAlert
from app.services.ai_explainability import (
    TopicEvidence,
    explain_topic_difficulty,
    fallback_explanation,
)
from app.services.alert_store import alert_details
from app.services.engagement import evaluate_comprehension_alert


async def refresh(session_id: UUID, question_id: UUID) -> ClassComprehensionAlert | None:
    async with get_session_factory()() as db:
        delivery = await db.scalar(
            select(DeliveredQuestion)
            .where(
                DeliveredQuestion.session_id == session_id,
                DeliveredQuestion.question_id == question_id,
            )
            .with_for_update()
        )
        if delivery is None or delivery.closed_at is None:
            return None
        existing = await db.scalar(
            select(AIAlert.alert_id).where(
                AIAlert.session_id == session_id,
                AIAlert.question_id == question_id,
                AIAlert.kind == AlertKind.TOPIC_DIFFICULTY.value,
            )
        )
        if existing is not None:
            return None
        found = await DatabaseComprehensionSource().read_labels(db, session_id, question_id)
        settings = get_settings()
        decision = evaluate_comprehension_alert(
            found.labels,
            min_respondents=settings.comprehension_alert_min_respondents,
            threshold=settings.comprehension_alert_threshold,
        )
        if not decision.should_alert or decision.correct_ratio is None:
            return None
        try:
            explained = explain_topic_difficulty(
                TopicEvidence(
                    labels=found.labels,
                    eligible=delivery.eligible_count,
                    min_respondents=settings.comprehension_alert_min_respondents,
                    threshold=settings.comprehension_alert_threshold,
                    confidences=found.confidences,
                    topic=found.topic,
                    source_slide=found.source_slide,
                )
            )
        except Exception:
            explained = fallback_explanation(AlertKind.TOPIC_DIFFICULTY)
        alert = ClassComprehensionAlert(
            alert_id=uuid4(),
            session_id=session_id,
            question_id=question_id,
            raised_at=datetime.now(UTC),
            topic=found.topic,
            correct_ratio=decision.correct_ratio,
            respondents=decision.respondents,
            threshold=settings.comprehension_alert_threshold,
            message=explained.message,
            reason=explained.reason,
            confidence=explained.confidence,
            explanation=explained.explanation,
            explanation_source=explained.explanation_source,
            confidence_reasons=list(explained.confidence_reasons),
            recommendation=explained.recommendation,
        )
        await save_alert(
            db,
            alert_id=alert.alert_id,
            session_id=session_id,
            question_id=question_id,
            kind=AlertKind.TOPIC_DIFFICULTY.value,
            topic=alert.topic,
            message=alert.message,
            reason=alert.reason,
            confidence=alert.confidence,
            explanation=alert.explanation,
            explanation_source=alert.explanation_source,
            confidence_reasons=alert.confidence_reasons,
            recommendation=alert.recommendation,
            details=alert_details(alert),
        )
        await db.commit()
        return alert
