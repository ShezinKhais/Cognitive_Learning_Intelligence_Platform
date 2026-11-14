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
from datetime import datetime, timedelta
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.models.course import Course
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
from app.services.course_membership import students_on

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
        elif key in seen:
            seen[key].add("teams", None, at)
    return seen


async def _people(db: AsyncSession, course_id: UUID, extra: set[UUID]) -> list[tuple]:
    """(student_id, name, email) for the course's students and anyone in extra."""
    rows = await db.execute(
        select(Student.student_id, User.name, User.email)
        .join(User, User.user_id == Student.user_id)
        .where(Student.student_id.in_(students_on(course_id)) | Student.student_id.in_(extra))
        .order_by(func.lower(User.name))
    )
    return list(rows.tuples().all())


def _late_after(session: Session) -> datetime | None:
    """From when a first join counts as late: the threshold after the class
    started, measured from the later of its timetabled and actual start."""
    minutes = get_settings().attendance_late_minutes
    if minutes <= 0:
        return None
    started = session.start_time
    if session.started_at is not None and (started is None or session.started_at > started):
        started = session.started_at
    return started + timedelta(minutes=minutes) if started else None


def _is_late(record: _Seen | None, after: datetime | None) -> bool:
    return bool(record and record.first and after and record.first > after)


async def session_attendance(db: AsyncSession, session: Session) -> SessionAttendanceOut:
    seen = await _seen(db, [session.session_id])
    late_after = _late_after(session)
    attended = {student for (_, student) in seen}
    code = await db.scalar(select(Course.code).where(Course.id == session.course_id)) or ""
    students = []
    for student_id, name, email in await _people(db, session.course_id, attended):
        record = seen.get((session.session_id, student_id))
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
                late=_is_late(record, late_after),
            )
        )
    return SessionAttendanceOut(
        session_id=session.session_id,
        title=session.title or code,
        course_code=code,
        starts_at=session.start_time,
        present=sum(row.present for row in students),
        late=sum(row.late for row in students),
        late_minutes=get_settings().attendance_late_minutes,
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
    late_after = {s.session_id: _late_after(s) for s in classes}
    for student_id, name, email in await _people(db, course.id, attended):
        marks = [(sid, student_id) in seen for sid in ids]
        late = [_is_late(seen.get((sid, student_id)), late_after[sid]) for sid in ids]
        students.append(
            CourseAttendanceRow(
                student_id=student_id,
                name=name,
                email=email,
                attended=sum(marks),
                classes=marks,
                late=late,
                late_count=sum(late),
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
        ["student", "email", "attended", "late", "of"]
        + [
            _safe(f"{c.starts_at:%Y-%m-%d} {c.title}" if c.starts_at else c.title)
            for c in attendance.classes
        ]
    )
    for row in attendance.students:
        writer.writerow(
            [_safe(row.name), _safe(row.email), row.attended, row.late_count, len(row.classes)]
            + [
                ("late" if late else "present") if mark else "absent"
                for mark, late in zip(
                    row.classes, row.late or [False] * len(row.classes), strict=True
                )
            ]
        )
    return "﻿" + out.getvalue()


def _safe(text: str) -> str:
    """A cell a spreadsheet will not run as a formula."""
    return "'" + text if text.lstrip()[:1] in ("=", "+", "-", "@") else text
