"""AI2's own-student review UI adapter; the Cyber 1 summary route is untouched."""

from uuid import UUID

from fastapi import APIRouter, Depends, Response

from app.api.deps import CurrentUser, DbSession, Paginated, require_consents, require_roles
from app.schemas.common import Page
from app.schemas.identity import ConsentType, Role
from app.schemas.student_review import ReviewSession, ReviewSources, StudentReview
from app.services import student_review

router = APIRouter(
    prefix="/student-reviews",
    tags=["student-review"],
    dependencies=[
        Depends(require_roles(Role.STUDENT)),
        Depends(require_consents(ConsentType.TERMS)),
    ],
)


@router.get("", response_model=Page[ReviewSession])
async def list_reviews(principal: CurrentUser, db: DbSession, page: Paginated, response: Response):
    response.headers["Cache-Control"] = "no-store"
    return await student_review.list_reviews(db, principal.user_id, page.limit, page.offset)


@router.get("/{session_id}", response_model=StudentReview)
async def review(
    session_id: UUID, principal: CurrentUser, db: DbSession, page: Paginated, response: Response
):
    response.headers["Cache-Control"] = "no-store"
    return await student_review.read_review(
        db, principal.user_id, session_id, page.limit, page.offset
    )


@router.get("/{session_id}/responses/{response_id}/sources", response_model=ReviewSources)
async def sources(
    session_id: UUID, response_id: UUID, principal: CurrentUser, db: DbSession, response: Response
):
    response.headers["Cache-Control"] = "no-store"
    return await student_review.read_sources(db, principal.user_id, session_id, response_id)
