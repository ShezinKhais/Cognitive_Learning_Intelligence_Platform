"""Session membership and ownership checks.

Owner: Cyber 1, Phase 3. Exercises app.services.session_access directly
against real Course/User/Student/Session rows -- no repository, no route,
no app fixture. Whichever branch adds the session repository and the REST
routes wires these functions in; what's under test here is only the policy:
who may join or manage a given session.
"""

from contextlib import asynccontextmanager
from datetime import UTC, date, datetime, timedelta
from uuid import uuid4

from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.core.config import get_settings
from app.models.course import Course
from app.models.session import Session as SessionModel
from app.models.student import Student
from app.models.user import User
from app.schemas.identity import Role
from app.services.session_access import session_membership_allowed

from .database_support import require_database


async def _seed(session_factory):
    """One course, one lecturer-taught session, one enrolled student.

    Returns (session_row, instructor_id, enrolled_student_user_id).
    """
    async with session_factory() as db:
        course = Course(code=f"C{uuid4().hex[:8]}", name="Access Test Course")
        db.add(course)
        await db.flush()

        instructor_id = uuid4()
        enrolled_user_id = uuid4()
        db.add(
            User(
                user_id=instructor_id,
                name="Lecturer",
                role="lecturer",
                email=f"{uuid4().hex[:8]}@uni.test",
            )
        )
        db.add(
            User(
                user_id=enrolled_user_id,
                name="Student",
                role="student",
                email=f"{uuid4().hex[:8]}@uni.test",
            )
        )
        await db.flush()

        db.add(
            Student(
                user_id=enrolled_user_id,
                course_id=course.id,
                consent_status="granted",
                enrolled_at=date.today(),
            )
        )

        now = datetime.now(UTC)
        session_row = SessionModel(
            instructor_id=instructor_id,
            course_id=course.id,
            start_time=now,
            end_time=now + timedelta(hours=1),
            mode="online",
            status="prepared",
        )
        db.add(session_row)
        await db.commit()
        await db.refresh(session_row)

        return session_row, instructor_id, enrolled_user_id, course.id


async def _cleanup(session_factory, session_row, instructor_id, enrolled_user_id, course_id):
    async with session_factory() as db:
        await db.execute(
            text("delete from session where session_id = :sid"), {"sid": session_row.session_id}
        )
        await db.execute(
            text("delete from student where user_id = :uid"), {"uid": enrolled_user_id}
        )
        await db.execute(
            text('delete from "user" where user_id in (:a, :b)'),
            {"a": instructor_id, "b": enrolled_user_id},
        )
        await db.execute(text("delete from course where id = :cid"), {"cid": course_id})
        await db.commit()


async def _session_factory():
    require_database()
    engine = create_async_engine(get_settings().database_url, poolclass=NullPool)
    return engine, async_sessionmaker(engine, expire_on_commit=False)


@asynccontextmanager
async def _seeded_session():
    """Seed a course/session/students, dispose the engine no matter what.

    The engine is created before _seed runs, so if _seed itself raises
    partway through, the connection (and any rows it already committed) must
    still be released -- the try/finally has to wrap the seed call, not just
    the test body that follows it.
    """
    engine, session_factory = await _session_factory()
    try:
        session_row, instructor_id, enrolled_user_id, course_id = await _seed(session_factory)
        try:
            yield session_factory, session_row, instructor_id, enrolled_user_id, course_id
        finally:
            await _cleanup(session_factory, session_row, instructor_id, enrolled_user_id, course_id)
    finally:
        await engine.dispose()


async def test_the_instructor_may_join_their_own_session():
    async with _seeded_session() as (session_factory, session_row, instructor_id, _, _):
        async with session_factory() as db:
            allowed = await session_membership_allowed(
                db, session_row, user_id=instructor_id, role=Role.LECTURER
            )
        assert allowed is True


async def test_a_lecturer_who_does_not_teach_this_session_is_denied():
    async with _seeded_session() as (session_factory, session_row, _, _, _):
        async with session_factory() as db:
            allowed = await session_membership_allowed(
                db, session_row, user_id=uuid4(), role=Role.LECTURER
            )
        assert allowed is False


async def test_an_enrolled_student_may_join():
    async with _seeded_session() as (session_factory, session_row, _, enrolled_user_id, _):
        async with session_factory() as db:
            allowed = await session_membership_allowed(
                db, session_row, user_id=enrolled_user_id, role=Role.STUDENT
            )
        assert allowed is True


async def test_a_student_not_enrolled_in_the_course_is_denied():
    async with _seeded_session() as (session_factory, session_row, _, _, _):
        async with session_factory() as db:
            allowed = await session_membership_allowed(
                db, session_row, user_id=uuid4(), role=Role.STUDENT
            )
        assert allowed is False


async def test_an_admin_may_join_any_session():
    async with _seeded_session() as (session_factory, session_row, _, _, _):
        async with session_factory() as db:
            allowed = await session_membership_allowed(
                db, session_row, user_id=uuid4(), role=Role.ADMIN
            )
        assert allowed is True


async def test_an_ended_session_cannot_be_joined_by_anyone():
    """Enrolment/ownership is necessary but not sufficient -- once a session
    has ended there is no stream left to join, even for its own instructor
    or an admin."""
    async with _seeded_session() as (
        session_factory,
        session_row,
        instructor_id,
        enrolled_user_id,
        _,
    ):
        async with session_factory() as db:
            row = await db.get(SessionModel, session_row.session_id)
            row.status = "ended"
            await db.commit()

        async with session_factory() as db:
            row = await db.get(SessionModel, session_row.session_id)
            assert (
                await session_membership_allowed(db, row, user_id=instructor_id, role=Role.LECTURER)
                is False
            )
            assert (
                await session_membership_allowed(
                    db, row, user_id=enrolled_user_id, role=Role.STUDENT
                )
                is False
            )
            assert (
                await session_membership_allowed(db, row, user_id=uuid4(), role=Role.ADMIN) is False
            )


async def test_a_cancelled_session_cannot_be_joined():
    async with _seeded_session() as (session_factory, session_row, _, enrolled_user_id, _):
        async with session_factory() as db:
            row = await db.get(SessionModel, session_row.session_id)
            row.status = "cancelled"
            await db.commit()

        async with session_factory() as db:
            row = await db.get(SessionModel, session_row.session_id)
            allowed = await session_membership_allowed(
                db, row, user_id=enrolled_user_id, role=Role.STUDENT
            )
        assert allowed is False
