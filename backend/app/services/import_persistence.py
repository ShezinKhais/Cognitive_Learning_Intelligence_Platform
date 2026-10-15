"""Saving an administrator's timetable and roster imports.

timetable_import parses and checks the files and touches no database. This
module takes its rows and writes them: courses and sessions from a timetable,
enrolments from a roster.

A timetable row names a weekday and a time, not a date. Each row becomes one
prepared session, on the next time that weekday comes round (today, if the
slot has not started yet). Uploading the timetable again each week adds the
following week's sessions; a slot that already has a session is left alone.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.session import Session
from app.models.student import Student
from app.models.user import User
from app.repositories.course_repository import CourseRepository
from app.repositories.session_repository import SessionRepository
from app.schemas.session import SessionStatus
from app.services.session_lifecycle import MODE_IN_PERSON
from app.services.timetable_import import RosterRow, TimetableRow, match_names

# Timetables are written in the university's local time (Dubai, no daylight
# saving), and sessions are stored with a time zone.
LOCAL_TIME = timezone(timedelta(hours=4))

WEEKDAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]

# What a student's consent is until they answer the consent screen.
NEW_STUDENT_CONSENT = "pending"


@dataclass
class ImportOutcome:
    sessions_created: int = 0
    students_enrolled: int = 0
    unmatched_lecturers: list[str] = field(default_factory=list)
    unmatched_students: list[str] = field(default_factory=list)
    problems: list[str] = field(default_factory=list)


def next_occurrence(day: str, at, now: datetime) -> datetime:
    """The next start of this weekday and time that is not already past."""
    local_now = now.astimezone(LOCAL_TIME)
    ahead = (WEEKDAYS.index(day) - local_now.weekday()) % 7
    start = datetime.combine(local_now.date() + timedelta(days=ahead), at, tzinfo=LOCAL_TIME)
    if start <= local_now:
        start += timedelta(days=7)
    return start.astimezone(UTC)


async def save_timetable(
    db: AsyncSession, rows: list[TimetableRow], *, now: datetime | None = None
) -> ImportOutcome:
    """Create the courses and sessions a timetable describes.

    A row whose lecturer is not a known lecturer is skipped and reported, not
    guessed at.
    """
    now = now or datetime.now(UTC)
    outcome = ImportOutcome()

    lecturers = (
        (await db.execute(select(User).where(User.role == "lecturer", User.active.is_(True))))
        .scalars()
        .all()
    )
    by_name = {lecturer.name: lecturer for lecturer in lecturers}
    outcome.unmatched_lecturers, matched = match_names([r.lecturer for r in rows], list(by_name))

    courses = CourseRepository(db)
    sessions = SessionRepository(db)
    for row in rows:
        known = matched.get(row.lecturer)
        if known is None:
            continue
        lecturer = by_name[known]
        course = await courses.get_by_code(row.course_code) or await courses.create(
            code=row.course_code, name=row.course_code
        )
        starts = next_occurrence(row.day, row.start_time, now)
        taken = await db.execute(
            select(Session.session_id).where(
                Session.instructor_id == lecturer.user_id,
                Session.course_id == course.id,
                Session.start_time == starts,
            )
        )
        if taken.first() is not None:
            continue
        created = await sessions.create(
            instructor_id=lecturer.user_id,
            course_id=course.id,
            title=f"{row.course_code} {row.day} {row.start_time:%H:%M}, {row.room}"[:200],
            start_time=starts,
            status=SessionStatus.PREPARED.value,
            mode=MODE_IN_PERSON,
        )
        created.end_time = starts + (
            datetime.combine(date.min, row.end_time) - datetime.combine(date.min, row.start_time)
        )
        outcome.sessions_created += 1
    return outcome


async def save_roster(
    db: AsyncSession, rows: list[RosterRow], *, today: date | None = None
) -> ImportOutcome:
    """Enrol the students a roster lists, matched to their accounts by email.

    A student has one course, so one already enrolled on a different course is
    reported, not moved.
    """
    today = today or datetime.now(UTC).date()
    outcome = ImportOutcome()

    emails = {row.student_email.strip().lower() for row in rows}
    accounts = (
        (
            await db.execute(
                select(User).where(
                    User.role == "student", User.active.is_(True), User.email.in_(emails)
                )
            )
        )
        .scalars()
        .all()
    )
    by_email = {account.email.lower(): account for account in accounts}

    courses = CourseRepository(db)
    for row in rows:
        account = by_email.get(row.student_email.strip().lower())
        if account is None:
            outcome.unmatched_students.append(f"{row.student_name} ({row.student_email})")
            continue
        course = await courses.get_by_code(row.course_code)
        if course is None:
            outcome.problems.append(
                f"Row {row.row_number}: course {row.course_code} does not exist. "
                "Import the timetable first."
            )
            continue
        enrolled = (
            await db.execute(select(Student).where(Student.user_id == account.user_id))
        ).scalar_one_or_none()
        if enrolled is None:
            db.add(
                Student(
                    user_id=account.user_id,
                    course_id=course.id,
                    consent_status=NEW_STUDENT_CONSENT,
                    enrolled_at=today,
                )
            )
            await db.flush()
            outcome.students_enrolled += 1
        elif enrolled.course_id != course.id:
            outcome.problems.append(
                f"Row {row.row_number}: {row.student_email} is already enrolled on another "
                f"course, so was not added to {row.course_code}."
            )
    return outcome
