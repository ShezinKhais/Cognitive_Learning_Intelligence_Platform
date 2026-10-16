"""Reading and writing the history database. The caller owns the transaction."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.history.models import StudentSemesterSummary

ADDED = (
    "sessions_attended",
    "questions_attempted",
    "questions_correct",
    "engagement_sum",
    "engagement_count",
    "gaze_sum",
    "gaze_count",
)


@dataclass(frozen=True)
class SemesterTotals:
    """What to add to one student's row for one course and semester."""

    student_id: UUID
    course_id: UUID
    semester: str
    sessions_attended: int = 0
    questions_attempted: int = 0
    questions_correct: int = 0
    engagement_sum: float = 0.0
    engagement_count: int = 0
    gaze_sum: float = 0.0
    gaze_count: int = 0


def semester_label(when: datetime) -> str:
    """Calendar half-years: 2026-H1 for January to June, 2026-H2 for the rest.
    The one place to change if the university's semesters differ."""
    return f"{when.year}-H{1 if when.month <= 6 else 2}"


async def add_totals(db: AsyncSession, totals: list[SemesterTotals]) -> None:
    """Add to the rows, creating them when they do not exist."""
    for item in totals:
        values = {
            "student_id": item.student_id,
            "course_id": item.course_id,
            "semester": item.semester,
            **{name: getattr(item, name) for name in ADDED},
        }
        statement = insert(StudentSemesterSummary).values(**values)
        table = StudentSemesterSummary.__table__
        await db.execute(
            statement.on_conflict_do_update(
                constraint="uq_history_student_course_semester",
                set_={name: table.c[name] + statement.excluded[name] for name in ADDED},
            )
        )


async def list_for_student(db: AsyncSession, student_id: UUID) -> list[StudentSemesterSummary]:
    rows = await db.scalars(
        select(StudentSemesterSummary)
        .where(StudentSemesterSummary.student_id == student_id)
        .order_by(StudentSemesterSummary.semester, StudentSemesterSummary.course_id)
    )
    return list(rows)


async def delete_student(db: AsyncSession, student_id: UUID) -> int:
    """Erase every row for a student. Returns how many. Safe to repeat."""
    result = await db.execute(
        delete(StudentSemesterSummary).where(StudentSemesterSummary.student_id == student_id)
    )
    return result.rowcount or 0
