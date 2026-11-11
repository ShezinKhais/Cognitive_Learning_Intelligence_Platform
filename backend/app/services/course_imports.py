"""Preview and apply administrator course imports in one transaction."""

import json
import re
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta
from hashlib import sha256
from hmac import compare_digest, digest
from uuid import UUID
from zoneinfo import ZoneInfo

from sqlalchemy import func, or_, select, text
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import ConflictError, ValidationError
from app.models.course import Course
from app.models.course_enrollment import CourseEnrollment, CourseLecturer
from app.models.session import Session
from app.models.student import Student
from app.models.user import User
from app.schemas.identity import ImportRow, TimetableImportResult
from app.schemas.session import SessionStatus
from app.services.session_lifecycle import MODE_IN_PERSON
from app.services.timetable_import import (
    DAY_ALIASES,
    RosterRow,
    TimetableRow,
    detect_timetable_conflicts,
)

DUBAI = ZoneInfo("Asia/Dubai")
DAYS = tuple(dict.fromkeys(DAY_ALIASES.values()))


@dataclass
class ImportPlan:
    result: TimetableImportResult
    courses: dict[str, UUID | None] = field(default_factory=dict)
    enrolments: set[tuple[str, UUID]] = field(default_factory=set)
    lecturers: set[tuple[str, UUID]] = field(default_factory=set)
    sessions: list[tuple[str, UUID, datetime, datetime, str]] = field(default_factory=list)
    matched_accounts: dict[int, UUID] = field(default_factory=dict)

    def token(self, secret: str, actor: UUID, raw: bytes, week_start: date | None) -> str:
        payload = [
            str(actor),
            sha256(raw).hexdigest(),
            str(week_start),
            self.result.model_dump(mode="json"),
            self.courses,
            self.matched_accounts,
            sorted(self.enrolments),
            sorted(self.lecturers),
        ]
        return digest(
            secret.encode(), json.dumps(payload, default=str, sort_keys=True).encode(), "sha256"
        ).hex()


def _code(row: TimetableRow | RosterRow) -> str:
    if not re.fullmatch(r"[A-Za-z0-9_-]{2,20}", row.course_code):
        raise ValidationError(f"Row {row.row_number}: enter a valid course code (2–20 characters).")
    return row.course_code.upper()


async def _courses(db: AsyncSession, codes: set[str], plan: ImportPlan) -> dict[str, UUID]:
    matches: dict[str, list[UUID]] = defaultdict(list)
    for course in await db.scalars(select(Course).where(func.upper(Course.code).in_(codes))):
        matches[course.code.upper()].append(course.id)
    for code, ids in sorted(matches.items()):
        if len(ids) > 1:
            plan.result.conflicts.append(
                f"Multiple courses use code {code}. Resolve this before importing."
            )
    return {code: ids[0] for code, ids in matches.items() if len(ids) == 1}


async def plan_roster(db: AsyncSession, rows: list[RosterRow]) -> ImportPlan:
    plan = ImportPlan(TimetableImportResult(rows_read=len(rows), sessions_created=0))
    courses = await _courses(db, {_code(row) for row in rows}, plan)
    emails = {row.student_email for row in rows}
    students: dict[str, list[Student]] = defaultdict(list)
    query = (
        select(User.email, Student)
        .join(Student, Student.user_id == User.user_id)
        .where(User.role == "student", User.active.is_(True), func.lower(User.email).in_(emails))
    )
    for email, student in await db.execute(query):
        students[email.lower()].append(student)
    student_ids = {student.student_id for matches in students.values() for student in matches}
    enrolled = set(
        (
            await db.execute(
                select(CourseEnrollment.course_id, CourseEnrollment.student_id).where(
                    CourseEnrollment.student_id.in_(student_ids),
                    CourseEnrollment.course_id.in_(courses.values()),
                )
            )
        ).tuples()
    )

    for row in rows:
        code = _code(row)
        matches = students[row.student_email]
        if len(matches) != 1:
            if row.student_email not in plan.result.unmatched_students:
                plan.result.unmatched_students.append(row.student_email)
            detail = "No unique active student profile for this email."
        else:
            student = matches[0]
            plan.matched_accounts[row.row_number] = student.student_id
            course_id = courses.get(code)
            key = (code, student.student_id)
            if student.course_id == course_id or (course_id, student.student_id) in enrolled:
                detail = "Already enrolled."
            elif key in plan.enrolments:
                detail = "Duplicate roster row."
            else:
                plan.courses[code] = course_id
                plan.enrolments.add(key)
                detail = "Add course enrolment."
        plan.result.rows.append(
            ImportRow(
                row=row.row_number, course_code=code, account=row.student_email, detail=detail
            )
        )
    return plan


