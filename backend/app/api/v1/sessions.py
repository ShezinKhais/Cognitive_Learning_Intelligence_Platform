"""Live session, response and analytics routes.

Contract frozen in Phase 1. Handler bodies are owned by:
  General CS: session lifecycle, question delivery
  BBIS:       persistence and dashboard queries
  AI 1:       scoring and classification
  Cyber 1:    engagement scoring, alerts
"""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, status

from app.api.deps import CurrentUser, DbSession, Paginated
from app.core.errors import not_implemented
from app.schemas.common import Page
from app.schemas.session import (
    ClassComprehensionAlert,
    EngagementOut,
    ResponseOut,
    SessionCreateRequest,
    SessionOut,
    StudentSessionSummary,
)

router = APIRouter(prefix="/sessions", tags=["sessions"])


@router.post("", response_model=SessionOut, status_code=status.HTTP_201_CREATED)
async def create_session(
    payload: SessionCreateRequest, principal: CurrentUser, db: DbSession
) -> SessionOut:
    raise not_implemented("General CS", "Phase 3")


@router.get("", response_model=Page[SessionOut])
async def list_sessions(principal: CurrentUser, db: DbSession, page: Paginated) -> Page[SessionOut]:
    raise not_implemented("BBIS", "Phase 3")


@router.get("/{session_id}", response_model=SessionOut)
async def get_session(session_id: UUID, principal: CurrentUser, db: DbSession) -> SessionOut:
    raise not_implemented("BBIS", "Phase 3")


@router.post("/{session_id}/start", response_model=SessionOut)
async def start_session(session_id: UUID, principal: CurrentUser, db: DbSession) -> SessionOut:
    """Blocked until the session has approved questions staged."""
    raise not_implemented("General CS", "Phase 3")


@router.post("/{session_id}/end", response_model=SessionOut)
async def end_session(session_id: UUID, principal: CurrentUser, db: DbSession) -> SessionOut:
    raise not_implemented("General CS", "Phase 3")


@router.post("/{session_id}/questions/{question_id}:deliver", status_code=status.HTTP_202_ACCEPTED)
async def deliver_question(
    session_id: UUID, question_id: UUID, principal: CurrentUser, db: DbSession
) -> dict[str, str]:
    """Lecturer's manual trigger. The scheduler uses the same internal path."""
    raise not_implemented("General CS", "Phase 3")


@router.get("/{session_id}/responses", response_model=Page[ResponseOut])
async def list_responses(
    session_id: UUID, principal: CurrentUser, db: DbSession, page: Paginated
) -> Page[ResponseOut]:
    raise not_implemented("BBIS", "Phase 3")


@router.get("/{session_id}/engagement", response_model=list[EngagementOut])
async def session_engagement(
    session_id: UUID, principal: CurrentUser, db: DbSession
) -> list[EngagementOut]:
    """Engagement only. Comprehension is served separately and the two are never
    combined into one figure."""
    raise not_implemented("Cyber 1", "Phase 3")


@router.get("/{session_id}/alerts", response_model=list[ClassComprehensionAlert])
async def session_alerts(
    session_id: UUID, principal: CurrentUser, db: DbSession
) -> list[ClassComprehensionAlert]:
    raise not_implemented("Cyber 1", "Phase 3")


@router.get("/{session_id}/summary/{student_id}", response_model=StudentSessionSummary)
async def student_summary(
    session_id: UUID, student_id: UUID, principal: CurrentUser, db: DbSession
) -> StudentSessionSummary:
    raise not_implemented("Cyber 1", "Phase 7")
