"""What the lecturer is told at a glance in Teams, read from what the class
stored: a checkpoint's most common wrong answer, and the class's summary when
it ends. Counts and course content only, never a student's name."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_session_factory
from app.models.delivered_question import DeliveredQuestion
from app.models.question import Question
from app.models.session import Session
from app.models.student_response import StudentResponse
from app.repositories.topic_difficulty_repository import DatabaseTopicAnswers
from app.services import attendance

OPTION_CHARS = 40


def _short(text: str) -> str:
    text = " ".join(text.split())
    return text if len(text) <= OPTION_CHARS else text[: OPTION_CHARS - 3].rstrip() + "..."


async def checkpoint_detail(session_id: UUID, question_id: UUID) -> str | None:
    """ "11 right. Most common wrong answer: B, heaps are sorted (6)." for a
    multiple-choice checkpoint; None for a written one or no answers."""
    async with get_session_factory()() as db:
        question = await db.get(Question, question_id)
        if question is None or not question.options or question.correct_option is None:
            return None
        rows = await db.execute(
            select(StudentResponse.selected_option, func.count())
            .where(
                StudentResponse.session_id == session_id,
                StudentResponse.question_id == question_id,
                StudentResponse.selected_option.is_not(None),
            )
            .group_by(StudentResponse.selected_option)
        )
        counts = dict(rows.tuples().all())
    if not counts:
        return None
    right = counts.get(question.correct_option, 0)
    text = f"{right} right."
    wrong = {
        option: n
        for option, n in counts.items()
        if option != question.correct_option and 0 <= option < len(question.options)
    }
    if wrong:
        option, n = max(wrong.items(), key=lambda item: (item[1], -item[0]))
        letter = chr(ord("A") + option)
        text += f" Most common wrong answer: {letter}, {_short(question.options[option])} ({n})."
    return text


async def class_summary(db: AsyncSession, session: Session) -> str:
    """A line such as: Class ended: 24 of 30 came, 78% of answers given. Hardest: Recursion."""
    seen = await attendance.session_attendance(db, session)
    delivered = (
        await db.scalar(
            select(func.count())
            .select_from(DeliveredQuestion)
            .where(DeliveredQuestion.session_id == session.session_id)
        )
        or 0
    )
    answers = (
        await db.scalar(
            select(func.count())
            .select_from(StudentResponse)
            .where(StudentResponse.session_id == session.session_id)
        )
        or 0
    )
    parts = [f"Class ended: {seen.present} of {seen.total} came"]
    possible = delivered * seen.present
    if possible:
        parts.append(f"{round(100 * answers / possible)}% of answers given")
    text = ", ".join(parts) + "."
    topics = await DatabaseTopicAnswers(db).session_topics(session.session_id)
    hardest = next((t.topic for t in topics if t.level == "hard"), None)
    if hardest:
        text += f" Hardest: {hardest}."
    return text
