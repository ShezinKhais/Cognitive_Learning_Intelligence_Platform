"""Session membership and ownership checks.

Owner: Cyber 1, Phase 3. A valid JWT proves identity, not that its holder
belongs to a particular live session -- this is the check ws.py's Phase 1
placeholder deferred ("fails closed when a specific session is requested")
and that sessions.py's REST routes need for the same reason content.py's
question ownership does: role alone lets any lecturer act on any session.
"""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.session import Session as SessionModel
from app.models.student import Student
from app.repositories.session_repository import SessionRepository
from app.schemas.identity import Role


async def session_membership_allowed(
    db: AsyncSession,
    session_row: SessionModel,
    *,
    user_id: uuid.UUID,
    role: Role,
) -> bool:
    """Whether `user_id` may join or act on this session's live event stream.

    Admins bypass the check, same as every other ownership guard in this
    codebase. A lecturer must be the session's instructor. A student must be
    enrolled in the session's course -- enrolment, not attendance, since this
    is what decides whether they may *join* at all.
    """
    if role == Role.ADMIN:
        return True
    if role == Role.LECTURER:
        return session_row.instructor_id == user_id
    if role == Role.STUDENT:
        result = await db.execute(
            select(Student.student_id).where(
                Student.user_id == user_id,
                Student.course_id == session_row.course_id,
            )
        )
        return result.first() is not None
    return False


async def is_session_owner(
    session_repo: SessionRepository,
    session_id: uuid.UUID,
    *,
    user_id: uuid.UUID,
    role: Role,
) -> SessionModel | None:
    """Fetch a session the caller is allowed to manage (start/end/deliver), or
    None if it does not exist or they don't own it. Admins own everything."""
    row = await session_repo.get_by_id(session_id)
    if row is None:
        return None
    if role == Role.ADMIN or row.instructor_id == user_id:
        return row
    return None
