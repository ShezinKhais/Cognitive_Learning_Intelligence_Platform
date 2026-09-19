"""Session membership and ownership checks.

Owner: Cyber 1, Phase 3. A valid JWT proves identity, not that its holder
belongs to a particular live session -- ws.py's Phase 1 placeholder fails
closed for exactly this reason ("authentication proves identity but does not
yet prove session membership"), and the REST session routes need the same
rule applied at the handler level, not just at the socket.

Deliberately built against app.models.session.Session directly rather than
against a BBIS session repository: the repository is General CS/BBIS's own
Phase 3 deliverable and lands on its own branch, but the policy question --
who may join or act on a given session -- is Cyber 1's regardless of which
persistence layer ends up fetching the row. Whichever branch this merges
with wires these functions in; nothing here assumes how the row was found.
"""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.session import Session as SessionModel
from app.models.student import Student
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
    db: AsyncSession,
    session_id: uuid.UUID,
    *,
    user_id: uuid.UUID,
    role: Role,
) -> SessionModel | None:
    """Fetch a session the caller is allowed to manage (start/end/deliver), or
    None if it does not exist or they don't own it. Admins own everything.
    """
    row = await db.get(SessionModel, session_id)
    if row is None:
        return None
    if role == Role.ADMIN or row.instructor_id == user_id:
        return row
    return None
