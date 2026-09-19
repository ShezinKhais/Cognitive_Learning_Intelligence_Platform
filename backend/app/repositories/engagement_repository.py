"""Database queries for engagement records and dynamic attention prompts.

Owner: BBIS, Phase 3. Scoring itself (app.services.engagement) is Cyber 1's;
this only stores what scoring decides, for the `/sessions/{id}/engagement`
dashboard query and for the per-student prompt cap.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.dynamic_prompt import DynamicPrompt
from app.models.engagement_record import EngagementRecord


class EngagementRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def record(
        self,
        *,
        session_id: uuid.UUID,
        student_id: uuid.UUID,
        attempt_rate: float,
        attention_signal: str,
        engagement_score: float | None,
        status: str,
        confidence: float,
        signals_available: str,
    ) -> EngagementRecord:
        row = EngagementRecord(
            session_id=session_id,
            student_id=student_id,
            status=status,
            confidence=confidence,
            signals_available=signals_available,
            attempt_rate=attempt_rate,
            attention_signal=attention_signal,
            engagement_score=engagement_score,
        )
        self.session.add(row)
        await self.session.flush()
        await self.session.refresh(row)
        return row

    async def latest_for_session(self, session_id: uuid.UUID) -> list[EngagementRecord]:
        """The most recent record per student in the session, for the
        lecturer's dashboard. Postgres's DISTINCT ON keeps this to one query
        instead of one per student."""
        result = await self.session.execute(
            select(EngagementRecord)
            .distinct(EngagementRecord.student_id)
            .where(EngagementRecord.session_id == session_id)
            .order_by(EngagementRecord.student_id, EngagementRecord.timestamp.desc())
        )
        return list(result.scalars().all())

    async def latest_for_student(
        self, session_id: uuid.UUID, student_id: uuid.UUID
    ) -> EngagementRecord | None:
        result = await self.session.execute(
            select(EngagementRecord)
            .where(
                EngagementRecord.session_id == session_id,
                EngagementRecord.student_id == student_id,
            )
            .order_by(EngagementRecord.timestamp.desc())
            .limit(1)
        )
        return result.scalar_one_or_none()

    # --- Dynamic prompts ----------------------------------------------------

    async def record_prompt(
        self,
        *,
        session_id: uuid.UUID,
        student_id: uuid.UUID,
        prompt_text: str,
        trigger_reason: str,
    ) -> DynamicPrompt:
        row = DynamicPrompt(
            session_id=session_id,
            student_id=student_id,
            prompt_text=prompt_text,
            trigger_reason=trigger_reason,
            response_status="sent",
        )
        self.session.add(row)
        await self.session.flush()
        await self.session.refresh(row)
        return row

    async def count_prompts(self, session_id: uuid.UUID, student_id: uuid.UUID) -> int:
        result = await self.session.execute(
            select(func.count())
            .select_from(DynamicPrompt)
            .where(
                DynamicPrompt.session_id == session_id,
                DynamicPrompt.student_id == student_id,
            )
        )
        return result.scalar_one()

    async def acknowledge_prompt(
        self, prompt_id: uuid.UUID, *, dismissed: bool
    ) -> DynamicPrompt | None:
        row = await self.session.get(DynamicPrompt, prompt_id)
        if row is None:
            return None
        row.response_status = "dismissed" if dismissed else "acknowledged"
        self.session.add(row)
        await self.session.flush()
        await self.session.refresh(row)
        return row

    async def get_prompt(self, prompt_id: uuid.UUID) -> DynamicPrompt | None:
        return await self.session.get(DynamicPrompt, prompt_id)

    async def expire_stale_prompts(self, session_id: uuid.UUID, *, max_age_seconds: int) -> None:
        """Mark prompts nobody acknowledged as timed out.

        Keeps `response_status` meaningful for the dashboard instead of
        leaving old prompts stuck at "sent" forever once a student never
        opens the nudge at all.
        """
        cutoff = datetime.now(UTC).timestamp() - max_age_seconds
        result = await self.session.execute(
            select(DynamicPrompt).where(
                DynamicPrompt.session_id == session_id,
                DynamicPrompt.response_status == "sent",
            )
        )
        for row in result.scalars().all():
            if row.sent_at.timestamp() < cutoff:
                row.response_status = "timed_out"
                self.session.add(row)
        await self.session.flush()
