"""Stores the AI alerts raised to the lecturer, and their acknowledgement.

Owner: BBIS, Phase 5. Each function works inside the caller's transaction.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.ai_alert import AIAlert


async def save_alert(
    db: AsyncSession,
    *,
    session_id: UUID,
    kind: str,
    message: str,
    reason: str,
    confidence: float,
    question_id: UUID | None = None,
    student_id: UUID | None = None,
    topic: str | None = None,
    model_name: str | None = None,
    prompt_version: str | None = None,
    details: dict[str, Any] | None = None,
    alert_id: UUID | None = None,
) -> AIAlert:
    """Add an alert to the caller's transaction.

    Pass the id already sent to the lecturer's screen as alert_id, so the
    stored alert is the one they see and can acknowledge.
    """
    alert = AIAlert(
        session_id=session_id,
        question_id=question_id,
        student_id=student_id,
        kind=kind,
        topic=topic,
        message=message,
        reason=reason,
        confidence=confidence,
        model_name=model_name,
        prompt_version=prompt_version,
        details=details or {},
    )
    if alert_id is not None:
        alert.alert_id = alert_id
    db.add(alert)
    await db.flush()
    return alert


async def acknowledge_alert(db: AsyncSession, alert_id: UUID, user_id: UUID) -> AIAlert | None:
    """Mark an alert acknowledged by a lecturer, and return it.

    An alert already acknowledged keeps its first acknowledgement, so a second
    click or a second lecturer does not overwrite who saw it first. Returns
    None when there is no such alert.
    """
    await db.execute(
        update(AIAlert)
        .where(AIAlert.alert_id == alert_id, AIAlert.status == "open")
        .values(status="acknowledged", acknowledged_by=user_id, acknowledged_at=func.now())
    )
    return await db.scalar(
        select(AIAlert)
        .where(AIAlert.alert_id == alert_id)
        .execution_options(populate_existing=True)
    )


async def list_alerts(
    db: AsyncSession, session_id: UUID, *, status: str | None = None
) -> list[AIAlert]:
    """A session's alerts, oldest first, optionally only the open ones."""
    query = select(AIAlert).where(AIAlert.session_id == session_id)
    if status is not None:
        query = query.where(AIAlert.status == status)
    rows = await db.scalars(query.order_by(AIAlert.raised_at, AIAlert.alert_id))
    return list(rows)
