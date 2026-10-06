"""Stores the AI recommendations shown to the lecturer, and their acknowledgement.

Owner: BBIS, Phase 5. Each function works inside the caller's transaction.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.ai_recommendation import AIRecommendation


async def save_recommendation(
    db: AsyncSession,
    *,
    session_id: UUID,
    recommendation: str,
    reason: str,
    confidence: float,
    alert_id: UUID | None = None,
    question_id: UUID | None = None,
    student_id: UUID | None = None,
    topic: str | None = None,
    sources: list[dict[str, Any]] | None = None,
    used_fallback: bool = False,
    model_name: str | None = None,
    prompt_version: str | None = None,
) -> AIRecommendation:
    """Add a recommendation to the caller's transaction.

    sources are the slides it cites, for example {"slide": 4, "excerpt": "..."}.
    Set used_fallback when the safe fallback text was shown instead of a
    model's answer.
    """
    row = AIRecommendation(
        session_id=session_id,
        alert_id=alert_id,
        question_id=question_id,
        student_id=student_id,
        topic=topic,
        recommendation=recommendation,
        reason=reason,
        confidence=confidence,
        sources=sources or [],
        used_fallback=used_fallback,
        model_name=model_name,
        prompt_version=prompt_version,
    )
    db.add(row)
    await db.flush()
    return row


async def acknowledge_recommendation(
    db: AsyncSession, recommendation_id: UUID, user_id: UUID
) -> AIRecommendation | None:
    """Mark a recommendation acknowledged by a lecturer, and return it.

    One already acknowledged keeps its first acknowledgement. Returns None
    when there is no such recommendation.
    """
    await db.execute(
        update(AIRecommendation)
        .where(
            AIRecommendation.recommendation_id == recommendation_id,
            AIRecommendation.status == "open",
        )
        .values(status="acknowledged", acknowledged_by=user_id, acknowledged_at=func.now())
    )
    return await db.scalar(
        select(AIRecommendation)
        .where(AIRecommendation.recommendation_id == recommendation_id)
        .execution_options(populate_existing=True)
    )


async def list_recommendations(
    db: AsyncSession, session_id: UUID, *, status: str | None = None
) -> list[AIRecommendation]:
    """A session's recommendations, oldest first, optionally only the open ones."""
    query = select(AIRecommendation).where(AIRecommendation.session_id == session_id)
    if status is not None:
        query = query.where(AIRecommendation.status == status)
    rows = await db.scalars(
        query.order_by(AIRecommendation.created_at, AIRecommendation.recommendation_id)
    )
    return list(rows)
