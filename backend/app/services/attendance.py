"""Attendance: which students were in each class.

A student counts as present when either record shows them there:

- clip: they joined the live class in C.L.I.P (session_participant), with the
  time they joined and when they were last seen.
- teams: Teams told the bot they joined the class's meeting, and their Teams
  account is linked to theirs (a matched participant on a participant_joined
  roster event).

Absent means neither. It is a record of who was there, not a mark, and it is
shown only to the course's lecturers and admins. The class list is the
course's students now, plus anyone recorded in the class who has since left
the course.
"""

from __future__ import annotations

import csv
import io
from collections import defaultdict
from datetime import date, datetime
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.course import Course
from app.models.course_enrollment import CourseEnrollment
from app.models.session import Session
from app.models.session_participant import SessionParticipant
from app.models.student import Student
from app.models.teams_participant_mapping import TeamsParticipantMapping
from app.models.teams_roster_sync import TeamsRosterSync
from app.models.user import User
from app.schemas.attendance import (
    AttendanceClass,
    AttendanceRow,
    CourseAttendanceOut,
    CourseAttendanceRow,
    SessionAttendanceOut,
)

MAX_CLASSES = 40
JOINED = "participant_joined"
LEFT = "participant_left"


class _Seen:
    __slots__ = ("first", "last", "sources")

    def __init__(self) -> None:
        self.first: datetime | None = None
        self.last: datetime | None = None
        self.sources: set[str] = set()

    def add(self, source: str, first: datetime | None, last: datetime | None) -> None:
        self.sources.add(source)
        if first is not None and (self.first is None or first < self.first):
            self.first = first
        if last is not None and (self.last is None or last > self.last):
            self.last = last


async def _seen(db: AsyncSession, session_ids: list[UUID]) -> dict[tuple[UUID, UUID], _Seen]:
    """(session, student) -> when they were seen, from both records."""
    seen: dict[tuple[UUID, UUID], _Seen] = defaultdict(_Seen)
    if not session_ids:
        return seen
    rows = await db.execute(
        select(
            SessionParticipant.session_id,
            SessionParticipant.student_id,
            SessionParticipant.joined_at,
            func.coalesce(SessionParticipant.left_at, SessionParticipant.last_seen_at),
        ).where(SessionParticipant.session_id.in_(session_ids))
    )
    for session_id, student_id, joined, last in rows.tuples().all():
        seen[(session_id, student_id)].add("clip", joined, last)

    # A Teams join counts only for a matched account; a leave only extends
    # the time of someone already seen joining.
    rows = await db.execute(
        select(
            TeamsRosterSync.session_id,
            Student.student_id,
            TeamsRosterSync.event_type,
            TeamsRosterSync.received_at,
        )
        .join(TeamsParticipantMapping, TeamsParticipantMapping.sync_id == TeamsRosterSync.sync_id)
        .join(Student, Student.user_id == TeamsParticipantMapping.user_id)
        .where(
            TeamsRosterSync.session_id.in_(session_ids),
            TeamsRosterSync.event_type.in_([JOINED, LEFT]),
            TeamsParticipantMapping.match_status == "matched",
        )
        .order_by(TeamsRosterSync.received_at)
    )
    for session_id, student_id, kind, at in rows.tuples().all():
        key = (session_id, student_id)
        if kind == JOINED:
            seen[key].add("teams", at, at)
        elif key in seen and "teams" in seen[key].sources:
            seen[key].add("teams", None, at)
    return seen


async def _people(db: AsyncSession, course_id: UUID, extra: set[UUID]) -> list[tuple]:
    """Current members and recorded attendees, with the relevant enrolment date."""
    rows = await db.execute(
        select(
            Student.student_id,
            User.name,
            User.email,
            Student.course_id,
            Student.enrolled_at,
            CourseEnrollment.added_at,
        )
        .join(User, User.user_id == Student.user_id)
        .outerjoin(
            CourseEnrollment,
            (CourseEnrollment.student_id == Student.student_id)
            & (CourseEnrollment.course_id == course_id),
        )
        .where(
            (Student.course_id == course_id)
            | CourseEnrollment.student_id.is_not(None)
            | Student.student_id.in_(extra)
        )
        .order_by(func.lower(User.name))
    )
    return [
        (student, name, email, enrolled if home == course_id else added)
        for student, name, email, home, enrolled, added in rows.tuples().all()
    ]


