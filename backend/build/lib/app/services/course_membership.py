"""Which students are on which courses, which lecturers teach them, and
changing either.

Owner: General CS, Phase 8. The one definition of "on a course": the
student's home course (student.course_id) or a course_enrollment row. Every
check that decides what a student may see goes through memberships() or
students_on(), so a student only ever sees the classes of the courses they
are on.

Who may change a course's students: an admin, or a lecturer who teaches the
course. Only an admin says who teaches it.
"""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import Select, delete, select, union
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import Principal
from app.core.errors import NotFoundError, PermissionError_, ValidationError
from app.models.course import Course
from app.models.course_enrollment import CourseEnrollment, CourseLecturer
from app.models.student import Student
from app.models.user import User
from app.schemas.accounts import CourseOut, CourseRoster, RosterPerson
from app.schemas.identity import Role


def memberships():  # noqa: ANN201 - a selectable of (student_id, course_id)
    """Every (student_id, course_id) a student is on, home course included."""
    return union(
        select(Student.student_id.label("student_id"), Student.course_id.label("course_id")),
        select(CourseEnrollment.student_id, CourseEnrollment.course_id),
    ).subquery("membership")


def students_on(course_id) -> Select:  # noqa: ANN001 - a UUID or a column
    """Student ids on a course; usable as Student.student_id.in_(...)."""
    on = memberships()
    return select(on.c.student_id).where(on.c.course_id == course_id)


def courses_of_user(user_id) -> Select:  # noqa: ANN001 - a UUID or a column
    """Course ids a student account is on; usable as X.course_id.in_(...)."""
    on = memberships()
    return (
        select(on.c.course_id)
        .join(Student, Student.student_id == on.c.student_id)
        .where(Student.user_id == user_id)
    )


async def teaches(db: AsyncSession, user_id: UUID, course_id: UUID) -> bool:
    return (
        await db.scalar(
            select(CourseLecturer.user_id).where(
                CourseLecturer.user_id == user_id, CourseLecturer.course_id == course_id
            )
        )
    ) is not None


async def _course(db: AsyncSession, code: str) -> Course:
    course = await db.scalar(select(Course).where(Course.code == code.strip().upper()))
    if course is None:
        raise NotFoundError("No course has that code.", {"course_code": code})
    return course


async def _may_manage(db: AsyncSession, principal: Principal, course: Course) -> None:
    if principal.is_(Role.ADMIN):
        return
    if principal.is_(Role.LECTURER) and await teaches(db, principal.user_id, course.id):
        return
    raise PermissionError_("Only an admin or a lecturer of this course can change its students.")


async def my_courses(db: AsyncSession, principal: Principal) -> list[CourseOut]:
    """Every course for an admin; the courses they teach for a lecturer."""
    query = select(Course).order_by(Course.code)
    if not principal.is_(Role.ADMIN):
        query = query.join(CourseLecturer, CourseLecturer.course_id == Course.id).where(
            CourseLecturer.user_id == principal.user_id
        )
    return [CourseOut.model_validate(course) for course in await db.scalars(query)]


async def roster(db: AsyncSession, principal: Principal, code: str) -> CourseRoster:
    course = await _course(db, code)
    await _may_manage(db, principal, course)
    lecturers = await db.execute(
        select(User.user_id, User.name, User.email)
        .join(CourseLecturer, CourseLecturer.user_id == User.user_id)
        .where(CourseLecturer.course_id == course.id)
        .order_by(User.name)
    )
    on = memberships()
    students = await db.execute(
        select(User.user_id, User.name, User.email, Student.course_id == course.id)
        .join(Student, Student.user_id == User.user_id)
        .join(on, on.c.student_id == Student.student_id)
        .where(on.c.course_id == course.id, User.active.is_(True))
        .order_by(User.name)
    )
    return CourseRoster(
        course=CourseOut.model_validate(course),
        lecturers=[RosterPerson(id=i, name=n, email=e) for i, n, e in lecturers.all()],
        students=[
            RosterPerson(id=i, name=n, email=e, home_course=bool(home))
            for i, n, e, home in students.all()
        ],
    )


async def add_student(db: AsyncSession, principal: Principal, code: str, email: str) -> None:
    course = await _course(db, code)
    await _may_manage(db, principal, course)
    student = await db.scalar(
        select(Student)
        .join(User, User.user_id == Student.user_id)
        .where(User.email == email.strip().lower(), User.role == Role.STUDENT.value)
    )
    if student is None:
        raise NotFoundError(
            "No student account has that email. An admin adds new people on the Accounts page.",
            {"email": email},
        )
    if student.course_id == course.id:
        return
    await db.execute(
        insert(CourseEnrollment)
        .values(student_id=student.student_id, course_id=course.id)
        .on_conflict_do_nothing()
    )


async def remove_student(db: AsyncSession, principal: Principal, code: str, user_id: UUID) -> None:
    """Take a student off a course. A student stays on at least one course:
    when this is their home course, another of theirs becomes home."""
    course = await _course(db, code)
    await _may_manage(db, principal, course)
    student = await db.scalar(select(Student).where(Student.user_id == user_id))
    if student is None:
        raise NotFoundError("That student was not found.", {"user_id": str(user_id)})
    if student.course_id != course.id:
        await db.execute(
            delete(CourseEnrollment).where(
                CourseEnrollment.student_id == student.student_id,
                CourseEnrollment.course_id == course.id,
            )
        )
        return
    other = await db.scalar(
        select(CourseEnrollment)
        .where(CourseEnrollment.student_id == student.student_id)
        .order_by(CourseEnrollment.added_at)
        .limit(1)
    )
    if other is None:
        raise ValidationError(
            "This is the student's only course. Add them to another course first, "
            "or switch their account off on the Accounts page."
        )
    student.course_id = other.course_id
    await db.delete(other)
    await db.flush()


async def set_lecturers(
    db: AsyncSession, principal: Principal, code: str, user_ids: list[UUID]
) -> None:
    """Admin only: the lecturers who teach this course."""
    if not principal.is_(Role.ADMIN):
        raise PermissionError_("Only an admin says who teaches a course.")
    course = await _course(db, code)
    wanted = set(user_ids)
    if wanted:
        found = set(
            await db.scalars(
                select(User.user_id).where(
                    User.user_id.in_(wanted), User.role == Role.LECTURER.value
                )
            )
        )
        if found != wanted:
            raise ValidationError("Only lecturer accounts can teach a course.")
    await db.execute(delete(CourseLecturer).where(CourseLecturer.course_id == course.id))
    for user_id in wanted:
        db.add(CourseLecturer(course_id=course.id, user_id=user_id))
    await db.flush()
