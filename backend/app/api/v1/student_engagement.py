"""A student's own engagement history (#243). See app.services.student_engagement."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Response

from app.api.deps import CurrentUser, DbSession, Paginated, require_consents, require_roles
from app.schemas.identity import ConsentType, Role
from app.schemas.student_engagement import StudentEngagementHistory
from app.services import student_engagement

router = APIRouter(
    prefix="/me/engagement-history",
    tags=["student review"],
    dependencies=[
        Depends(require_roles(Role.STUDENT)),
        Depends(require_consents(ConsentType.TERMS)),
    ],
)


@router.get("", response_model=StudentEngagementHistory)
async def my_engagement_history(
    principal: CurrentUser, db: DbSession, page: Paginated, response: Response
) -> StudentEngagementHistory:
    """What was recorded in each of the caller's finished classes, newest first.
    No score; readings only where consented, and never as zero when missing."""
    response.headers["Cache-Control"] = "no-store"
    return await student_engagement.history(db, principal.user_id, page.limit, page.offset)