def _before_enrolment(session: Session, enrolled: date | datetime | None) -> bool:
    # Use the class end when known. Home-course dates only have day precision,
    # so a student added on the day still counts as eligible for that class.
    ended = session.ended_at or session.end_time or session.start_time
    if ended is None or enrolled is None:
        return False
    if isinstance(enrolled, datetime):
        return ended < enrolled
    return ended.date() < enrolled


async def session_attendance(db: AsyncSession, session: Session) -> SessionAttendanceOut:
    seen = await _seen(db, [session.session_id])
    attended = {student for (_, student) in seen}
    code = await db.scalar(select(Course.code).where(Course.id == session.course_id)) or ""
    students = []
    for student_id, name, email, enrolled in await _people(db, session.course_id, attended):
        record = seen.get((session.session_id, student_id))
        if record is None and session.status == "ended" and _before_enrolment(session, enrolled):
            continue
        minutes = None
        if record and record.first and record.last:
            minutes = max(0, int((record.last - record.first).total_seconds() // 60))
        students.append(
            AttendanceRow(
                student_id=student_id,
                name=name,
                email=email,
                present=record is not None,
                first_seen=record.first if record else None,
                last_seen=record.last if record else None,
                minutes=minutes,
                sources=sorted(record.sources) if record else [],
            )
        )
    return SessionAttendanceOut(
        session_id=session.session_id,
        title=session.title or code,
        course_code=code,
        starts_at=session.start_time,
        present=sum(row.present for row in students),
        total=len(students),
        students=students,
    )


async def course_attendance(db: AsyncSession, course: Course) -> CourseAttendanceOut:
    """The course's finished classes, oldest first, the latest MAX_CLASSES."""
    recent = list(
        (
            await db.scalars(
                select(Session)
                .where(Session.course_id == course.id, Session.status == "ended")
                .order_by(Session.start_time.desc())
                .limit(MAX_CLASSES)
            )
        ).all()
    )
    classes = list(reversed(recent))
    ids = [s.session_id for s in classes]
    seen = await _seen(db, ids)
    attended = {student for (_, student) in seen}
    students = []
    for student_id, name, email, enrolled in await _people(db, course.id, attended):
        marks = [(sid, student_id) in seen for sid in ids]
        not_yet_enrolled = [
            session.session_id
            for session, present in zip(classes, marks, strict=True)
            if not present and _before_enrolment(session, enrolled)
        ]
        students.append(
            CourseAttendanceRow(
                student_id=student_id,
                name=name,
                email=email,
                attended=sum(marks),
                classes=marks,
                not_yet_enrolled=not_yet_enrolled,
            )
        )
    return CourseAttendanceOut(
        course_code=course.code,
        classes=[
            AttendanceClass(
                session_id=s.session_id, title=s.title or course.code, starts_at=s.start_time
            )
            for s in classes
        ],
        students=students,
    )


def course_csv(attendance: CourseAttendanceOut) -> str:
    """One row per student, one column per class: present or absent."""
    out = io.StringIO()
    writer = csv.writer(out)
    writer.writerow(
        ["student", "email", "attended", "of"]
        + [
            _safe(f"{c.starts_at:%Y-%m-%d} {c.title}" if c.starts_at else c.title)
            for c in attendance.classes
        ]
    )
    for row in attendance.students:
        not_yet_enrolled = set(row.not_yet_enrolled)
        marks = [
            "not yet enrolled"
            if session.session_id in not_yet_enrolled
            else "present"
            if mark
            else "absent"
            for session, mark in zip(attendance.classes, row.classes, strict=True)
        ]
        writer.writerow(
            [
                _safe(row.name),
                _safe(row.email),
                row.attended,
                len(row.classes) - len(not_yet_enrolled),
            ]
            + marks
        )
    return "﻿" + out.getvalue()


def _safe(text: str) -> str:
    """A cell a spreadsheet will not run as a formula."""
    return "'" + text if text.lstrip()[:1] in ("=", "+", "-", "@") else text
