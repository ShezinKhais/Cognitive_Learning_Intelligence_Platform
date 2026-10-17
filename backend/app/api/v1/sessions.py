"""Live session, response and analytics routes.

Contract frozen in Phase 1; pause and resume were added in Phase 3. Handler
bodies are owned by:
  General CS: session lifecycle, question delivery
  BBIS:       persistence and dashboard queries
  AI 1:       scoring and classification
  Cyber 1:    engagement scoring, alerts
"""

from __future__ import annotations

from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request, status

from app.api.deps import (
    AppSettings,
    CurrentUser,
    DbSession,
    Paginated,
    require_consents,
    require_roles,
)
from app.auth.service import granted_consents
from app.core.audit import audit_action
from app.core.errors import NotFoundError
from app.realtime.classroom import classroom
from app.repositories.session_repository import SessionRepository
from app.repositories.student_repository import StudentRepository
from app.repositories.topic_difficulty_repository import DatabaseTopicAnswers
from app.schemas.common import Page
from app.schemas.identity import ConsentType, Role
from app.schemas.session import (
    AlertOut,
    DeliverableQuestionOut,
    EngagementOut,
    ResponseOut,
    SessionCreateRequest,
    SessionOut,
    SessionReadinessOut,
    SessionStatus,
    StudentSessionSummary,
    TopicDifficultyOut,
)
from app.services import alert_store, session_lifecycle, session_reads
from app.services.engagement_view import staff_confidence, staff_score, staff_signals
from app.services.session_access import may_view_session_analytics
from app.services.student_report import build_student_summary, record_staff_view

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
@audit_action("SESSION_CREATED")
async def create_session(
    payload: SessionCreateRequest,
    principal: CurrentUser,
    request: Request,
    settings: AppSettings,
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
    """The caller's sessions, newest first: a lecturer's own, a student's
    courses', or every session for an admin."""
    return await session_reads.list_sessions(db, principal, page.limit, page.offset)


@router.get("/{session_id}", response_model=SessionOut)
async def get_session(
    session_id: UUID,
    principal: CurrentUser,
    db: DbSession,
) -> SessionOut:
    return await session_reads.get_session(db, principal, session_id)


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


@router.get(
    "/{session_id}/readiness",
    response_model=SessionReadinessOut,
    dependencies=_staff,
)
async def session_readiness(
    session_id: UUID,
    principal: CurrentUser,
    db: DbSession,
) -> SessionReadinessOut:
    """What the session has to deliver: its material and staged questions.
    Each issue is a warning; none of them stops the session from starting."""
    return await session_lifecycle.session_readiness(db, principal, session_id)


@router.post("/{session_id}/start", response_model=SessionOut, dependencies=_staff)
@audit_action("SESSION_STARTED")
async def start_session(
    session_id: UUID,
    principal: CurrentUser,
    request: Request,
    settings: AppSettings,
    db: DbSession,
) -> SessionOut:
    """Blocked until the session is ready. GET /readiness says why it is not."""
    return await session_lifecycle.start_session(db, principal, session_id)


@router.post("/{session_id}/pause", response_model=SessionOut, dependencies=_staff)
@audit_action("SESSION_PAUSED")
async def pause_session(
    session_id: UUID,
    principal: CurrentUser,
    request: Request,
    settings: AppSettings,
    db: DbSession,
) -> SessionOut:
    """Holds the question cycle of an active session until it resumes. A question
    already open runs to the end of its window."""
    return await session_lifecycle.pause_session(db, principal, session_id)


@router.post("/{session_id}/resume", response_model=SessionOut, dependencies=_staff)
@audit_action("SESSION_RESUMED")
async def resume_session(
    session_id: UUID,
    principal: CurrentUser,
    request: Request,
    settings: AppSettings,
    db: DbSession,
) -> SessionOut:
    """Resumes a paused session. The next scheduled question comes after whatever
    was left of the wait when it paused."""
    return await session_lifecycle.resume_session(db, principal, session_id)


@router.post("/{session_id}/end", response_model=SessionOut, dependencies=_staff)
@audit_action("SESSION_ENDED")
async def end_session(
    session_id: UUID,
    principal: CurrentUser,
    request: Request,
    settings: AppSettings,
    db: DbSession,
) -> SessionOut:
    """Ends an active session, or cancels one that has not started."""
    return await session_lifecycle.end_session(db, principal, session_id)


@router.post(
    "/{session_id}/questions/{question_id}:deliver",
    status_code=status.HTTP_202_ACCEPTED,
    dependencies=_staff,
)
@audit_action("QUESTION_DELIVERED")
async def deliver_question(
    session_id: UUID,
    question_id: UUID,
    principal: CurrentUser,
    request: Request,
    settings: AppSettings,
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
    """Every response in the session for its lecturer or an admin, and a
    student's own for a student."""
    return await session_reads.list_responses(db, principal, session_id, page.limit, page.offset)


@router.get("/{session_id}/engagement", response_model=list[EngagementOut], dependencies=_staff)
async def session_engagement(
    session_id: UUID,
    principal: CurrentUser,
    db: DbSession,
) -> list[EngagementOut]:
    """Engagement only. Comprehension is served separately and the two are never
    combined into one figure. Scores live with the running session, so a
    session this process is not running reports none."""
    await require_analytics_access(db, principal, session_id)
    scored = classroom.engagement(session_id)
    # The classroom knows students by user id; the contract speaks in
    # student.student_id, the id ResponseOut and the student table use.
    student_ids = await StudentRepository(db).student_ids_by_user([s.user_id for s in scored])
    return [
        EngagementOut(
            student_id=student_ids[s.user_id],
            session_id=session_id,
            score=staff_score(s.engagement.score),
            status=s.engagement.status,
            # The same view for every student: see services/engagement_view.py.
            confidence=staff_confidence(s.engagement.signals_available),
            signals_available=staff_signals(s.engagement.signals_available),
            computed_at=s.scored_at,
        )
        for s in scored
        if s.user_id in student_ids
    ]


@router.get("/{session_id}/alerts", response_model=list[AlertOut], dependencies=_staff)
async def session_alerts(
    session_id: UUID,
    principal: CurrentUser,
    db: DbSession,
    status_filter: Annotated[
        Literal["open", "acknowledged"] | None,
        Query(alias="status", description="Only the alerts in this state."),
    ] = None,
) -> list[AlertOut]:
    """The alerts raised in a session, oldest first, with why, what to do about
    them and whether a lecturer has acknowledged them.

    Read from the stored alerts, so it works during and after a session and
    after a refresh."""
    await require_analytics_access(db, principal, session_id)
    return await alert_store.list_session_alerts(db, session_id, status=status_filter)


@router.post(
    "/{session_id}/alerts/{alert_id}/acknowledge",
    response_model=AlertOut,
    dependencies=_staff,
)
@audit_action("ALERT_ACKNOWLEDGED")
async def acknowledge_session_alert(
    session_id: UUID,
    alert_id: UUID,
    principal: CurrentUser,
    request: Request,
    settings: AppSettings,
    db: DbSession,
) -> AlertOut:
    """Mark an alert as seen. The lecturer who runs the session, or an admin.

    The first acknowledgement is kept: acknowledging an alert again, as
    anyone, returns it unchanged. An alert from another session is reported as
    missing."""
    await require_analytics_access(db, principal, session_id)
    return await alert_store.acknowledge_session_alert(db, session_id, alert_id, principal.user_id)


@router.get("/{session_id}/topics", response_model=list[TopicDifficultyOut], dependencies=_staff)
async def session_topics(
    session_id: UUID,
    principal: CurrentUser,
    db: DbSession,
) -> list[TopicDifficultyOut]:
    """How hard the class found each topic, hardest first. Read from stored
    comprehension labels, so it works during and after a session. Topics with
    too few answers for a level come last."""
    await require_analytics_access(db, principal, session_id)
    topics = await DatabaseTopicAnswers(db).session_topics(session_id)
    return [TopicDifficultyOut.model_validate(topic) for topic in topics]


async def require_analytics_access(db: DbSession, principal: CurrentUser, session_id: UUID) -> None:
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
    settings: AppSettings,
    request: Request,
) -> StudentSessionSummary:
    """One student's results for one session: what they attempted and missed,
    where their answers were strong or weak, and what to do next. Engagement
    and comprehension are separate fields and never combined.

    A student reads only their own; staff read those of a session they run
    (and leave an audit trace when it is not their own). A session, a student
    or a pairing the caller may not see are all the same 404."""
    row = await SessionRepository(db).get(session_id)
    student = await StudentRepository(db).get_by_id(student_id)
    own = student is not None and student.user_id == principal.user_id
    allowed = (
        row is not None
        and student is not None
        and student.course_id == row.course_id
        # A post-session summary (REQ-1.10): nothing is served while the class
        # is still prepared or running, and the refusal is the same 404.
        and row.status == SessionStatus.ENDED.value
        and (
            own
            if principal.role == Role.STUDENT
            else may_view_session_analytics(row, user_id=principal.user_id, role=principal.role)
        )
    )
    if not allowed or student is None:
        raise NotFoundError("Summary was not found.", {"session_id": str(session_id)})
    consented = ConsentType.ENGAGEMENT_MONITORING in await granted_consents(
        student.user_id, settings, db
    )
    summary = await build_student_summary(
        db, session_id, student_id, student.user_id, engagement_consented=consented
    )
    if not own:
        await record_staff_view(
            db,
            viewer=principal.user_id,
            student_id=student_id,
            session_id=session_id,
            ip_address=request.client.host if request.client is not None else "unknown",
        )
    return summary
