"""Engagement across a term, for the lecturer who taught it, or an admin.

Owner: General CS.

Each finished class gets a row: who joined, how many checkpoints were sent,
how much of what could have been answered was, and how much of it was right.
The attention average is shown only when at least three students turned the
indicator on, so one student's reading can never be picked out of it.

The quiet list looks at the last RECENT_WINDOW finished classes of each
course. A student is listed when they missed most of them, or answered less
than QUIET_ANSWER_RATE of the checkpoints in the ones they joined. It is a
prompt to check in, not a mark: a student with an approved special
consideration is never listed, as the consideration page promises, and the
list is only ever shown to the course's lecturer and to admins.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import date
from uuid import UUID

from sqlalchemy import Float, case, cast, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.attention_signal_summary import AttentionSignalSummary
from app.models.consideration_request import ConsiderationRequest
from app.models.course import Course
from app.models.delivered_question import DeliveredQuestion
from app.models.session import Session
from app.models.session_participant import SessionParticipant
from app.models.student import Student
from app.models.student_response import StudentResponse
from app.models.user import User
from app.schemas.engagement_history import EngagementHistory, QuietStudent, SessionEngagement

RECENT_WINDOW = 4
QUIET_ANSWER_RATE = 0.4
MIN_ATTENTION_STUDENTS = 3
MAX_SESSIONS = 100


def is_quiet(considered: int, missed: int, checkpoints: int, answered: int) -> bool:
    """Missed most of the recent classes, or answered little in those joined."""
    if considered < 2:
        return False
    if missed * 2 > considered:
        return True
    return checkpoints >= 3 and answered / checkpoints < QUIET_ANSWER_RATE


def _ratio(part: int | float | None, whole: int | float | None) -> float | None:
    if not whole:
        return None
    return round(float(part or 0) / float(whole), 3)


async def engagement_history(
    db: AsyncSession, *, instructor_id: UUID | None, course_id: UUID | None
) -> EngagementHistory:
    """instructor_id None means every lecturer's classes (an admin)."""
    conditions = [Session.status == "ended"]
    if instructor_id is not None:
        conditions.append(Session.instructor_id == instructor_id)
    if course_id is not None:
        conditions.append(Session.course_id == course_id)

    finished = (
        await db.execute(
            select(
                Session.session_id,
                Session.title,
                Session.start_time,
                Session.course_id,
                Course.code,
            )
            .join(Course, Course.id == Session.course_id)
            .where(*conditions)
            .order_by(Session.start_time.desc())
            .limit(MAX_SESSIONS)
        )
    ).all()
    ids = [row.session_id for row in finished]
    if not ids:
        return EngagementHistory(sessions=[], quiet=[], recent_window=RECENT_WINDOW)

    present = dict(
        (
            await db.execute(
                select(
                    SessionParticipant.session_id,
                    func.count(func.distinct(SessionParticipant.student_id)),
                )
                .where(SessionParticipant.session_id.in_(ids))
                .group_by(SessionParticipant.session_id)
            )
        ).all()
    )
    checkpoints = {
        row.session_id: row
        for row in (
            await db.execute(
                select(
                    DeliveredQuestion.session_id,
                    func.count().label("sent"),
                    func.sum(DeliveredQuestion.eligible_count).label("eligible"),
                    func.sum(DeliveredQuestion.respondent_count).label("answered"),
                )
                .where(DeliveredQuestion.session_id.in_(ids))
                .group_by(DeliveredQuestion.session_id)
            )
        ).all()
    }
    marking = {
        row.session_id: row
        for row in (
            await db.execute(
                select(
                    StudentResponse.session_id,
                    func.count(StudentResponse.is_correct).label("marked"),
                    func.sum(case((StudentResponse.is_correct.is_(True), 1), else_=0)).label(
                        "right"
                    ),
                )
                .where(StudentResponse.session_id.in_(ids))
                .group_by(StudentResponse.session_id)
            )
        ).all()
    }
    per_student = (
        select(
            AttentionSignalSummary.session_id,
            AttentionSignalSummary.student_id,
            func.avg(AttentionSignalSummary.gaze_on_screen_ratio).label("ratio"),
        )
        .where(
            AttentionSignalSummary.session_id.in_(ids),
            AttentionSignalSummary.gaze_on_screen_ratio.is_not(None),
        )
        .group_by(AttentionSignalSummary.session_id, AttentionSignalSummary.student_id)
        .subquery()
    )
    attention = {
        row.session_id: row
        for row in (
            await db.execute(
                select(
                    per_student.c.session_id,
                    func.count().label("students"),
                    func.avg(cast(per_student.c.ratio, Float)).label("ratio"),
                ).group_by(per_student.c.session_id)
            )
        ).all()
    }

    sessions = []
    for row in finished:
        sent = checkpoints.get(row.session_id)
        marked = marking.get(row.session_id)
        watched = attention.get(row.session_id)
        sessions.append(
            SessionEngagement(
                session_id=row.session_id,
                title=row.title,
                course_code=row.code,
                held_at=row.start_time,
                present=int(present.get(row.session_id, 0)),
                checkpoints=int(sent.sent) if sent else 0,
                answer_rate=_ratio(sent.answered, sent.eligible) if sent else None,
                correct_rate=_ratio(marked.right, marked.marked) if marked else None,
                on_screen=(
                    round(float(watched.ratio), 3)
                    if watched
                    and watched.students >= MIN_ATTENTION_STUDENTS
                    and watched.ratio is not None
                    else None
                ),
            )
        )

    quiet = await _quiet_students(db, finished, checkpoints)
    return EngagementHistory(sessions=sessions, quiet=quiet, recent_window=RECENT_WINDOW)


