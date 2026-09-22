"""Live session, response and analytics routes.

Contract frozen in Phase 1; pause and resume were added in Phase 3. Handler
bodies are owned by:
  General CS: session lifecycle, question delivery
  BBIS:       persistence and dashboard queries
  AI 1:       scoring and classification
  Cyber 1:    engagement scoring, alerts
"""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, status

from app.api.deps import (
    CurrentUser,
    DbSession,
    Paginated,
    require_consents,
    require_roles,
)
from app.core.errors import not_implemented
from app.schemas.common import Page
from app.schemas.identity import ConsentType, Role
from app.schemas.session import (
    ClassComprehensionAlert,
    EngagementOut,
    ResponseOut,
    SessionCreateRequest,
    SessionOut,
    StudentSessionSummary,
)
from app.services import session_lifecycle

# Running a session is staff work. Students reach a session over the socket.
_staff = [Depends(require_roles(Role.LECTURER, Role.ADMIN))]

router = APIRouter(
    prefix="/sessions",
    tags=["sessions"],
    dependencies=[
        Depends(require_consents(ConsentType.TERMS)),
    ],
)


@router.post(
    "",
    response_model=SessionOut,
    status_code=status.HTTP_201_CREATED,
    dependencies=_staff,
)
async def create_session(
    payload: SessionCreateRequest,
    principal: CurrentUser,
    db: DbSession,
) -> SessionOut:
    """Prepare a session for a course. It starts once questions are staged."""
    return await session_lifecycle.create_session(db, principal, payload)


@router.get("", response_model=Page[SessionOut])
async def list_sessions(
    principal: CurrentUser,
    db: DbSession,
    page: Paginated,
) -> Page[SessionOut]:
    raise not_implemented("BBIS", "Phase 3")


@router.get("/{session_id}", response_model=SessionOut)
async def get_session(
    session_id: UUID,
    principal: CurrentUser,
    db: DbSession,
) -> SessionOut:
    raise not_implemented("BBIS", "Phase 3")


@router.post("/{session_id}/start", response_model=SessionOut, dependencies=_staff)
async def start_session(
    session_id: UUID,
    principal: CurrentUser,
    db: DbSession,
) -> SessionOut:
    """Blocked until the session has approved questions staged."""
    return await session_lifecycle.start_session(db, principal, session_id)


@router.post("/{session_id}/pause", response_model=SessionOut, dependencies=_staff)
async def pause_session(
    session_id: UUID,
    principal: CurrentUser,
    db: DbSession,
) -> SessionOut:
    """Holds the question cycle of an active session until it resumes. A question
    already open runs to the end of its window."""
    return await session_lifecycle.pause_session(db, principal, session_id)


@router.post("/{session_id}/resume", response_model=SessionOut, dependencies=_staff)
async def resume_session(
    session_id: UUID,
    principal: CurrentUser,
    db: DbSession,
) -> SessionOut:
    """Resumes a paused session. The next scheduled question comes after whatever
    was left of the wait when it paused."""
    return await session_lifecycle.resume_session(db, principal, session_id)


@router.post("/{session_id}/end", response_model=SessionOut, dependencies=_staff)
async def end_session(
    session_id: UUID,
    principal: CurrentUser,
    db: DbSession,
) -> SessionOut:
    """Ends an active session, or cancels one that has not started."""
    return await session_lifecycle.end_session(db, principal, session_id)


@router.post(
    "/{session_id}/questions/{question_id}:deliver",
    status_code=status.HTTP_202_ACCEPTED,
    dependencies=_staff,
)
async def deliver_question(
    session_id: UUID,
    question_id: UUID,
    principal: CurrentUser,
    db: DbSession,
) -> dict[str, str]:
    """Lecturer's manual trigger. The scheduler uses the same internal path."""
    return await session_lifecycle.deliver_question(db, principal, session_id, question_id)


@router.get("/{session_id}/responses", response_model=Page[ResponseOut])
async def list_responses(
    session_id: UUID,
    principal: CurrentUser,
    db: DbSession,
    page: Paginated,
) -> Page[ResponseOut]:
    raise not_implemented("BBIS", "Phase 3")


@router.get("/{session_id}/engagement", response_model=list[EngagementOut])
async def session_engagement(
    session_id: UUID,
    principal: CurrentUser,
    db: DbSession,
) -> list[EngagementOut]:
    """Engagement only. Comprehension is served separately and the two are never
    combined into one figure."""
    raise not_implemented("Cyber 1", "Phase 3")


@router.get("/{session_id}/alerts", response_model=list[ClassComprehensionAlert])
async def session_alerts(
    session_id: UUID,
    principal: CurrentUser,
    db: DbSession,
) -> list[ClassComprehensionAlert]:
    raise not_implemented("Cyber 1", "Phase 3")


@router.get(
    "/{session_id}/summary/{student_id}",
    response_model=StudentSessionSummary,
)
async def student_summary(
    session_id: UUID,
    student_id: UUID,
    principal: CurrentUser,
    db: DbSession,
) -> StudentSessionSummary:
    raise not_implemented("Cyber 1", "Phase 7")
