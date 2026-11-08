"""Course rosters decide which classes a student sees, against a real
database. Commits become flushes and every test is rolled back."""

import uuid
from datetime import UTC, date, datetime

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.api.deps import Principal
from app.core.config import get_settings
from app.core.errors import NotFoundError, PermissionError_, ValidationError
from app.models.course import Course
from app.models.course_enrollment import CourseLecturer
from app.models.session import Session
from app.models.student import Student
from app.models.user import User
from app.schemas.identity import Role
from app.services import course_membership, session_access, session_reads

from .database_support import require_database


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


def _code() -> str:
    return f"CM{uuid.uuid4().hex[:6]}".upper()


async def _user(db, role: str) -> User:
    row = User(name=f"{role} {uuid.uuid4().hex[:4]}", role=role, email=f"{uuid.uuid4().hex}@t.test")
    db.add(row)
    await db.flush()
    return row


async def _student(db, course: Course) -> tuple[User, Student]:
    user = await _user(db, "student")
    student = Student(
        user_id=user.user_id,
        course_id=course.id,
        consent_status="granted",
        enrolled_at=date.today(),
    )
    db.add(student)
    await db.flush()
    return user, student


async def _session(db, course: Course, lecturer: User) -> Session:
    row = Session(
        instructor_id=lecturer.user_id,
        course_id=course.id,
        title="Week 1",
        start_time=datetime.now(UTC),
        mode="online",
        status="prepared",
    )
    db.add(row)
    await db.flush()
    return row


@pytest.fixture
async def world(db):
    first, second = Course(code=_code(), name="First"), Course(code=_code(), name="Second")
    db.add_all([first, second])
    await db.flush()
    lecturer = await _user(db, "lecturer")
    db.add(CourseLecturer(course_id=first.id, user_id=lecturer.user_id))
    await db.flush()
    return first, second, lecturer


def _as(user: User) -> Principal:
    return Principal(user.user_id, Role(user.role), user.email)


async def _visible_ids(db, user: User) -> set[uuid.UUID]:
    page = await session_reads.list_sessions(db, _as(user), limit=200, offset=0)
    return {item.id for item in page.items}


async def test_a_student_sees_only_the_classes_of_their_courses(db, world) -> None:
    first, second, lecturer = world
    other_lecturer = await _user(db, "lecturer")
    mine = await _session(db, first, lecturer)
    theirs = await _session(db, second, other_lecturer)
    user, _ = await _student(db, first)

    seen = await _visible_ids(db, user)
    assert mine.session_id in seen and theirs.session_id not in seen
    assert await session_access.session_membership_allowed(
        db, mine, user_id=user.user_id, role=Role.STUDENT
    )
    assert not await session_access.session_membership_allowed(
        db, theirs, user_id=user.user_id, role=Role.STUDENT
    )


async def test_adding_a_student_to_another_course_shows_its_classes(db, world) -> None:
    first, second, lecturer = world
    admin = await _user(db, "admin")
    other = await _session(db, second, lecturer)
    user, _ = await _student(db, first)

    await course_membership.add_student(db, _as(admin), second.code, user.email)

    assert other.session_id in await _visible_ids(db, user)
    assert await session_access.session_membership_allowed(
        db, other, user_id=user.user_id, role=Role.STUDENT
    )
    roster = await course_membership.roster(db, _as(admin), second.code)
    assert [p.id for p in roster.students] == [user.user_id]
    assert not roster.students[0].home_course

    await course_membership.remove_student(db, _as(admin), second.code, user.user_id)
    assert other.session_id not in await _visible_ids(db, user)


async def test_a_lecturer_manages_only_the_courses_they_teach(db, world) -> None:
    first, second, lecturer = world
    user, _ = await _student(db, second)

    await course_membership.add_student(db, _as(lecturer), first.code, user.email)
    with pytest.raises(PermissionError_):
        await course_membership.add_student(db, _as(lecturer), second.code, user.email)
    with pytest.raises(PermissionError_):
        await course_membership.set_lecturers(db, _as(lecturer), first.code, [])
    assert [c.code for c in await course_membership.my_courses(db, _as(lecturer))] == [first.code]


async def test_a_student_always_keeps_one_course(db, world) -> None:
    first, second, _ = world
    admin = await _user(db, "admin")
    user, student = await _student(db, first)

    with pytest.raises(ValidationError):
        await course_membership.remove_student(db, _as(admin), first.code, user.user_id)

    await course_membership.add_student(db, _as(admin), second.code, user.email)
    await course_membership.remove_student(db, _as(admin), first.code, user.user_id)
    await db.refresh(student)
    assert student.course_id == second.id


async def test_only_lecturers_can_be_assigned_and_unknown_emails_are_refused(db, world) -> None:
    first, _, lecturer = world
    admin = await _user(db, "admin")
    student_user, _ = await _student(db, first)

    with pytest.raises(ValidationError):
        await course_membership.set_lecturers(db, _as(admin), first.code, [student_user.user_id])
    await course_membership.set_lecturers(db, _as(admin), first.code, [lecturer.user_id])
    with pytest.raises(NotFoundError):
        await course_membership.add_student(db, _as(admin), first.code, "nobody@t.test")
