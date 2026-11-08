"""Engagement across a term.

Owner: General CS. Lecturers see their own classes; admins see everyone's.
"""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends

from app.api.deps import CurrentUser, DbSession, require_consents, require_roles
from app.schemas.engagement_history import EngagementHistory
from app.schemas.identity import ConsentType, Role
from app.services import engagement_history

router = APIRouter(
    prefix="/engagement-history",
    tags=["sessions"],
    dependencies=[
        Depends(require_consents(ConsentType.TERMS)),
        Depends(require_roles(Role.LECTURER, Role.ADMIN)),
    ],
)


@router.get("", response_model=EngagementHistory)
async def get_engagement_history(
    principal: CurrentUser, db: DbSession, course_id: UUID | None = None
) -> EngagementHistory:
    """Each finished class with its attendance and answers, newest first, and
    the students who have gone quiet over the recent ones."""
    return await engagement_history.engagement_history(
        db,
        instructor_id=None if principal.is_(Role.ADMIN) else principal.user_id,
        course_id=course_id,
    )
