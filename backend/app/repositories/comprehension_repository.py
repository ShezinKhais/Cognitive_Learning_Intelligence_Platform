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
from app.realtime.recorders import QuestionComprehension


class DatabaseComprehensionSource:
    """The latest label per student for one question in one session."""

    async def question_labels(self, session_id: UUID, question_id: UUID) -> QuestionComprehension:
        async with get_session_factory()() as db:
            rows = await db.execute(
                select(
                    StudentResponse.student_id,
                    ComprehensionResult.label,
                    ComprehensionResult.confidence_score,
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
            latest = {
                student_id: (label, confidence) for student_id, label, confidence in rows.all()
            }
            question = (
                await db.execute(
                    select(Question.topic, Question.source_slide).where(
                        Question.question_id == question_id
                    )
                )
            ).one_or_none()
        topic, source_slide = (question.topic, question.source_slide) if question else (None, None)
        return QuestionComprehension(
            labels=[label for label, _ in latest.values()],
            topic=topic,
            confidences=[confidence for _, confidence in latest.values()],
            source_slide=source_slide,
        )
