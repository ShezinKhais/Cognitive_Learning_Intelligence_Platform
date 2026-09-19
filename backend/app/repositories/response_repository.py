"""Database queries for student responses and missed responses.

Owner: BBIS, Phase 3.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.missed_response import MissedResponse
from app.models.student_response import StudentResponse


class ResponseRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_for_question(
        self, session_id: uuid.UUID, question_id: uuid.UUID, student_id: uuid.UUID
    ) -> StudentResponse | None:
        result = await self.session.execute(
            select(StudentResponse).where(
                StudentResponse.session_id == session_id,
                StudentResponse.question_id == question_id,
                StudentResponse.student_id == student_id,
            )
        )
        return result.scalar_one_or_none()

    async def record(
        self,
        *,
        session_id: uuid.UUID,
        question_id: uuid.UUID,
        student_id: uuid.UUID,
        selected_option: int | None,
        free_text: str | None,
        elapsed_ms: int,
        is_correct: bool | None,
    ) -> StudentResponse:
        row = StudentResponse(
            session_id=session_id,
            question_id=question_id,
            student_id=student_id,
            selected_option=selected_option,
            free_text=free_text,
            elapsed_ms=elapsed_ms,
            is_correct=is_correct,
        )
        self.session.add(row)
        await self.session.flush()
        await self.session.refresh(row)
        return row

    async def respondent_count(self, session_id: uuid.UUID, question_id: uuid.UUID) -> int:
        result = await self.session.execute(
            select(func.count())
            .select_from(StudentResponse)
            .where(
                StudentResponse.session_id == session_id,
                StudentResponse.question_id == question_id,
            )
        )
        return result.scalar_one()

    async def correct_count(self, session_id: uuid.UUID, question_id: uuid.UUID) -> int:
        result = await self.session.execute(
            select(func.count())
            .select_from(StudentResponse)
            .where(
                StudentResponse.session_id == session_id,
                StudentResponse.question_id == question_id,
                StudentResponse.is_correct.is_(True),
            )
        )
        return result.scalar_one()

    async def responded_student_ids(
        self, session_id: uuid.UUID, question_id: uuid.UUID
    ) -> set[uuid.UUID]:
        result = await self.session.execute(
            select(StudentResponse.student_id).where(
                StudentResponse.session_id == session_id,
                StudentResponse.question_id == question_id,
            )
        )
        return set(result.scalars().all())

    async def list_page(
        self, session_id: uuid.UUID, *, limit: int, offset: int
    ) -> tuple[list[StudentResponse], int]:
        total = (
            await self.session.execute(
                select(func.count())
                .select_from(StudentResponse)
                .where(StudentResponse.session_id == session_id)
            )
        ).scalar_one()

        result = await self.session.execute(
            select(StudentResponse)
            .where(StudentResponse.session_id == session_id)
            .order_by(StudentResponse.timestamp)
            .limit(limit)
            .offset(offset)
        )
        return list(result.scalars().all()), total

    async def count_attempted(self, session_id: uuid.UUID, student_id: uuid.UUID) -> int:
        result = await self.session.execute(
            select(func.count())
            .select_from(StudentResponse)
            .where(
                StudentResponse.session_id == session_id,
                StudentResponse.student_id == student_id,
            )
        )
        return result.scalar_one()

    async def record_missed(
        self, session_id: uuid.UUID, question_id: uuid.UUID, student_ids: set[uuid.UUID]
    ) -> None:
        for student_id in student_ids:
            self.session.add(
                MissedResponse(
                    session_id=session_id,
                    question_id=question_id,
                    student_id=student_id,
                    recorded_at=datetime.now(UTC),
                )
            )
        if student_ids:
            await self.session.flush()

    async def count_missed(self, session_id: uuid.UUID, student_id: uuid.UUID) -> int:
        result = await self.session.execute(
            select(func.count())
            .select_from(MissedResponse)
            .where(
                MissedResponse.session_id == session_id,
                MissedResponse.student_id == student_id,
            )
        )
        return result.scalar_one()
