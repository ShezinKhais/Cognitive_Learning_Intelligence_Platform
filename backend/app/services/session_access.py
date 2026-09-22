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
from app.schemas.session import SessionStatus

# Sessions that may still be joined. A session that has ended or was
# cancelled has no live stream left to join, regardless of who is asking --
# enrolment and ownership answer "does this person belong to this session,"
# not "is there still something here to join." The branch that adds
# session_lifecycle (not yet on this branch) will need an equivalent
# JOINABLE set of its own for start/pause/end transitions -- whoever merges
# the two should double-check those sets stay in sync, since nothing here
# enforces that.
JOINABLE_STATUSES = {SessionStatus.PREPARED.value, SessionStatus.ACTIVE.value}


async def session_membership_allowed(
    db: AsyncSession,
    session_row: SessionModel,
    *,
    user_id: uuid.UUID,
    role: Role,
) -> bool:
    """Whether `user_id` may join or act on this session's live event stream.

    A session that isn't prepared or active has no stream to join, and this
    is checked before role -- an admin does not get to join a stream that no
    longer exists. Otherwise: a lecturer must be the session's instructor. A
    student must be enrolled in the session's course -- enrolment, not
    attendance, since this is what decides whether they may *join* at all.
    """
    if session_row.status not in JOINABLE_STATUSES:
        return False
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


# Deliberately no `is_session_owner` here. Lifecycle transitions (start,
# pause, end, deliver) need the session row locked (`SELECT ... FOR UPDATE`)
# to be race-free against a concurrent transition; a plain `db.get` lookup
# cannot provide that, so an ownership check for those actions belongs to
# whichever module already holds the row locked for the transition, not to
# this policy module.
