"""Applying an admin's timetable or roster upload to the courses.

Owner: General CS, Phase 8. timetable_import.py reads and checks the file;
this module saves what it found:

- A course code that does not exist yet becomes a course, named after its
  code until an admin gives it a proper name.
- A timetable row makes its lecturer one of the course's lecturers.
- A roster row puts the student on the course.

Imports only ever add. Nobody is taken off a course and no account is
created: a lecturer or student without an account is reported back to the
admin, who adds them on the Accounts page and imports again. Importing the
same file twice changes nothing the second time.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import ValidationError
from app.models.course import Course
from app.models.course_enrollment import CourseEnrollment, CourseLecturer
from app.models.student import Student
from app.models.user import User
from app.schemas.identity import Role
from app.services.timetable_import import RosterRow, TimetableRow, match_names

# The same rule as an admin typing a course code on the Accounts page.
_CODE = re.compile(r"^[A-Za-z0-9_-]{2,20}$")


@dataclass
class ImportOutcome:
    courses_created: list[str] = field(default_factory=list)
    lecturers_assigned: int = 0
    students_enrolled: int = 0
    unmatched_lecturers: list[str] = field(default_factory=list)
    unmatched_students: list[str] = field(default_factory=list)


def _codes(rows: list[TimetableRow] | list[RosterRow]) -> list[str]:
    """The file's course codes, upper-cased, in order. One bad code refuses
    the whole file, before anything is saved."""
    codes: list[str] = []
    for row in rows:
        if not _CODE.match(row.course_code):
            raise ValidationError(
                f"Row {row.row_number}: course code {row.course_code!r} must be 2 to 20 "
                "letters, digits, hyphens or underscores.",
                {"row": row.row_number},
            )
        codes.append(row.course_code.upper())
    return list(dict.fromkeys(codes))


async def _courses(db: AsyncSession, codes: list[str], outcome: ImportOutcome) -> dict[str, UUID]:
    """Course ids by code, creating the courses the file names that do not exist."""
    query = select(Course.code, Course.id).where(Course.code.in_(codes))
    found = dict((await db.execute(query)).all())
    for code in codes:
        if code not in found:
            course = Course(code=code, name=code)
            db.add(course)
            await db.flush()
            found[code] = course.id
            outcome.courses_created.append(code)
    return found


async def apply_timetable(db: AsyncSession, rows: list[TimetableRow]) -> ImportOutcome:
    """Each row's lecturer teaches its course."""
    outcome = ImportOutcome()
    courses = await _courses(db, _codes(rows), outcome)

    lecturers = (
        await db.execute(
            select(User.name, User.user_id).where(
                User.role == Role.LECTURER.value, User.active.is_(True)
            )
        )
    ).all()
    ids_by_name: dict[str, list[UUID]] = {}
    for name, user_id in lecturers:
        ids_by_name.setdefault(name, []).append(user_id)
    unmatched, matched = match_names([row.lecturer for row in rows], list(ids_by_name))
    outcome.unmatched_lecturers = unmatched

    for row in rows:
        known = matched.get(row.lecturer)
        if known is None:
            continue
        ids = ids_by_name[known]
        if len(ids) > 1:
            # Two lecturers share the name: guessing would let the wrong one in.
            if row.lecturer not in outcome.unmatched_lecturers:
                outcome.unmatched_lecturers.append(row.lecturer)
            continue
        added = await db.execute(
            insert(CourseLecturer)
            .values(course_id=courses[row.course_code.upper()], user_id=ids[0])
            .on_conflict_do_nothing()
        )
        outcome.lecturers_assigned += added.rowcount or 0
    await db.flush()
    return outcome


async def apply_roster(db: AsyncSession, rows: list[RosterRow]) -> ImportOutcome:
    """Each row's student is on its course. Students are found by email."""
    outcome = ImportOutcome()
    courses = await _courses(db, _codes(rows), outcome)

    emails = list(dict.fromkeys(row.student_email.lower() for row in rows))
    students = dict(
        (
            await db.execute(
                select(User.email, Student)
                .join(Student, Student.user_id == User.user_id)
                .where(User.email.in_(emails), User.role == Role.STUDENT.value)
            )
        ).all()
    )

    for row in rows:
        student = students.get(row.student_email.lower())
        if student is None:
            label = f"{row.student_name} ({row.student_email})"
            if label not in outcome.unmatched_students:
                outcome.unmatched_students.append(label)
            continue
        course_id = courses[row.course_code.upper()]
        if student.course_id == course_id:
            continue
        added = await db.execute(
            insert(CourseEnrollment)
            .values(student_id=student.student_id, course_id=course_id)
            .on_conflict_do_nothing()
        )
        outcome.students_enrolled += added.rowcount or 0
    await db.flush()
    return outcome
