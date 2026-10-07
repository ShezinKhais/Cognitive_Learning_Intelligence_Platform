"""Reads a session's labelled answers for topic difficulty.

Owner: AI 1, Phase 5 (#55). Read-only: BBIS owns student_response and
question, and AI 1 writes comprehension_result. This only gathers what they
have recorded.
"""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import select

from app.core.database import get_session_factory
from app.models.comprehension_result import ComprehensionResult
from app.models.question import Question
from app.models.student_response import StudentResponse
from app.services.topic_difficulty import LabelledAnswer, TopicDifficulty, topic_difficulty


class DatabaseTopicAnswers:
    async def session_answers(self, session_id: UUID) -> list[LabelledAnswer]:
        """Every labelled answer in a session, oldest label first."""
        async with get_session_factory()() as db:
            rows = await db.execute(
                select(
                    StudentResponse.student_id,
                    StudentResponse.question_id,
                    Question.topic,
                    Question.difficulty,
                    ComprehensionResult.label,
                    ComprehensionResult.confidence_score,
                )
                .join(
                    ComprehensionResult,
                    ComprehensionResult.response_id == StudentResponse.response_id,
                )
                .join(Question, Question.question_id == StudentResponse.question_id)
                .where(StudentResponse.session_id == session_id)
                .order_by(ComprehensionResult.created_at)
            )
            return [
                LabelledAnswer(
                    student_id=student_id,
                    question_id=question_id,
                    topic=topic,
                    label=label,
                    confidence=confidence,
                    question_difficulty=difficulty,
                )
                for student_id, question_id, topic, difficulty, label, confidence in rows.all()
            ]

    async def session_topics(self, session_id: UUID) -> list[TopicDifficulty]:
        """The session's topics, hardest first."""
        return topic_difficulty(await self.session_answers(session_id))
