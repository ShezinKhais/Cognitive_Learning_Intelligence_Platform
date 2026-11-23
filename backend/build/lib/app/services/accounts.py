"""Adding people to C.L.I.P, and changing or switching off their accounts.

Owner: General CS. Admin only, through app.api.v1.accounts.

Rules kept here rather than in the routes:

- An email is one account. Emails are stored lower case, as sign-in and
  Teams single sign-on compare them.
- A student always has a course (student.user_id is unique, so one course),
  and staff never do. So a student stays a student, and only lecturer and
  admin swap: turning a student into staff would orphan their class data.
- An admin cannot switch off or demote themselves, and the last active admin
  cannot be removed, so nobody is ever locked out of this page.
- A password is generated, never chosen by the admin, shown once and stored
  only as a hash.
"""

from __future__ import annotations

import secrets
from datetime import date
from uuid import UUID

from sqlalchemy import exists, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import ConflictError, NotFoundError, ValidationError
from app.core.security import hash_password
from app.models.course import Course
from app.models.student import Student
from app.models.teams_user_mapping import TeamsUserMapping
from app.models.user import User
from app.schemas.accounts import AccountCreate, AccountOut, AccountUpdate, CourseCreate, CourseOut
from app.schemas.identity import Role

STAFF = {Role.LECTURER.value, Role.ADMIN.value}


def new_password() -> str:
    return secrets.token_urlsafe(12)


def _account(user: User, course: Course | None, teams_linked: bool) -> AccountOut:
    return AccountOut(
        id=user.user_id,
        name=user.name,
        email=user.email,
        role=Role(user.role),
        active=user.active,
        course=CourseOut.model_validate(course) if course is not None else None,
        has_password=bool(user.password_hash),
        teams_linked=teams_linked,
    )


def _listing():
    linked = exists().where(TeamsUserMapping.user_id == User.user_id)
    return (
        select(User, Course, linked.label("teams_linked"))
        .outerjoin(Student, Student.user_id == User.user_id)
        .outerjoin(Course, Course.id == Student.course_id)
    )


async def get_account(db: AsyncSession, user_id: UUID) -> AccountOut:
    row = (await db.execute(_listing().where(User.user_id == user_id))).first()
    if row is None:
        raise NotFoundError("No such account.")
    return _account(*row)


async def list_accounts(
    db: AsyncSession, *, role: Role | None, query: str | None, limit: int, offset: int
) -> tuple[list[AccountOut], int]:
    conditions = []
    if role is not None:
        conditions.append(User.role == role.value)
    if query:
        pattern = f"%{query.strip().lower()}%"
        conditions.append(or_(func.lower(User.name).like(pattern), User.email.like(pattern)))
    total = await db.scalar(select(func.count()).select_from(User).where(*conditions)) or 0
    rows = (
        await db.execute(
            _listing().where(*conditions).order_by(User.role, User.name).limit(limit).offset(offset)
        )
    ).all()
    return [_account(*row) for row in rows], int(total)


async def list_courses(db: AsyncSession) -> list[CourseOut]:
    courses = await db.scalars(select(Course).order_by(Course.code))
    return [CourseOut.model_validate(course) for course in courses]


async def create_course(db: AsyncSession, payload: CourseCreate) -> CourseOut:
    if await db.scalar(select(Course.id).where(Course.code == payload.code)):
        raise ConflictError(f"{payload.code} already exists.")
    course = Course(code=payload.code, name=payload.name.strip())
    db.add(course)
    await db.flush()
    await db.commit()
    return CourseOut.model_validate(course)


async def _course(db: AsyncSession, course_id: UUID) -> Course:
    course = await db.get(Course, course_id)
    if course is None:
        raise ValidationError("That course does not exist.")
    return course


async def create_account(db: AsyncSession, payload: AccountCreate) -> tuple[AccountOut, str | None]:
    if await db.scalar(select(User.user_id).where(User.email == payload.email)):
        raise ConflictError(f"{payload.email} already has an account.")
    is_student = payload.role == Role.STUDENT
    if is_student and payload.course_id is None:
        raise ValidationError("Choose the student's course.")
    if not is_student and payload.course_id is not None:
        raise ValidationError("Only students are enrolled on a course.")
    course = await _course(db, payload.course_id) if payload.course_id else None
    password = new_password() if payload.website_password else None
    user = User(
        name=payload.name,
        role=payload.role.value,
        email=payload.email,
        password_hash=hash_password(password) if password else None,
    )
    db.add(user)
    await db.flush()
    if course is not None:
        db.add(
            Student(
                user_id=user.user_id,
                course_id=course.id,
                consent_status="pending",
                enrolled_at=date.today(),
            )
        )
    await db.commit()
    return _account(user, course, False), password


async def _active_admins(db: AsyncSession) -> int:
    return int(
        await db.scalar(
            select(func.count())
            .select_from(User)
            .where(User.role == Role.ADMIN.value, User.active.is_(True))
        )
        or 0
    )


async def update_account(
    db: AsyncSession, acting_admin: UUID, user_id: UUID, payload: AccountUpdate
) -> AccountOut:
    user = await db.get(User, user_id)
    if user is None:
        raise NotFoundError("No such account.")
    removes_admin = user.role == Role.ADMIN.value and (
        payload.active is False or (payload.role is not None and payload.role != Role.ADMIN)
    )
    if removes_admin and user.user_id == acting_admin:
        raise ConflictError("You cannot switch off or demote your own account.")
    if removes_admin and user.active and await _active_admins(db) <= 1:
        raise ConflictError("This is the last active admin. Make another admin first.")

    if payload.role is not None and payload.role.value != user.role:
        if user.role not in STAFF or payload.role.value not in STAFF:
            raise ValidationError("Only lecturer and admin can swap. A student stays a student.")
        user.role = payload.role.value
    if payload.course_id is not None:
        if user.role != Role.STUDENT.value:
            raise ValidationError("Only students are enrolled on a course.")
        course = await _course(db, payload.course_id)
        student = await db.scalar(select(Student).where(Student.user_id == user.user_id))
        if student is None:
            db.add(
                Student(
                    user_id=user.user_id,
                    course_id=course.id,
                    consent_status="pending",
                    enrolled_at=date.today(),
                )
            )
        elif student.course_id != course.id:
            student.course_id = course.id
            student.enrolled_at = date.today()
    if payload.name is not None:
        name = payload.name.strip()
        if not name:
            raise ValidationError("A name is required.")
        user.name = name
    if payload.active is not None:
        user.active = payload.active
    await db.commit()
    return await get_account(db, user_id)


async def reset_password(db: AsyncSession, user_id: UUID) -> tuple[AccountOut, str]:
    user = await db.get(User, user_id)
    if user is None:
        raise NotFoundError("No such account.")
    password = new_password()
    user.password_hash = hash_password(password)
    await db.commit()
    return await get_account(db, user_id), password
