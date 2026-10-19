"""Reading sessions and their responses.

Owner: BBIS, Phase 3, for the queries; the visibility rule is Cyber 1's
(session_access.py). Wired by General CS in Phase 8, where these three
routes were still answering 501.

Who sees what:

- An admin sees every session and every response.
- A lecturer sees the sessions they run, and every response in them.
- A student sees the sessions of the courses they are enrolled in, and only
  their own responses. Another student's answers are never theirs to read.

A session someone may not see is reported as missing, as session_lifecycle
does for another lecturer's session, so a session id cannot be probed.
"""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import Principal
from app.core.errors import NotFoundError
from app.models.session import Session
from app.models.student import Student
from app.models.student_response import StudentResponse
from app.schemas.common import Page
from app.schemas.identity import Role
from app.schemas.session import ResponseOut, SessionOut
from app.services.session_lifecycle import session_out, sessions_out


def _enrolled_in(principal: Principal):  # noqa: ANN202 - a select
    """The courses a student is enrolled in."""
    return select(Student.course_id).where(Student.user_id == principal.user_id)


def _visible(principal: Principal):  # noqa: ANN202 - a where clause, or None for all
    if principal.is_(Role.ADMIN):
        return None
    if principal.is_(Role.LECTURER):
        return Session.instructor_id == principal.user_id
    return Session.course_id.in_(_enrolled_in(principal))


async def list_sessions(
    db: AsyncSession, principal: Principal, limit: int, offset: int
) -> Page[SessionOut]:
    """The caller's sessions, newest first."""
    rule = _visible(principal)
    count = select(func.count()).select_from(Session)
    rows = select(Session).order_by(Session.start_time.desc(), Session.session_id)
    if rule is not None:
        count, rows = count.where(rule), rows.where(rule)
    total = (await db.execute(count)).scalar_one()
    found = (await db.execute(rows.limit(limit).offset(offset))).scalars().all()
    return Page(
        items=await sessions_out(db, list(found)),
        total=total,
        limit=limit,
        offset=offset,
    )


async def visible_session(db: AsyncSession, principal: Principal, session_id: UUID) -> Session:
    """The session, if the caller may see it."""
    query = select(Session).where(Session.session_id == session_id)
    rule = _visible(principal)
    if rule is not None:
        query = query.where(rule)
    row = (await db.execute(query)).scalar_one_or_none()
    if row is None:
        raise NotFoundError("Session was not found.", {"session_id": str(session_id)})
    return row


async def get_session(db: AsyncSession, principal: Principal, session_id: UUID) -> SessionOut:
    return await session_out(db, await visible_session(db, principal, session_id))


async def list_responses(
    db: AsyncSession, principal: Principal, session_id: UUID, limit: int, offset: int
) -> Page[ResponseOut]:
    """The responses in a session the caller may see, in the order they
    arrived. A student is given their own.

    A student's own is_correct is given while the question is still open, on
    purpose: the live feedback.result event has already told them, as soon as
    the answer was stored. What stays withheld until the window closes is the
    correct option, and no response carries that."""
    await visible_session(db, principal, session_id)
    where = [StudentResponse.session_id == session_id]
    if principal.is_(Role.STUDENT):
        where.append(
            StudentResponse.student_id.in_(
                select(Student.student_id).where(Student.user_id == principal.user_id)
            )
        )
    total = (
        await db.execute(select(func.count()).select_from(StudentResponse).where(*where))
    ).scalar_one()
    found = (
        (
            await db.execute(
                select(StudentResponse)
                .where(*where)
                .order_by(StudentResponse.submitted_at, StudentResponse.response_id)
                .limit(limit)
                .offset(offset)
            )
        )
        .scalars()
        .all()
    )
    return Page(
        items=[
            ResponseOut(
                id=row.response_id,
                question_id=row.question_id,
                student_id=row.student_id,
                selected_option=row.selected_option,
                free_text=row.free_text,
                is_correct=row.is_correct,
                elapsed_ms=row.elapsed_ms,
                submitted_at=row.submitted_at,
            )
            for row in found
        ],
        total=total,
        limit=limit,
        offset=offset,
    )
