"""Attention signal summaries: folding a window of signals, and storing the result."""

import uuid
from datetime import UTC, date, datetime, timedelta
from types import SimpleNamespace

import pytest
from sqlalchemy import delete
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.core.config import get_settings
from app.models.attention_signal_summary import AttentionSignalSummary
from app.models.course import Course
from app.models.session import Session
from app.models.student import Student
from app.models.user import User
from app.repositories.attention_signal_repository import (
    WindowSummary,
    list_for_session,
    save_summary,
    summarise,
)
from app.schemas.events import AttentionSignalPayload

from .database_support import require_database

WINDOW_START = datetime(2026, 1, 1, 10, 0, tzinfo=UTC)


def signal(**fields) -> AttentionSignalPayload:
    fields.setdefault("window_seconds", 5.0)
    return AttentionSignalPayload(**fields)


def a_summary(**overrides) -> WindowSummary:
    fields = {
        "window_seconds": 60.0,
        "sample_count": 12,
        "gaze_on_screen_ratio": 0.7,
        "face_present_ratio": 1.0,
        "speaking_ratio": 0.0,
    }
    fields.update(overrides)
    return WindowSummary(**fields)


# --------------------------------------------------------------------------
# Folding a window of signals
# --------------------------------------------------------------------------


def test_summarise_averages_what_the_sensors_reported():
    summary = summarise(
        [
            signal(gaze_on_screen_ratio=1.0, face_present=True, speaking=False),
            signal(gaze_on_screen_ratio=0.5, face_present=True, speaking=True),
            signal(gaze_on_screen_ratio=0.0, face_present=False, speaking=False),
            signal(gaze_on_screen_ratio=0.5, face_present=True, speaking=False),
        ]
    )

    assert summary.sample_count == 4
    assert summary.window_seconds == 20.0
    assert summary.gaze_on_screen_ratio == pytest.approx(0.5)
    assert summary.face_present_ratio == pytest.approx(0.75)
    assert summary.speaking_ratio == pytest.approx(0.25)


def test_summarise_keeps_a_signal_nobody_reported_as_none_not_zero():
    summary = summarise([signal(face_present=True), signal(face_present=False)])

    assert summary.gaze_on_screen_ratio is None
    assert summary.speaking_ratio is None
    assert summary.face_present_ratio == pytest.approx(0.5)


def test_summarise_leaves_unreported_values_out_of_the_average():
    summary = summarise(
        [
            signal(gaze_on_screen_ratio=0.8),
            signal(),
            signal(gaze_on_screen_ratio=0.4),
        ]
    )

    assert summary.sample_count == 3
    assert summary.gaze_on_screen_ratio == pytest.approx(0.6)


def test_summarise_weights_each_value_by_how_long_it_lasted():
    summary = summarise(
        [
            signal(gaze_on_screen_ratio=1.0, face_present=True, speaking=True, window_seconds=1.0),
            signal(
                gaze_on_screen_ratio=0.0, face_present=False, speaking=False, window_seconds=59.0
            ),
        ]
    )

    assert summary.window_seconds == 60.0
    assert summary.gaze_on_screen_ratio == pytest.approx(1 / 60)
    assert summary.face_present_ratio == pytest.approx(1 / 60)
    assert summary.speaking_ratio == pytest.approx(1 / 60)


def test_summarise_weights_only_the_windows_that_reported():
    # The 50 s window has no gaze reading, so it must not dilute the 10 s one.
    summary = summarise(
        [
            signal(gaze_on_screen_ratio=0.8, window_seconds=10.0),
            signal(face_present=True, window_seconds=50.0),
        ]
    )

    assert summary.window_seconds == 60.0
    assert summary.gaze_on_screen_ratio == pytest.approx(0.8)


def test_summarise_rejects_an_empty_window():
    with pytest.raises(ValueError):
        summarise([])


# --------------------------------------------------------------------------
# Storing summaries, against a real database
# --------------------------------------------------------------------------


@pytest.fixture
async def database():
    require_database()
    engine = create_async_engine(get_settings().database_url, poolclass=NullPool)
    yield async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    await engine.dispose()


