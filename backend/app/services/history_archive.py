"""Archiving sessions into the history database before they are purged.

Owner: BBIS, Phase 7. For each session about to be deleted, what each student
did in it is added to their summary for that course and semester: sessions
attended, questions attempted and correct, and engagement and gaze as sums and
counts. Only counts and averages-to-be: no answers, no free text, no names.

A session is added once. Its id is recorded in the history database in the same
transaction, so a purge that is retried after a failure adds nothing twice.

Reads the main database; writes the history database. The caller commits the
history transaction before it deletes anything from the main one.
"""

from __future__ import annotations

from collections import defaultdict
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.history.models import ArchivedSession
from app.history.repository import SemesterTotals, add_totals, semester_label
from app.models.attention_signal_summary import AttentionSignalSummary
from app.models.engagement_record import EngagementRecord
from app.models.session import Session
from app.models.session_participant import SessionParticipant
from app.models.student_response import StudentResponse
from app.services.retention import session_clock


async def archive_sessions(
    db: AsyncSession, history_db: AsyncSession, session_ids: list[UUID]
) -> int:
    """Add these sessions to the summaries. Returns how many summary rows were
    touched. Sessions already archived are skipped."""
    already = set(
        await history_db.scalars(
            select(ArchivedSession.session_id).where(ArchivedSession.session_id.in_(session_ids))
        )
    )
    todo = [session_id for session_id in session_ids if session_id not in already]
    if not todo:
        return 0

    where = {
        row.session_id: (row.course_id, semester_label(row.clock))
        for row in await db.execute(
            select(Session.session_id, Session.course_id, session_clock().label("clock")).where(
                Session.session_id.in_(todo)
            )
        )
    }

    summary: dict[tuple[UUID, UUID, str], dict[str, float]] = defaultdict(
        lambda: defaultdict(float)
    )
    attended: set[tuple[UUID, UUID]] = set()

    def row_for(session_id: UUID, student_id: UUID) -> dict[str, float]:
        course_id, semester = where[session_id]
        attended.add((session_id, student_id))
        return summary[(student_id, course_id, semester)]

    # Attendance is what the attendance table says. A student who joined but
    # declined monitoring and never answered still attended: they get a row with
    # zero answers and no engagement, not no row.
    attendance = await db.execute(
        select(SessionParticipant.session_id, SessionParticipant.student_id).where(
            SessionParticipant.session_id.in_(todo)
        )
    )
    for session_id, student_id in attendance:
        row_for(session_id, student_id)

    answers = await db.execute(
        select(
            StudentResponse.session_id,
            StudentResponse.student_id,
            func.count(),
            func.count().filter(StudentResponse.is_correct.is_(True)),
        )
        .where(StudentResponse.session_id.in_(todo))
        .group_by(StudentResponse.session_id, StudentResponse.student_id)
    )
    for session_id, student_id, attempted, correct in answers:
        row = row_for(session_id, student_id)
        row["questions_attempted"] += attempted
        row["questions_correct"] += correct

    engagement = await db.execute(
        select(
            EngagementRecord.session_id,
            EngagementRecord.student_id,
            func.sum(EngagementRecord.engagement_score),
            func.count(),
        )
        .where(EngagementRecord.session_id.in_(todo))
        .group_by(EngagementRecord.session_id, EngagementRecord.student_id)
    )
    for session_id, student_id, total, count in engagement:
        row = row_for(session_id, student_id)
        row["engagement_sum"] += total or 0.0
        row["engagement_count"] += count

    gaze = await db.execute(
        select(
            AttentionSignalSummary.session_id,
            AttentionSignalSummary.student_id,
            func.sum(AttentionSignalSummary.gaze_on_screen_ratio),
            func.count(AttentionSignalSummary.gaze_on_screen_ratio),
        )
        .where(AttentionSignalSummary.session_id.in_(todo))
        .group_by(AttentionSignalSummary.session_id, AttentionSignalSummary.student_id)
    )
    for session_id, student_id, total, count in gaze:
        row = row_for(session_id, student_id)
        row["gaze_sum"] += total or 0.0
        row["gaze_count"] += count

    for session_id, student_id in attended:
        course_id, semester = where[session_id]
        summary[(student_id, course_id, semester)]["sessions_attended"] += 1

    await add_totals(
        history_db,
        [
            SemesterTotals(
                student_id=student_id,
                course_id=course_id,
                semester=semester,
                sessions_attended=int(row["sessions_attended"]),
                questions_attempted=int(row["questions_attempted"]),
                questions_correct=int(row["questions_correct"]),
                engagement_sum=row["engagement_sum"],
                engagement_count=int(row["engagement_count"]),
                gaze_sum=row["gaze_sum"],
                gaze_count=int(row["gaze_count"]),
            )
            for (student_id, course_id, semester), row in summary.items()
        ],
    )
    history_db.add_all([ArchivedSession(session_id=session_id) for session_id in todo])
    await history_db.flush()
    return len(summary)