async def _quiet_students(db: AsyncSession, finished, checkpoints) -> list[QuietStudent]:
    recent: dict[UUID, list[UUID]] = defaultdict(list)
    codes: dict[UUID, str] = {}
    for row in finished:  # newest first
        if len(recent[row.course_id]) < RECENT_WINDOW:
            recent[row.course_id].append(row.session_id)
            codes[row.course_id] = row.code
    window = [session_id for ids in recent.values() for session_id in ids]

    today = date.today()
    accommodated = (
        select(ConsiderationRequest.student_id)
        .where(
            ConsiderationRequest.status == "approved",
            or_(ConsiderationRequest.until.is_(None), ConsiderationRequest.until >= today),
        )
        .scalar_subquery()
    )
    roster = (
        await db.execute(
            select(Student.student_id, Student.course_id, User.name)
            .join(User, User.user_id == Student.user_id)
            .where(
                Student.course_id.in_(list(recent)),
                User.active.is_(True),
                Student.student_id.not_in(accommodated),
            )
        )
    ).all()
    joined = {
        (row.session_id, row.student_id)
        for row in (
            await db.execute(
                select(SessionParticipant.session_id, SessionParticipant.student_id)
                .where(SessionParticipant.session_id.in_(window))
                .distinct()
            )
        ).all()
    }
    answers = dict(
        (
            (row.session_id, row.student_id),
            int(row.count),
        )
        for row in (
            await db.execute(
                select(
                    StudentResponse.session_id,
                    StudentResponse.student_id,
                    func.count(func.distinct(StudentResponse.question_id)).label("count"),
                )
                .where(StudentResponse.session_id.in_(window))
                .group_by(StudentResponse.session_id, StudentResponse.student_id)
            )
        ).all()
    )

    quiet = []
    for student in roster:
        considered = recent[student.course_id]
        missed = sum(1 for sid in considered if (sid, student.student_id) not in joined)
        attended = [sid for sid in considered if (sid, student.student_id) in joined]
        possible = sum(int(checkpoints[sid].sent) for sid in attended if sid in checkpoints)
        answered = min(possible, sum(answers.get((sid, student.student_id), 0) for sid in attended))
        if is_quiet(len(considered), missed, possible, answered):
            quiet.append(
                QuietStudent(
                    student_id=student.student_id,
                    name=student.name,
                    course_code=codes[student.course_id],
                    sessions_considered=len(considered),
                    sessions_missed=missed,
                    answer_rate=_ratio(answered, possible),
                )
            )
    return sorted(
        quiet, key=lambda q: (q.course_code, -q.sessions_missed, q.answer_rate or 0, q.name)
    )
