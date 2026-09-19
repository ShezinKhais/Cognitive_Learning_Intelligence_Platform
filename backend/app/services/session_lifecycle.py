"""Creating, starting and ending a live session, and who may join one.

Owner: General CS, Phase 3.

A session moves prepared -> active -> ended, or prepared -> cancelled when it
is ended before it starts. Every other move is refused with a 409. ENDING is
in the contract for a close that takes time; ending is immediate here, so no
session is ever left in it.

Each change locks the session row, checks the current status, records the new
one and commits before anyone is told, so two lecturers' tabs pressing start
and end at once cannot both succeed, and nobody hears about a change the
database does not have.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import Principal
from app.core.errors import ConflictError, NotFoundError, ValidationError
from app.models.session import Session
from app.realtime.classroom import classroom
from app.realtime.hub import hub
from app.repositories.course_repository import CourseRepository
from app.repositories.session_repository import SessionRepository
from app.repositories.student_repository import StudentRepository
from app.schemas.events import ServerEventType
from app.schemas.identity import Role
from app.schemas.session import SessionCreateRequest, SessionOut, SessionStatus

log = logging.getLogger("clip.sessions")

# How the class is held. Teams sessions arrive with Phase 4.
MODE_IN_PERSON = "in_person"

MAX_TITLE_LENGTH = 200

# Sessions a student or the lecturer may still connect to.
JOINABLE = {SessionStatus.PREPARED.value, SessionStatus.ACTIVE.value}


async def create_session(
    db: AsyncSession, principal: Principal, payload: SessionCreateRequest
) -> SessionOut:
    title = payload.title.strip()
    if not title or len(title) > MAX_TITLE_LENGTH:
        raise ValidationError(
            f"A session title must be 1 to {MAX_TITLE_LENGTH} characters.",
            {"field": "title"},
        )
    course = await CourseRepository(db).get_by_code(payload.course_code.strip())
    if course is None:
        raise NotFoundError("No course has that code.", {"course_code": payload.course_code})

    starts_at = payload.starts_at or datetime.now(UTC)
    if starts_at.tzinfo is None:
        starts_at = starts_at.replace(tzinfo=UTC)

    row = await SessionRepository(db).create(
        instructor_id=principal.user_id,
        course_id=course.id,
        title=title,
        start_time=starts_at,
        status=SessionStatus.PREPARED.value,
        mode=MODE_IN_PERSON,
    )
    return await session_out(db, row)


async def start_session(db: AsyncSession, principal: Principal, session_id: UUID) -> SessionOut:
    """Blocked until the session has a staged question to deliver."""
    repo = SessionRepository(db)
    row = await _owned(repo, principal, session_id)
    _require(row, SessionStatus.PREPARED, "start")
    if not await repo.has_deliverable(row):
        raise ConflictError(
            "Stage at least one approved question before starting the session.",
            {"session_id": str(session_id)},
        )

    row.status = SessionStatus.ACTIVE.value
    await db.commit()

    classroom.activate(row.session_id)
    await hub.broadcast(
        row.session_id,
        ServerEventType.SESSION_STATE,
        classroom.state(row.session_id, SessionStatus.ACTIVE).model_dump(mode="json"),
    )
    log.info("session %s started by %s", session_id, principal.user_id)
    return await session_out(db, row)


async def end_session(db: AsyncSession, principal: Principal, session_id: UUID) -> SessionOut:
    """End a running session, or cancel one that never started."""
    repo = SessionRepository(db)
    row = await _owned(repo, principal, session_id)
    if row.status == SessionStatus.PREPARED.value:
        ended = SessionStatus.CANCELLED
    else:
        _require(row, SessionStatus.ACTIVE, "end")
        ended = SessionStatus.ENDED

    row.status = ended.value
    row.ended_at = datetime.now(UTC)
    await db.commit()

    delivered = await repo.count_delivered(row.session_id)
    await classroom.end(row.session_id, ended, delivered)
    log.info("session %s %s by %s", session_id, ended.value, principal.user_id)
    return await session_out(db, row)


async def deliver_question(
    db: AsyncSession, principal: Principal, session_id: UUID, question_id: UUID
) -> dict[str, str]:
    """The lecturer's manual trigger, through the same path as the cycle."""
    row = await _owned(SessionRepository(db), principal, session_id)
    _require(row, SessionStatus.ACTIVE, "deliver a question in")
    delivered = await classroom.deliver(db, row, question_id)
    if delivered is None:
        raise NotFoundError(
            "That question is not staged for this session.",
            {"question_id": str(question_id)},
        )
    return {"status": "delivered", "question_id": str(question_id)}


async def joinable_session(
    db: AsyncSession, user_id: UUID, role: Role, session_id: UUID
) -> Session | None:
    """The session a socket may join, or None.

    The lecturer who runs it, any admin, and students enrolled on its course,
    while it is prepared or active. A session that does not exist and one the
    caller may not see are refused alike.
    """
    row = await SessionRepository(db).get(session_id)
    if row is None or row.status not in JOINABLE:
        return None
    if role is Role.ADMIN or (role is Role.LECTURER and row.instructor_id == user_id):
        return row
    if role is Role.STUDENT:
        student = await StudentRepository(db).get_by_user_id(user_id)
        if student is not None and student.course_id == row.course_id:
            return row
    return None


async def session_out(db: AsyncSession, row: Session) -> SessionOut:
    repo = SessionRepository(db)
    return SessionOut(
        id=row.session_id,
        course_code=await repo.course_code(row.course_id),
        title=row.title,
        lecturer_id=row.instructor_id,
        status=SessionStatus(row.status),
        starts_at=row.start_time,
        ended_at=row.ended_at,
        participant_count=hub.participant_count(row.session_id),
        questions_delivered=await repo.count_delivered(row.session_id),
    )


async def _owned(repo: SessionRepository, principal: Principal, session_id: UUID) -> Session:
    """The session, locked, if the caller runs it or is an admin.

    Another lecturer's session is reported as missing, as another lecturer's
    material is, so a session id cannot be probed for existence.
    """
    row = await repo.get(session_id, for_update=True)
    if row is None or (not principal.is_(Role.ADMIN) and row.instructor_id != principal.user_id):
        raise NotFoundError("Session was not found.", {"session_id": str(session_id)})
    return row


def _require(row: Session, status: SessionStatus, action: str) -> None:
    if row.status != status.value:
        raise ConflictError(
            f"Cannot {action} a session that is {row.status}.",
            {"current_status": row.status},
        )
