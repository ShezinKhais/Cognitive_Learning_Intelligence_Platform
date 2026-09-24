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
from app.core.errors import NotFoundError, not_implemented
from app.realtime.classroom import classroom
from app.repositories.session_repository import SessionRepository
from app.repositories.student_repository import StudentRepository
from app.schemas.common import Page
from app.schemas.identity import ConsentType, Role
from app.schemas.session import (
    ClassComprehensionAlert,
    DeliverableQuestionOut,
    EngagementOut,
    ResponseOut,
    SessionCreateRequest,
    SessionOut,
    StudentSessionSummary,
)
from app.services import session_lifecycle
from app.services.session_access import may_view_session_analytics

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


@router.get(
    "/{session_id}/questions",
    response_model=Page[DeliverableQuestionOut],
    dependencies=_staff,
)
async def list_deliverable_questions(
    session_id: UUID,
    principal: CurrentUser,
    db: DbSession,
    page: Paginated,
) -> Page[DeliverableQuestionOut]:
    """List staged questions that this session may actually deliver."""
    return await session_lifecycle.list_deliverable_questions(
        db,
        principal,
        session_id,
        limit=page.limit,
        offset=page.offset,
    )


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


@router.get("/{session_id}/engagement", response_model=list[EngagementOut], dependencies=_staff)
async def session_engagement(
    session_id: UUID,
    principal: CurrentUser,
    db: DbSession,
) -> list[EngagementOut]:
    """Engagement only. Comprehension is served separately and the two are never
    combined into one figure. Scores live with the running session, so a
    session this process is not running reports none."""
    await _analytics_session(db, principal, session_id)
    scored = classroom.engagement(session_id)
    # The classroom knows students by user id; the contract speaks in
    # student.student_id, the id ResponseOut and the student table use.
    student_ids = await StudentRepository(db).student_ids_by_user([s.user_id for s in scored])
    return [
        EngagementOut(
            student_id=student_ids[s.user_id],
            session_id=session_id,
            score=s.engagement.score,
            status=s.engagement.status,
            confidence=s.engagement.confidence,
            signals_available=s.engagement.signals_available,
            computed_at=s.scored_at,
        )
        for s in scored
        if s.user_id in student_ids
    ]


@router.get(
    "/{session_id}/alerts", response_model=list[ClassComprehensionAlert], dependencies=_staff
)
async def session_alerts(
    session_id: UUID,
    principal: CurrentUser,
    db: DbSession,
) -> list[ClassComprehensionAlert]:
    """Class comprehension alerts raised so far in a running session."""
    await _analytics_session(db, principal, session_id)
    return classroom.alerts(session_id)


async def _analytics_session(db: DbSession, principal: CurrentUser, session_id: UUID) -> None:
    """Another lecturer's session is reported as missing, as it is for the
    lifecycle routes, so a session id cannot be probed for existence."""
    row = await SessionRepository(db).get(session_id)
    if row is None or not may_view_session_analytics(
        row, user_id=principal.user_id, role=principal.role
    ):
        raise NotFoundError("Session was not found.", {"session_id": str(session_id)})


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
