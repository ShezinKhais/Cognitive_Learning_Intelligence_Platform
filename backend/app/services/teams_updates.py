"""The lecturer's Teams update pop-up: what it lists, and muting it.

Owner: General CS, Phase 8. The updates themselves are held in memory by
teams_notifications for the length of the class, since they only describe
the class while it runs. Only the session's lecturer, or an admin, may read
or mute them.
"""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import Principal
from app.core.config import Settings
from app.models.student import Student
from app.models.teams_user_mapping import TeamsUserMapping
from app.models.user import User
from app.repositories.session_repository import SessionRepository
from app.schemas.meetings import LecturerUpdateOut, TeamsUpdatesOut
from app.services.course_membership import students_on
from app.services.session_lifecycle import owned_session
from app.services.teams_notifications import notifications


async def updates(
    db: AsyncSession, principal: Principal, session_id: UUID, settings: Settings
) -> TeamsUpdatesOut:
    row = await owned_session(SessionRepository(db), principal, session_id, for_update=False)
    on_course = (
        select(Student.user_id)
        .join(User, User.user_id == Student.user_id)
        .where(Student.student_id.in_(students_on(row.course_id)), User.active.is_(True))
    )
    students = await db.scalar(select(func.count()).select_from(on_course.subquery())) or 0
    in_teams = None
    if settings.teams_notifications_enabled:
        in_teams = (
            await db.scalar(
                select(func.count(func.distinct(TeamsUserMapping.user_id))).where(
                    TeamsUserMapping.tenant_id == settings.tenant_id,
                    TeamsUserMapping.user_id.in_(on_course),
                )
            )
            or 0
        )
    muted, recent = notifications.recent_updates(session_id)
    return TeamsUpdatesOut(
        muted=muted,
        updates=[LecturerUpdateOut(at=u.at, kind=u.kind, text=u.text) for u in recent],
        students_on_course=students,
        students_in_teams=in_teams,
    )


async def mute(
    db: AsyncSession, principal: Principal, session_id: UUID, muted: bool, settings: Settings
) -> TeamsUpdatesOut:
    await owned_session(SessionRepository(db), principal, session_id, for_update=False)
    notifications.mute(session_id, muted)
    return await updates(db, principal, session_id, settings)
