"""Reads AI 1's comprehension classifications for the class comprehension
alert.

Owner: Cyber 1, Phase 3. Read-only: AI 1 writes comprehension_result, BBIS
owns student_response. This only counts what they have recorded.
"""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import select

from app.core.database import get_session_factory
from app.models.comprehension_result import ComprehensionResult
from app.models.question import Question
from app.models.student_response import StudentResponse
from app.realtime.classroom import QuestionComprehension


class DatabaseComprehensionSource:
    """The latest label per student for one question in one session."""

    async def question_labels(self, session_id: UUID, question_id: UUID) -> QuestionComprehension:
        async with get_session_factory()() as db:
            rows = await db.execute(
                select(
                    StudentResponse.student_id,
                    ComprehensionResult.label,
                )
                .join(
                    ComprehensionResult,
                    ComprehensionResult.response_id == StudentResponse.response_id,
                )
                .where(
                    StudentResponse.session_id == session_id,
                    StudentResponse.question_id == question_id,
                )
                .order_by(ComprehensionResult.created_at)
            )
            # A reclassified answer counts once, by its newest label.
            latest = {student_id: label for student_id, label in rows.all()}
            topic = await db.scalar(
                select(Question.topic).where(Question.question_id == question_id)
            )
        return QuestionComprehension(labels=list(latest.values()), topic=topic)
