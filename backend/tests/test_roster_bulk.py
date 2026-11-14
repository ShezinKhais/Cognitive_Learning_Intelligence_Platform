"""Adding a list of students to a course at once (#293), against a real
database. Commits become flushes and every test is rolled back."""

import uuid
from datetime import date

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.api.deps import Principal
from app.core.config import get_settings
from app.core.errors import NotFoundError, PermissionError_, ValidationError
from app.models.course import Course
from app.models.course_enrollment import CourseLecturer
from app.models.student import Student
from app.models.user import User
from app.schemas.accounts import BulkRosterIn
from app.schemas.identity import Role
from app.services import roster_bulk

from .database_support import require_database


def test_lines_are_read_as_email_or_name_and_email() -> None:
    text = (
        "Email,Name\n  ann@uni.test , Ann Lee\nBob Ray,BOB@uni.test\n\ncat@uni.test\nnot an email\n"
    )
    assert roster_bulk.parse(text) == [
        (2, "ann@uni.test", "Ann Lee"),
        (3, "bob@uni.test", "Bob Ray"),
        (5, "cat@uni.test", None),
        (6, "not an email", None),
    ]
    assert roster_bulk.parse("a@uni.test\tAnn\n") == [(1, "a@uni.test", "Ann")]
    assert roster_bulk.parse("a@uni.test;Ann\n") == [(1, "a@uni.test", "Ann")]
    assert roster_bulk._name_from("jane.doe-smith@uni.test") == "Jane Doe Smith"


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


async def _user(db, role: str, email: str | None = None, active: bool = True) -> User:
    row = User(
        name=f"{role} {uuid.uuid4().hex[:4]}",
        role=role,
        email=email or f"{uuid.uuid4().hex}@t.test",
        active=active,
    )
    db.add(row)
    await db.flush()
    return row


@pytest.fixture
async def world(db):
    course = Course(code=f"RB{uuid.uuid4().hex[:6]}".upper(), name="Bulk")
    other = Course(code=f"RB{uuid.uuid4().hex[:6]}".upper(), name="Other")
    db.add_all([course, other])
    await db.flush()
    lecturer = await _user(db, "lecturer")
    db.add(CourseLecturer(course_id=course.id, user_id=lecturer.user_id))
    stranger = await _user(db, "lecturer")
    admin = await _user(db, "admin")
    elsewhere = await _user(db, "student")
    db.add(
        Student(
            user_id=elsewhere.user_id,
            course_id=other.id,
            consent_status="granted",
            enrolled_at=date.today(),
        )
    )
    here = await _user(db, "student")
    db.add(
        Student(
            user_id=here.user_id,
            course_id=course.id,
            consent_status="granted",
            enrolled_at=date.today(),
        )
    )
    no_record = await _user(db, "student")
    gone = await _user(db, "student", active=False)
    staff = await _user(db, "lecturer")
    await db.flush()
    return {
        "course": course,
        "lecturer": lecturer,
        "stranger": stranger,
        "admin": admin,
        "elsewhere": elsewhere,
        "here": here,
        "no_record": no_record,
        "gone": gone,
        "staff": staff,
    }


def _as(user: User, role: Role) -> Principal:
    return Principal(user_id=user.user_id, role=role, email=user.email)


def _text(w) -> str:  # noqa: ANN001
    return "\n".join(
        [
            w["elsewhere"].email,
            w["here"].email,
            w["no_record"].email,
            w["gone"].email,
            w["staff"].email,
            "nobody@new.test",
            "not-an-email",
            w["elsewhere"].email.upper(),
        ]
    )


async def test_a_preview_reports_each_line_and_changes_nothing(db, world) -> None:
    w = world
    out = await roster_bulk.run(
        db, _as(w["lecturer"], Role.LECTURER), w["course"].code, BulkRosterIn(text=_text(w))
    )

    assert not out.applied and out.roster is None
    assert [line.outcome.value for line in out.lines] == [
        "add",
        "already",
        "add",
        "inactive",
        "not_student",
        "no_account",
        "invalid",
        "duplicate",
    ]
    assert out.counts["add"] == 2
    assert await db.scalar(select(Student).where(Student.user_id == w["no_record"].user_id)) is None


async def test_confirm_adds_exactly_what_the_preview_showed(db, world) -> None:
    w = world
    out = await roster_bulk.run(
        db,
        _as(w["lecturer"], Role.LECTURER),
        w["course"].code,
        BulkRosterIn(text=_text(w), confirm=True),
    )

    on_course = {person.email for person in out.roster.students}
    assert {w["elsewhere"].email, w["here"].email, w["no_record"].email} <= on_course
    assert w["gone"].email not in on_course and w["staff"].email not in on_course
    # The student who had no record has this course as their home course;
    # the one already elsewhere keeps their home course.
    new = await db.scalar(select(Student).where(Student.user_id == w["no_record"].user_id))
    assert new.course_id == w["course"].id
    moved = await db.scalar(select(Student).where(Student.user_id == w["elsewhere"].user_id))
    assert moved.course_id != w["course"].id
    assert await db.scalar(select(User).where(User.email == "nobody@new.test")) is None


async def test_only_an_admin_creates_missing_accounts(db, world) -> None:
    w = world
    text = "Nia Obi,nia.obi@new.test\nzed.k@new.test\n"
    with pytest.raises(PermissionError_):
        await roster_bulk.run(
            db,
            _as(w["lecturer"], Role.LECTURER),
            w["course"].code,
            BulkRosterIn(text=text, create_missing=True),
        )

    out = await roster_bulk.run(
        db,
        _as(w["admin"], Role.ADMIN),
        w["course"].code,
        BulkRosterIn(text=text, create_missing=True, confirm=True),
    )

    assert out.counts == {"create": 2}
    made = {
        user.email: user
        for user in await db.scalars(
            select(User).where(User.email.in_(["nia.obi@new.test", "zed.k@new.test"]))
        )
    }
    assert made["nia.obi@new.test"].name == "Nia Obi"
    assert made["zed.k@new.test"].name == "Zed K"
    assert all(user.role == "student" and user.password_hash is None for user in made.values())


async def test_a_lecturer_of_another_course_is_refused(db, world) -> None:
    w = world
    with pytest.raises(PermissionError_):
        await roster_bulk.run(
            db, _as(w["stranger"], Role.LECTURER), w["course"].code, BulkRosterIn(text="a@b.test")
        )
    with pytest.raises(NotFoundError):
        await roster_bulk.run(
            db, _as(w["admin"], Role.ADMIN), "NOPE999", BulkRosterIn(text="a@b.test")
        )


async def test_an_empty_or_oversized_list_is_refused(db, world) -> None:
    w = world
    principal = _as(w["admin"], Role.ADMIN)
    with pytest.raises(ValidationError):
        await roster_bulk.run(db, principal, w["course"].code, BulkRosterIn(text="\n , \n"))
    many = "\n".join(f"s{i}@uni.test" for i in range(roster_bulk.MAX_LINES + 1))
    with pytest.raises(ValidationError):
        await roster_bulk.run(db, principal, w["course"].code, BulkRosterIn(text=many))