def _slot(row: TimetableRow, week_start: date) -> tuple[datetime, datetime]:
    day = week_start + timedelta(days=DAYS.index(row.day))
    return datetime.combine(day, row.start_time, DUBAI), datetime.combine(day, row.end_time, DUBAI)


def _unique_timetable(rows: list[TimetableRow]) -> list[TimetableRow]:
    unique: dict[tuple, TimetableRow] = {}
    for row in rows:
        key = (
            _code(row),
            row.lecturer.casefold(),
            row.day,
            row.start_time,
            row.end_time,
            row.room.casefold(),
        )
        unique.setdefault(key, row)
    return list(unique.values())


async def plan_timetable(
    db: AsyncSession, rows: list[TimetableRow], week_start: date | None
) -> ImportPlan:
    unique = _unique_timetable(rows)
    plan = ImportPlan(
        TimetableImportResult(
            rows_read=len(rows), sessions_created=0, conflicts=detect_timetable_conflicts(unique)
        )
    )
    if week_start is not None and (week_start.weekday() != 0 or week_start.year >= 9999):
        raise ValidationError("Choose a Monday as the start of the timetable week.")
    courses = await _courses(db, {_code(row) for row in rows}, plan)
    names = {row.lecturer.lower() for row in rows}
    lecturers: dict[str, list[User]] = defaultdict(list)
    for user in await db.scalars(
        select(User).where(
            User.role == "lecturer", User.active.is_(True), func.lower(User.name).in_(names)
        )
    ):
        lecturers[user.name.lower()].append(user)
    user_ids = {user.user_id for matches in lecturers.values() for user in matches}

    existing: list[Session] = []
    assigned: set[tuple[UUID, UUID]] = set()
    if week_start is not None:
        start = datetime.combine(week_start, time.min, DUBAI)
        existing = list(
            await db.scalars(
                select(Session).where(
                    or_(
                        Session.instructor_id.in_(user_ids), Session.course_id.in_(courses.values())
                    ),
                    Session.status != SessionStatus.CANCELLED,
                    Session.start_time < start + timedelta(days=7),
                    or_(
                        Session.start_time >= start,
                        Session.end_time > start,
                        Session.ended_at > start,
                    ),
                )
            )
        )
        assigned = set(
            (
                await db.execute(
                    select(CourseLecturer.course_id, CourseLecturer.user_id).where(
                        CourseLecturer.course_id.in_(courses.values()),
                        CourseLecturer.user_id.in_(user_ids),
                    )
                )
            ).tuples()
        )

    unique_numbers = {row.row_number for row in unique}
    for row in rows:
        code = _code(row)
        matches = lecturers[row.lecturer.lower()]
        start_time, end_time = _slot(row, week_start) if week_start is not None else (None, None)
        if row.row_number not in unique_numbers:
            detail = "Duplicate timetable row."
        elif len(matches) != 1:
            if row.lecturer not in plan.result.unmatched_lecturers:
                plan.result.unmatched_lecturers.append(row.lecturer)
            detail = "No unique active lecturer with this name."
        elif start_time is None or end_time is None:
            detail = "Choose the timetable week to preview the dated session."
        else:
            user_id = matches[0].user_id
            plan.matched_accounts[row.row_number] = user_id
            course_id = courses.get(code)
            same_slot = overlaps = False
            for session in existing:
                if session.instructor_id != user_id and session.course_id != course_id:
                    continue
                if (
                    session.instructor_id == user_id
                    and session.course_id == course_id
                    and session.start_time == start_time
                    and session.end_time == end_time
                ):
                    same_slot = True
                    continue
                occupied_until = max(
                    session.start_time,
                    session.end_time or session.start_time,
                    session.ended_at or session.start_time,
                )
                if session.start_time < end_time and (
                    occupied_until > start_time or session.start_time >= start_time
                ):
                    overlaps = True
                    break
            if overlaps:
                detail = "Overlaps an existing lecturer or course session."
                plan.result.conflicts.append(f"Row {row.row_number} ({code}): {detail}")
            else:
                plan.courses[code] = course_id
                if (course_id, user_id) not in assigned:
                    plan.lecturers.add((code, user_id))
                if same_slot:
                    detail = "Session already exists."
                else:
                    plan.sessions.append((code, user_id, start_time, end_time, row.room))
                    detail = "Create prepared session."
        plan.result.rows.append(
            ImportRow(
                row=row.row_number,
                course_code=code,
                account=row.lecturer,
                detail=detail,
                start_time=start_time,
                end_time=end_time,
                room=row.room,
            )
        )
    # The parser already checks room and lecturer overlap. A course must also
    # have a single class at a time, even with different lecturers and rooms.
    by_course: dict[str, list[TimetableRow]] = defaultdict(list)
    for row in unique:
        by_course[_code(row)].append(row)
    for code, group in by_course.items():
        last = None
        for row in sorted(group, key=lambda item: (item.day, item.start_time)):
            if last and last.day == row.day and last.end_time > row.start_time:
                plan.result.conflicts.append(
                    f"Course {code}: rows {last.row_number} and {row.row_number} overlap."
                )
            if last is None or last.day != row.day or row.end_time > last.end_time:
                last = row
    return plan


