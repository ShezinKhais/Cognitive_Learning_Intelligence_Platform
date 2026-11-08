"""How each question and each student did in one session, for its lecturer.

The results page showed a strip of right and wrong per question and a total.
A lecturer could not see which question tripped the class up, how the
choices split, or which students answered, without opening the PDF report.
This reads what the session stored and lays it out both ways, and as a CSV
for a spreadsheet or the marks system.
"""

from __future__ import annotations

import csv
import io
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.delivered_question import DeliveredQuestion
from app.models.missed_response import MissedResponse
from app.models.question import Question
from app.models.student import Student
from app.models.student_response import StudentResponse
from app.models.user import User
from app.schemas.session import (
    QuestionBreakdown,
    SessionBreakdownOut,
    StudentBreakdown,
)


async def _asked(db: AsyncSession, session_id: UUID) -> list[tuple[DeliveredQuestion, Question]]:
    rows = await db.execute(
        select(DeliveredQuestion, Question)
        .join(Question, Question.question_id == DeliveredQuestion.question_id)
        .where(DeliveredQuestion.session_id == session_id)
        .order_by(DeliveredQuestion.delivered_at)
    )
    return list(rows.tuples().all())


async def _answers(db: AsyncSession, session_id: UUID) -> list[tuple[StudentResponse, str]]:
    rows = await db.execute(
        select(StudentResponse, User.name)
        .join(Student, Student.student_id == StudentResponse.student_id)
        .join(User, User.user_id == Student.user_id)
        .where(StudentResponse.session_id == session_id)
        .order_by(StudentResponse.submitted_at)
    )
    return list(rows.tuples().all())


async def build(db: AsyncSession, session_id: UUID) -> SessionBreakdownOut:
    asked = await _asked(db, session_id)
    answers = await _answers(db, session_id)
    missed_rows = await db.execute(
        select(MissedResponse.student_id, User.name, func.count())
        .join(DeliveredQuestion, DeliveredQuestion.delivery_id == MissedResponse.delivery_id)
        .join(Student, Student.student_id == MissedResponse.student_id)
        .join(User, User.user_id == Student.user_id)
        .where(DeliveredQuestion.session_id == session_id)
        .group_by(MissedResponse.student_id, User.name)
    )

    questions: list[QuestionBreakdown] = []
    for number, (delivery, question) in enumerate(asked, start=1):
        mine = [answer for answer, _ in answers if answer.question_id == question.question_id]
        counts = None
        if question.options:
            counts = [0] * len(question.options)
            for answer in mine:
                if answer.selected_option is not None and 0 <= answer.selected_option < len(counts):
                    counts[answer.selected_option] += 1
        times = [answer.elapsed_ms for answer in mine if answer.elapsed_ms is not None]
        questions.append(
            QuestionBreakdown(
                number=number,
                question_id=question.question_id,
                prompt=question.question_text,
                type=question.question_type,
                options=question.options,
                correct_option=question.correct_option,
                topic=question.topic,
                eligible=delivery.eligible_count,
                answers=len(mine),
                correct=sum(1 for answer in mine if answer.is_correct is True),
                marked=sum(1 for answer in mine if answer.is_correct is not None),
                option_counts=counts,
                median_seconds=_median(times) / 1000 if times else None,
            )
        )

    students: dict[UUID, StudentBreakdown] = {}
    for answer, name in answers:
        row = students.setdefault(
            answer.student_id, StudentBreakdown(student_id=answer.student_id, name=name)
        )
        row.answered += 1
        row.correct += 1 if answer.is_correct is True else 0
        row.marked += 1 if answer.is_correct is not None else 0
    for student_id, name, missed in missed_rows.tuples().all():
        row = students.setdefault(student_id, StudentBreakdown(student_id=student_id, name=name))
        row.missed = missed

    return SessionBreakdownOut(
        session_id=session_id,
        questions=questions,
        students=sorted(students.values(), key=lambda row: row.name.casefold()),
    )


async def csv_rows(db: AsyncSession, session_id: UUID) -> str:
    """One row per answer: who, which question, what they chose, and whether
    it was right."""
    asked = await _asked(db, session_id)
    number = {question.question_id: index for index, (_, question) in enumerate(asked, start=1)}
    prompts = {question.question_id: question for _, question in asked}
    out = io.StringIO()
    writer = csv.writer(out)
    writer.writerow(
        ["student", "question_number", "question", "answer", "correct", "seconds", "submitted_at"]
    )
    for answer, name in await _answers(db, session_id):
        question = prompts.get(answer.question_id)
        options = question.options if question and question.options else []
        if answer.selected_option is not None:
            picked = answer.selected_option
            chosen = options[picked] if 0 <= picked < len(options) else ""
        else:
            chosen = answer.free_text or ""
        writer.writerow(
            [
                _safe(name),
                number.get(answer.question_id, ""),
                _safe(question.question_text if question else ""),
                _safe(chosen),
                "" if answer.is_correct is None else ("yes" if answer.is_correct else "no"),
                "" if answer.elapsed_ms is None else round(answer.elapsed_ms / 1000, 1),
                answer.submitted_at.isoformat(),
            ]
        )
    return out.getvalue()


def _median(values: list[int]) -> float:
    ordered = sorted(values)
    middle = len(ordered) // 2
    if len(ordered) % 2:
        return float(ordered[middle])
    return (ordered[middle - 1] + ordered[middle]) / 2


def _safe(text: str) -> str:
    """A cell a spreadsheet will not run as a formula. A student's written
    answer starting with = could otherwise execute when the lecturer opens
    the file."""
    return "'" + text if text[:1] in ("=", "+", "-", "@", "\t", "\r") else text
