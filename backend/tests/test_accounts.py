"""Admin account management, against a real database. Commits are turned into
flushes and every test is rolled back, so nothing is left behind."""

import uuid

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.core.config import get_settings
from app.core.errors import ConflictError, NotFoundError, ValidationError
from app.core.security import verify_password
from app.models.course import Course
from app.models.student import Student
from app.models.user import User
from app.schemas.accounts import AccountCreate, AccountUpdate, CourseCreate
from app.schemas.identity import Role
from app.services import accounts

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


def email(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:10]}@Example.com"


@pytest.fixture
async def course(db):
    row = Course(code=f"AC{uuid.uuid4().hex[:6]}".upper(), name="Accounts")
    db.add(row)
    await db.flush()
    return row


@pytest.fixture
async def admin(db):
    row = User(name="Acting Admin", role="admin", email=email("admin").lower())
    db.add(row)
    await db.flush()
    return row


async def test_a_student_is_created_enrolled_and_without_a_password(db, course) -> None:
    created, password = await accounts.create_account(
        db, AccountCreate(name=" Sam ", email=email("sam"), role=Role.STUDENT, course_id=course.id)
    )
    assert password is None
    assert created.name == "Sam"
    assert created.email == created.email.lower()
    assert created.course is not None and created.course.id == course.id
    assert not created.has_password and not created.teams_linked
    student = await db.scalar(select(Student).where(Student.user_id == created.id))
    assert student is not None and student.consent_status == "pending"


async def test_staff_get_a_one_time_password_stored_only_as_a_hash(db) -> None:
    created, password = await accounts.create_account(
        db, AccountCreate(name="Lee", email=email("lee"), role=Role.LECTURER, website_password=True)
    )
    user = await db.get(User, created.id)
    assert password and user.password_hash != password
    assert verify_password(password, user.password_hash)
    assert created.has_password and created.course is None


async def test_an_email_is_one_account(db, course) -> None:
    address = email("twice")
    await accounts.create_account(db, AccountCreate(name="A", email=address, role=Role.LECTURER))
    with pytest.raises(ConflictError):
        await accounts.create_account(
            db, AccountCreate(name="B", email=address.upper(), role=Role.ADMIN)
        )


async def test_a_student_needs_a_course_and_staff_cannot_have_one(db, course) -> None:
    with pytest.raises(ValidationError, match="course"):
        await accounts.create_account(
            db, AccountCreate(name="S", email=email("s"), role=Role.STUDENT)
        )
    with pytest.raises(ValidationError, match="Only students"):
        await accounts.create_account(
            db, AccountCreate(name="L", email=email("l"), role=Role.LECTURER, course_id=course.id)
        )
    with pytest.raises(ValidationError, match="does not exist"):
        await accounts.create_account(
            db, AccountCreate(name="S", email=email("s"), role=Role.STUDENT, course_id=uuid.uuid4())
        )


async def test_lecturer_and_admin_swap_but_a_student_stays_a_student(db, admin, course) -> None:
    lecturer, _ = await accounts.create_account(
        db, AccountCreate(name="L", email=email("l"), role=Role.LECTURER)
    )
    promoted = await accounts.update_account(
        db, admin.user_id, lecturer.id, AccountUpdate(role=Role.ADMIN)
    )
    assert promoted.role == Role.ADMIN
    student, _ = await accounts.create_account(
        db, AccountCreate(name="S", email=email("s"), role=Role.STUDENT, course_id=course.id)
    )
    with pytest.raises(ValidationError, match="stays a student"):
        await accounts.update_account(
            db, admin.user_id, student.id, AccountUpdate(role=Role.LECTURER)
        )


async def test_a_student_moves_course(db, admin, course) -> None:
    other = Course(code=f"MV{uuid.uuid4().hex[:6]}".upper(), name="Other")
    db.add(other)
    await db.flush()
    student, _ = await accounts.create_account(
        db, AccountCreate(name="S", email=email("s"), role=Role.STUDENT, course_id=course.id)
    )
    moved = await accounts.update_account(
        db, admin.user_id, student.id, AccountUpdate(course_id=other.id)
    )
    assert moved.course is not None and moved.course.code == other.code


async def test_an_admin_cannot_lock_themselves_or_everyone_out(db, admin) -> None:
    with pytest.raises(ConflictError, match="your own"):
        await accounts.update_account(db, admin.user_id, admin.user_id, AccountUpdate(active=False))
    with pytest.raises(ConflictError, match="your own"):
        await accounts.update_account(
            db, admin.user_id, admin.user_id, AccountUpdate(role=Role.LECTURER)
        )


async def test_the_last_active_admin_cannot_be_switched_off(db, admin, monkeypatch) -> None:
    other, _ = await accounts.create_account(
        db, AccountCreate(name="O", email=email("o"), role=Role.ADMIN)
    )

    async def one(_db):
        return 1

    monkeypatch.setattr(accounts, "_active_admins", one)
    with pytest.raises(ConflictError, match="last active admin"):
        await accounts.update_account(db, admin.user_id, other.id, AccountUpdate(active=False))


async def test_switching_off_and_renaming(db, admin) -> None:
    lecturer, _ = await accounts.create_account(
        db, AccountCreate(name="L", email=email("l"), role=Role.LECTURER)
    )
    changed = await accounts.update_account(
        db, admin.user_id, lecturer.id, AccountUpdate(active=False, name="Lecturer Two")
    )
    assert not changed.active and changed.name == "Lecturer Two"
    with pytest.raises(NotFoundError):
        await accounts.update_account(db, admin.user_id, uuid.uuid4(), AccountUpdate(active=False))


async def test_a_password_reset_replaces_the_old_one(db) -> None:
    lecturer, first = await accounts.create_account(
        db, AccountCreate(name="L", email=email("l"), role=Role.LECTURER, website_password=True)
    )
    _, second = await accounts.reset_password(db, lecturer.id)
    user = await db.get(User, lecturer.id)
    assert first != second
    assert verify_password(second, user.password_hash)
    assert not verify_password(first, user.password_hash)


async def test_listing_filters_by_role_and_text(db, course) -> None:
    tag = uuid.uuid4().hex[:8]
    await accounts.create_account(
        db, AccountCreate(name=f"Zed {tag}", email=email("z"), role=Role.LECTURER)
    )
    await accounts.create_account(
        db,
        AccountCreate(name=f"Yan {tag}", email=email("y"), role=Role.STUDENT, course_id=course.id),
    )
    found, total = await accounts.list_accounts(
        db, role=None, query=tag.upper(), limit=50, offset=0
    )
    assert total == 2 and {account.role for account in found} == {Role.LECTURER, Role.STUDENT}
    students, total = await accounts.list_accounts(
        db, role=Role.STUDENT, query=tag, limit=50, offset=0
    )
    assert total == 1 and students[0].course is not None


async def test_a_course_code_is_unique(db) -> None:
    code = f"cc{uuid.uuid4().hex[:6]}"
    created = await accounts.create_course(db, CourseCreate(code=code, name="Course"))
    assert created.code == code.upper()
    with pytest.raises(ConflictError):
        await accounts.create_course(db, CourseCreate(code=code.upper(), name="Again"))