async def lock_imports(db: AsyncSession) -> None:
    # Serialize confirm requests before planning against the latest committed rows.
    await db.execute(text("SELECT pg_advisory_xact_lock(240, 321)"))


async def finish_import(
    db: AsyncSession,
    plan: ImportPlan,
    *,
    raw: bytes,
    week_start: date | None,
    actor: UUID,
    secret: str,
    confirmation: str | None,
    can_apply: bool,
) -> TimetableImportResult:
    result = plan.result
    token = plan.token(secret, actor, raw, week_start)
    result.new_course_codes = sorted(
        code for code, course_id in plan.courses.items() if course_id is None
    )
    if confirmation is None:
        result.sessions_to_create = len(plan.sessions)
        result.courses_changed = sum(value is None for value in plan.courses.values())
        result.memberships_changed = len(plan.enrolments) + len(plan.lecturers)
        if can_apply and not result.conflicts:
            result.preview_token = token
        return result

    if not can_apply or result.conflicts or not compare_digest(token, confirmation):
        raise ConflictError(
            "The import cannot be confirmed. Preview the file again and resolve any conflicts."
        )

    course_ids = {}
    for code, course_id in sorted(plan.courses.items()):
        if course_id is None:
            course_id = await db.scalar(
                insert(Course)
                .values(code=code, name=code)
                .on_conflict_do_nothing(index_elements=[Course.code])
                .returning(Course.id)
            )
            if course_id is None:
                raise ConflictError("A course changed after preview. Preview the file again.")
            result.courses_changed += 1
        course_ids[code] = course_id

    for model, pairs, member_key in (
        (CourseEnrollment, plan.enrolments, "student_id"),
        (CourseLecturer, plan.lecturers, "user_id"),
    ):
        for code, member_id in sorted(pairs):
            inserted = await db.scalar(
                insert(model)
                .values(course_id=course_ids[code], **{member_key: member_id})
                .on_conflict_do_nothing()
                .returning(model.course_id)
            )
            if inserted is not None:
                result.memberships_changed += 1

    for code, lecturer_id, start, end, room in plan.sessions:
        db.add(
            Session(
                course_id=course_ids[code],
                instructor_id=lecturer_id,
                title=f"{code} · {room}"[:200],
                start_time=start,
                end_time=end,
                mode=MODE_IN_PERSON,
                status=SessionStatus.PREPARED,
            )
        )
    await db.flush()
    result.sessions_created = len(plan.sessions)
    result.applied = True
    for row in result.rows:
        if row.detail == "Create prepared session.":
            row.detail = "Prepared session created."
        elif row.detail == "Add course enrolment.":
            row.detail = "Course enrolment saved."
    return result
