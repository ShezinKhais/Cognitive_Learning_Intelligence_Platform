"""The history database: semester labels, adding up, and erasing a student.

Runs against the test database. The history tables are created there, and every
test is rolled back, so nothing is saved.
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.core.config import get_settings
from app.history.database import create_history_tables
from app.history.repository import (
    SemesterTotals,
    add_totals,
    delete_student,
    list_for_student,
    semester_label,
)

from .database_support import require_database


@pytest.fixture
async def history():
    require_database()
    engine = create_async_engine(get_settings().database_url, poolclass=NullPool)
    await create_history_tables(engine)
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as session:
        yield session
        await session.rollback()
    await engine.dispose()


def totals(student, course, semester="2001-H1", **more) -> SemesterTotals:
    return SemesterTotals(student_id=student, course_id=course, semester=semester, **more)


@pytest.mark.parametrize(
    ("when", "label"),
    [
        (datetime(2026, 1, 1, tzinfo=UTC), "2026-H1"),
        (datetime(2026, 6, 30, 23, 59, tzinfo=UTC), "2026-H1"),
        (datetime(2026, 7, 1, tzinfo=UTC), "2026-H2"),
        (datetime(2026, 12, 31, tzinfo=UTC), "2026-H2"),
    ],
)
def test_the_semester_label_is_a_calendar_half_year(when, label):
    assert semester_label(when) == label


async def test_a_second_purge_adds_to_the_same_row(history):
    student, course = uuid4(), uuid4()
    await add_totals(history, [totals(student, course, sessions_attended=2, questions_attempted=5)])
    await add_totals(history, [totals(student, course, sessions_attended=1, questions_attempted=3)])

    [row] = await list_for_student(history, student)
    assert (row.sessions_attended, row.questions_attempted) == (3, 8)


async def test_engagement_is_kept_as_sum_and_count_so_averages_stay_exact(history):
    student, course = uuid4(), uuid4()
    await add_totals(history, [totals(student, course, engagement_sum=1.5, engagement_count=2)])
    await add_totals(history, [totals(student, course, engagement_sum=0.5, engagement_count=2)])

    [row] = await list_for_student(history, student)
    assert row.engagement_sum / row.engagement_count == pytest.approx(0.5)


async def test_semesters_and_courses_are_separate_rows(history):
    student = uuid4()
    first, second = uuid4(), uuid4()
    await add_totals(
        history,
        [
            totals(student, first, "2001-H1", sessions_attended=1),
            totals(student, first, "2001-H2", sessions_attended=1),
            totals(student, second, "2001-H1", sessions_attended=1),
        ],
    )

    rows = await list_for_student(history, student)
    assert len(rows) == 3


async def test_erasing_a_student_removes_only_their_rows(history):
    student, other, course = uuid4(), uuid4(), uuid4()
    await add_totals(
        history,
        [totals(student, course, sessions_attended=1), totals(other, course, sessions_attended=1)],
    )

    assert await delete_student(history, student) == 1

    assert await list_for_student(history, student) == []
    assert len(await list_for_student(history, other)) == 1
    assert await delete_student(history, student) == 0
