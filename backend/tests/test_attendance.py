"""Attendance from C.L.I.P joins and Teams meeting joins, against a real
database. Commits become flushes and every test is rolled back."""

import uuid
from datetime import UTC, date, datetime, timedelta

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.core.config import get_settings
from app.models.course import Course
from app.models.session import Session
from app.models.session_participant import SessionParticipant
from app.models.student import Student
from app.models.teams_participant_mapping import TeamsParticipantMapping
from app.models.teams_roster_sync import TeamsRosterSync
from app.models.user import User
from app.services import attendance

from .database_support import require_database

START = datetime(2026, 11, 2, 9, 0, tzinfo=UTC)


@pytest.fixture
async def db():
    require_database()
    engine = create_async_engine(get_settings().database_url, poolclass=NullPool)
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as session:
        session.commit = session.flush  # type: ignore[method-assign]
        yield session
        await session.rollback()
    await engine.dispose()


async def _student(db, course: Course, name: str) -> Student:
    user = User(name=name, role="student", email=f"{uuid.uuid4().hex}@t.test")
    db.add(user)
    await db.flush()
    student = Student(
        user_id=user.user_id,
        course_id=course.id,
        consent_status="granted",
        enrolled_at=date.today(),
    )
    db.add(student)
    await db.flush()
    return student


async def _class(db, course: Course, lecturer: User, start: datetime, status="ended") -> Session:
    row = Session(
        instructor_id=lecturer.user_id,
        course_id=course.id,
        title=f"Week {start.day}",
        start_time=start,
        mode="teams",
        status=status,
    )
    db.add(row)
    await db.flush()
    return row


async def _teams(db, session: Session, student: Student, kind: str, at: datetime) -> None:
    sync = TeamsRosterSync(
        meeting_id=f"meeting-{session.session_id}",
        session_id=session.session_id,
        source_event_id=uuid.uuid4().hex,
        event_type=kind,
        status="processed",
        participant_count=1,
        matched_count=1,
        received_at=at,
    )
    db.add(sync)
    await db.flush()
    db.add(
        TeamsParticipantMapping(
            sync_id=sync.sync_id,
            record_index=0,
            tenant_id="tenant",
            teams_user_id=uuid.uuid4().hex,
            user_id=student.user_id,
            match_status="matched",
        )
    )
    await db.flush()


@pytest.fixture
async def world(db):
    course = Course(code=f"AT{uuid.uuid4().hex[:6]}".upper(), name="Attendance")
    db.add(course)
    await db.flush()
    lecturer = User(name="Lecturer", role="lecturer", email=f"{uuid.uuid4().hex}@t.test")
    db.add(lecturer)
    await db.flush()
    ann = await _student(db, course, "Ann")
    bob = await _student(db, course, "Bob")
    cat = await _student(db, course, "Cat")
    first = await _class(db, course, lecturer, START)
    second = await _class(db, course, lecturer, START + timedelta(days=7))
    running = await _class(db, course, lecturer, START + timedelta(days=14), status="active")
    # Ann joined the first class in C.L.I.P for 50 minutes.
    db.add(
        SessionParticipant(
            session_id=first.session_id,
            student_id=ann.student_id,
            joined_at=START,
            last_seen_at=START + timedelta(minutes=50),
        )
    )
    # Bob was only in the Teams meeting of the first class, for 30 minutes.
    await _teams(db, first, bob, "participant_joined", START + timedelta(minutes=5))
    await _teams(db, first, bob, "participant_left", START + timedelta(minutes=35))
    # Cat only left the second class's meeting, with no join seen: not present.
    await _teams(db, second, cat, "participant_left", START + timedelta(days=7, minutes=20))
    await db.flush()
    return {
        "course": course,
        "ann": ann,
        "bob": bob,
        "cat": cat,
        "first": first,
        "second": second,
        "running": running,
    }


async def test_a_class_lists_who_was_there_and_how(db, world) -> None:
    out = await attendance.session_attendance(db, world["first"])

    rows = {row.name: row for row in out.students}
    assert (out.present, out.total) == (2, 3)
    assert (rows["Ann"].present, rows["Ann"].sources, rows["Ann"].minutes) == (True, ["clip"], 50)
    assert (rows["Bob"].present, rows["Bob"].sources, rows["Bob"].minutes) == (True, ["teams"], 30)
    assert (rows["Cat"].present, rows["Cat"].minutes) == (False, None)


async def test_the_course_view_has_one_column_per_finished_class(db, world) -> None:
    out = await attendance.course_attendance(db, world["course"])

    assert [c.session_id for c in out.classes] == [
        world["first"].session_id,
        world["second"].session_id,
    ]
    rows = {row.name: row for row in out.students}
    assert rows["Ann"].classes == [True, False] and rows["Ann"].attended == 1
    assert rows["Bob"].classes == [True, False]
    assert rows["Cat"].classes == [False, False] and rows["Cat"].attended == 0

    csv_text = attendance.course_csv(out)
    assert csv_text.startswith("﻿student,email,attended,of,")
    assert "Ann," in csv_text and ",present," in csv_text + ","
