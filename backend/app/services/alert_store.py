"""Keeps the alerts raised to the lecturer, and serves them back.

Owner: Cyber 1, Phase 5. BBIS's ai_alert table and alert_repository.py do the
storing. This maps a live alert onto that table and back, and puts the access
rules in front of the two things a lecturer does with a stored alert: read them
and acknowledge one.

What is kept is the alert the lecturer was shown, under the id they were shown
it with, so the alert on their screen is the one they acknowledge. The reason,
explanation, recommendation and confidence reasons (see ai_explainability.py)
go in the row's details beside the figures, so a page reloaded in the middle of
a class, or opened after it, shows what was shown live.

Reading never fails on an unexpected row, and never returns one with nothing to
read: any field missing or blank in a stored alert is replaced with the fallback
explanation for its kind. An alert written by other code, or by an older version
of this one, still has a reason, an explanation and a recommendation.
"""

from __future__ import annotations

import logging
from typing import Any, Literal, cast
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_session_factory
from app.core.errors import NotFoundError
from app.models.ai_alert import AIAlert
from app.repositories import alert_repository
from app.schemas.events import AlertKind
from app.schemas.session import AlertOut, ClassComprehensionAlert
from app.services.ai_explainability import fallback_explanation

log = logging.getLogger("clip.alerts")

AlertStatus = Literal["open", "acknowledged"]
_STATUSES = ("open", "acknowledged")


def alert_details(alert: ClassComprehensionAlert) -> dict[str, Any]:
    """What goes in the stored row's details: the figures the alert rests on,
    and everything the lecturer was shown beyond the headline and the reason."""
    return {
        "respondents": alert.respondents,
        "threshold": alert.threshold,
        "correct_ratio": alert.correct_ratio,
        "explanation": alert.explanation,
        "explanation_source": alert.explanation_source,
        "confidence_reasons": list(alert.confidence_reasons),
        "recommendation": alert.recommendation,
    }


async def store_comprehension_alert(alert: ClassComprehensionAlert) -> None:
    """Keep one class comprehension alert, in a transaction of its own.

    The classroom calls this concurrently with everything else it records, so
    it opens its own session, as live_wiring's other stores do.
    """
    async with get_session_factory()() as db:
        await alert_repository.save_alert(
            db,
            alert_id=alert.alert_id,
            session_id=alert.session_id,
            question_id=alert.question_id,
            kind=AlertKind.TOPIC_DIFFICULTY.value,
            topic=alert.topic,
            message=alert.message,
            reason=alert.reason,
            confidence=alert.confidence,
            details=alert_details(alert),
        )
        await db.commit()


def _text(value: object) -> str | None:
    """A stored string that has something in it, trimmed, or None."""
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None


def _number(value: object, kind: type) -> Any:
    """A stored figure of the right type, or None. A bool is not a number."""
    if isinstance(value, bool) or not isinstance(value, int | float):
        return None
    return int(value) if kind is int else float(value)


def alert_from_row(row: AIAlert) -> AlertOut:
    """A stored alert as the lecturer is shown it. Never raises, never blank."""
    details: dict[str, Any] = row.details if isinstance(row.details, dict) else {}
    fallback = fallback_explanation(cast(AlertKind, row.kind))

    reasons = details.get("confidence_reasons")
    confidence_reasons = [t for t in (reasons if isinstance(reasons, list) else []) if _text(t)]
    source = details.get("explanation_source")
    status = row.status if row.status in _STATUSES else "open"

    return AlertOut(
        alert_id=row.alert_id,
        session_id=row.session_id,
        question_id=row.question_id,
        kind=row.kind,
        topic=_text(row.topic),
        message=_text(row.message) or fallback.message,
        reason=_text(row.reason) or fallback.reason,
        confidence=max(0.0, min(1.0, row.confidence)),
        explanation=_text(details.get("explanation")) or fallback.explanation,
        explanation_source=cast(
            Literal["ai", "fallback"], source if source in ("ai", "fallback") else "fallback"
        ),
        confidence_reasons=[t.strip() for t in confidence_reasons]
        or list(fallback.confidence_reasons),
        recommendation=_text(details.get("recommendation")) or fallback.recommendation,
        status=cast(AlertStatus, status),
        raised_at=row.raised_at,
        acknowledged_by=row.acknowledged_by,
        acknowledged_at=row.acknowledged_at,
        respondents=_number(details.get("respondents"), int),
        threshold=_number(details.get("threshold"), float),
        correct_ratio=_number(details.get("correct_ratio"), float),
    )


async def list_session_alerts(
    db: AsyncSession, session_id: UUID, *, status: AlertStatus | None = None
) -> list[AlertOut]:
    """A session's stored alerts, oldest first, optionally only one status."""
    rows = await alert_repository.list_alerts(db, session_id, status=status)
    return [alert_from_row(row) for row in rows]


async def acknowledge_session_alert(
    db: AsyncSession, session_id: UUID, alert_id: UUID, user_id: UUID
) -> AlertOut:
    """Mark a session's alert as seen by this lecturer.

    The alert is looked up by its id *and* the session in the route, so an alert
    id from another class cannot be acknowledged through one's own. A missing
    alert and another session's are the same refusal. An alert already
    acknowledged keeps its first acknowledgement and is returned as it is, so a
    second click, or a second lecturer, changes nothing.

    The caller has already checked that this user may see the session.
    """
    owned = await db.scalar(
        select(AIAlert.alert_id).where(
            AIAlert.alert_id == alert_id, AIAlert.session_id == session_id
        )
    )
    if owned is None:
        raise NotFoundError("Alert was not found.", {"alert_id": str(alert_id)})
    row = await alert_repository.acknowledge_alert(db, alert_id, user_id)
    if row is None:  # deleted between the two statements
        raise NotFoundError("Alert was not found.", {"alert_id": str(alert_id)})
    await db.commit()
    log.info("alert %s acknowledged by %s (now %s)", alert_id, user_id, row.acknowledged_by)
    return alert_from_row(row)