@pytest.fixture
async def classroom(database):
    """One student and two sessions of the same course. Everything it creates
    is removed afterwards."""
    async with database() as db:
        lecturer = User(
            name="Signal Lecturer", role="lecturer", email=f"l-{uuid.uuid4()}@example.com"
        )
        learner = User(name="Signal Student", role="student", email=f"s-{uuid.uuid4()}@example.com")
        course = Course(code=f"AS-{uuid.uuid4().hex[:8]}", name="Attention Signals")
        db.add_all([lecturer, learner, course])
        await db.flush()
        student = Student(
            user_id=learner.user_id,
            course_id=course.id,
            consent_status="granted",
            enrolled_at=date.today(),
        )
        sessions = [
            Session(
                instructor_id=lecturer.user_id,
                course_id=course.id,
                start_time=datetime.now(UTC),
                end_time=datetime.now(UTC) + timedelta(hours=1),
                mode="live",
                status="active",
            )
            for _ in range(2)
        ]
        db.add_all([student, *sessions])
        await db.commit()
        ids = SimpleNamespace(
            session=sessions[0].session_id,
            other_session=sessions[1].session_id,
            student=student.student_id,
            course=course.id,
            users=[lecturer.user_id, learner.user_id],
        )

    yield ids

    async with database() as db:
        await db.execute(
            delete(AttentionSignalSummary).where(AttentionSignalSummary.student_id == ids.student)
        )
        await db.execute(
            delete(Session).where(Session.session_id.in_([ids.session, ids.other_session]))
        )
        await db.execute(delete(Student).where(Student.student_id == ids.student))
        await db.execute(delete(Course).where(Course.id == ids.course))
        await db.execute(delete(User).where(User.user_id.in_(ids.users)))
        await db.commit()


async def test_summaries_are_listed_for_their_session_oldest_first(database, classroom):
    async with database() as db:
        for minute in (1, 0):
            await save_summary(
                db,
                session_id=classroom.session,
                student_id=classroom.student,
                window_start=WINDOW_START + timedelta(minutes=minute),
                summary=a_summary(sample_count=12 - minute),
            )
        await db.commit()

    async with database() as db:
        rows = await list_for_session(db, classroom.session)

    assert [row.window_start for row in rows] == [
        WINDOW_START,
        WINDOW_START + timedelta(minutes=1),
    ]
    assert all(row.session_id == classroom.session for row in rows)
    assert rows[0].gaze_on_screen_ratio == pytest.approx(0.7)


async def test_missing_signals_are_stored_as_null_not_zero(database, classroom):
    async with database() as db:
        await save_summary(
            db,
            session_id=classroom.session,
            student_id=classroom.student,
            window_start=WINDOW_START,
            summary=summarise([signal(face_present=True)]),
        )
        await db.commit()

    async with database() as db:
        [row] = await list_for_session(db, classroom.session)

    assert row.gaze_on_screen_ratio is None
    assert row.speaking_ratio is None
    assert row.face_present_ratio == pytest.approx(1.0)


async def test_a_session_does_not_see_another_sessions_summaries(database, classroom):
    async with database() as db:
        await save_summary(
            db,
            session_id=classroom.session,
            student_id=classroom.student,
            window_start=WINDOW_START,
            summary=a_summary(),
        )
        await db.commit()

    async with database() as db:
        assert await list_for_session(db, classroom.other_session) == []


async def test_a_ratio_outside_zero_to_one_is_rejected(database, classroom):
    async with database() as db:
        with pytest.raises(IntegrityError):
            await save_summary(
                db,
                session_id=classroom.session,
                student_id=classroom.student,
                window_start=WINDOW_START,
                summary=a_summary(gaze_on_screen_ratio=1.5),
            )


async def test_the_same_student_and_window_cannot_be_stored_twice(database, classroom):
    fields = {
        "session_id": classroom.session,
        "student_id": classroom.student,
        "window_start": WINDOW_START,
        "summary": a_summary(),
    }
    async with database() as db:
        await save_summary(db, **fields)
        await db.commit()

    async with database() as db:
        with pytest.raises(IntegrityError):
            await save_summary(db, **fields)


async def test_deleting_a_session_deletes_its_summaries(database, classroom):
    async with database() as db:
        await save_summary(
            db,
            session_id=classroom.session,
            student_id=classroom.student,
            window_start=WINDOW_START,
            summary=a_summary(),
        )
        await db.commit()

    async with database() as db:
        await db.execute(delete(Session).where(Session.session_id == classroom.session))
        await db.commit()

    async with database() as db:
        assert await list_for_session(db, classroom.session) == []


async def test_deleting_a_student_deletes_their_summaries(database, classroom):
    async with database() as db:
        await save_summary(
            db,
            session_id=classroom.session,
            student_id=classroom.student,
            window_start=WINDOW_START,
            summary=a_summary(),
        )
        await db.commit()

    async with database() as db:
        await db.execute(delete(Student).where(Student.student_id == classroom.student))
        await db.commit()

    async with database() as db:
        assert await list_for_session(db, classroom.session) == []
