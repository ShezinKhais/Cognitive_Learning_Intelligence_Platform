"""Live session, response and analytics routes.

Contract frozen in Phase 1. Handler bodies are owned by:
  General CS: session lifecycle, question delivery
  BBIS:       persistence and dashboard queries
  AI 1:       scoring and classification
  Cyber 1:    engagement scoring, alerts
"""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, Request, status

from app.api.deps import (
    AppSettings,
    CurrentUser,
    DbSession,
    Paginated,
    require_consents,
    require_roles,
)
from app.core.audit import audit_action
from app.core.errors import ConflictError, NotFoundError, ValidationError
from app.models.session import Session as SessionModel
from app.repositories.course_repository import CourseRepository
from app.repositories.engagement_repository import EngagementRepository
from app.repositories.response_repository import ResponseRepository
from app.repositories.session_repository import SessionRepository
from app.schemas.common import Page
from app.schemas.identity import ConsentType, Role
from app.schemas.session import (
    ClassComprehensionAlert,
    EngagementOut,
    EngagementStatus,
    ResponseOut,
    SessionCreateRequest,
    SessionOut,
    SessionStatus,
    StudentSessionSummary,
)
from app.services.session_access import is_session_owner, session_membership_allowed
from app.services.session_lifecycle import lifecycle

router = APIRouter(
    prefix="/sessions",
    tags=["sessions"],
    dependencies=[
        Depends(require_consents(ConsentType.TERMS)),
    ],
)


def _to_session_out(row: SessionModel, course_code: str, participant_count: int = 0) -> SessionOut:
    return SessionOut(
        id=row.session_id,
        course_code=course_code,
        title=row.title,
        lecturer_id=row.instructor_id,
        status=SessionStatus(row.status),
        starts_at=row.start_time,
        ended_at=row.end_time if row.status in {"ended", "cancelled"} else None,
        teams_meeting_id=row.teams_meeting_id,
        participant_count=participant_count,
    )


@router.post(
    "",
    response_model=SessionOut,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_roles(Role.LECTURER, Role.ADMIN))],
)
@audit_action("SESSION_CREATED")
async def create_session(
    payload: SessionCreateRequest,
    principal: CurrentUser,
    db: DbSession,
    request: Request,
) -> SessionOut:
    course_repo = CourseRepository(db)
    course = await course_repo.get_by_code(payload.course_code)
    if course is None:
        raise NotFoundError(
            "Course was not found.",
            {"course_code": payload.course_code},
        )

    session_repo = SessionRepository(db)
    row = await session_repo.create(
        instructor_id=principal.user_id,
        course_id=course.id,
        title=payload.title,
        starts_at=payload.starts_at,
    )
    return _to_session_out(row, course.code)


@router.get("", response_model=Page[SessionOut])
async def list_sessions(
    principal: CurrentUser,
    db: DbSession,
    page: Paginated,
) -> Page[SessionOut]:
    session_repo = SessionRepository(db)
    instructor_id = principal.user_id if principal.is_(Role.LECTURER) else None
    participant_user_id = principal.user_id if principal.is_(Role.STUDENT) else None

    rows, total = await session_repo.list_page(
        limit=page.limit,
        offset=page.offset,
        instructor_id=instructor_id,
        participant_user_id=participant_user_id,
    )

    items = []
    for row, course_code in rows:
        count = await session_repo.participant_count(row.session_id)
        items.append(_to_session_out(row, course_code, count))

    return Page[SessionOut](items=items, total=total, limit=page.limit, offset=page.offset)


async def _get_visible_session(
    session_repo: SessionRepository,
    db: DbSession,
    session_id: UUID,
    principal,
) -> tuple[SessionModel, str]:
    found = await session_repo.get_with_course_code(session_id)
    if found is None:
        raise NotFoundError("Session was not found.", {"session_id": str(session_id)})

    row, course_code = found
    allowed = await session_membership_allowed(
        db, row, user_id=principal.user_id, role=principal.role
    )
    # A lecturer who does not teach this session, or a student not enrolled in
    # its course, gets the same 404 an unowned material or question does --
    # see content.py's ownership guard for why existence itself isn't
    # revealed to a caller who has no business with this session.
    if not allowed:
        raise NotFoundError("Session was not found.", {"session_id": str(session_id)})

    return row, course_code


@router.get("/{session_id}", response_model=SessionOut)
async def get_session(
    session_id: UUID,
    principal: CurrentUser,
    db: DbSession,
) -> SessionOut:
    session_repo = SessionRepository(db)
    row, course_code = await _get_visible_session(session_repo, db, session_id, principal)
    count = await session_repo.participant_count(session_id)
    return _to_session_out(row, course_code, count)


@router.post(
    "/{session_id}/start",
    response_model=SessionOut,
    dependencies=[Depends(require_roles(Role.LECTURER, Role.ADMIN))],
)
@audit_action("SESSION_STARTED")
async def start_session(
    session_id: UUID,
    principal: CurrentUser,
    db: DbSession,
    settings: AppSettings,
    request: Request,
) -> SessionOut:
    """Blocked until the session has approved questions staged."""
    session_repo = SessionRepository(db)
    row = await is_session_owner(
        session_repo, session_id, user_id=principal.user_id, role=principal.role
    )
    if row is None:
        raise NotFoundError("Session was not found.", {"session_id": str(session_id)})

    if not await session_repo.has_staged_question(session_id):
        raise ValidationError(
            "A session needs at least one staged question before it can start.",
            {"session_id": str(session_id)},
        )

    row = await session_repo.transition(row, status="active")
    await db.commit()

    lifecycle.start_cycle(
        session_id,
        interval_seconds=settings.checkpoint_interval_seconds,
        window_seconds=settings.checkpoint_response_window_seconds,
        min_respondents=settings.comprehension_alert_min_respondents,
        alert_threshold=settings.comprehension_alert_threshold,
    )

    found = await session_repo.get_with_course_code(session_id)
    return _to_session_out(*found)


@router.post(
    "/{session_id}/end",
    response_model=SessionOut,
    dependencies=[Depends(require_roles(Role.LECTURER, Role.ADMIN))],
)
@audit_action("SESSION_ENDED")
async def end_session(
    session_id: UUID,
    principal: CurrentUser,
    db: DbSession,
    request: Request,
) -> SessionOut:
    session_repo = SessionRepository(db)
    row = await is_session_owner(
        session_repo, session_id, user_id=principal.user_id, role=principal.role
    )
    if row is None:
        raise NotFoundError("Session was not found.", {"session_id": str(session_id)})

    if row.status not in {"prepared", "active", "ending"}:
        raise ConflictError(
            f"Cannot end a session in status '{row.status}'.",
            {"current_status": row.status},
        )

    row = await session_repo.transition(row, status="ended")
    await db.commit()

    lifecycle.stop_cycle(session_id)

    from app.realtime.hub import hub
    from app.schemas.events import ServerEventType

    await hub.broadcast(
        session_id,
        ServerEventType.SESSION_STATE,
        {
            "session_id": str(session_id),
            "status": row.status,
            "participant_count": await session_repo.participant_count(session_id),
            "active_question_id": None,
            "questions_delivered": await session_repo.count_delivered(session_id),
        },
    )
    hub.forget_session(session_id)

    found = await session_repo.get_with_course_code(session_id)
    return _to_session_out(*found)


@router.post(
    "/{session_id}/questions/{question_id}:deliver",
    status_code=status.HTTP_202_ACCEPTED,
    dependencies=[Depends(require_roles(Role.LECTURER, Role.ADMIN))],
)
@audit_action("QUESTION_DELIVERED")
async def deliver_question(
    session_id: UUID,
    question_id: UUID,
    principal: CurrentUser,
    db: DbSession,
    settings: AppSettings,
    request: Request,
) -> dict[str, str]:
    """Lecturer's manual trigger. The scheduler uses the same internal path."""
    session_repo = SessionRepository(db)
    row = await is_session_owner(
        session_repo, session_id, user_id=principal.user_id, role=principal.role
    )
    if row is None:
        raise NotFoundError("Session was not found.", {"session_id": str(session_id)})

    if row.status != "active":
        raise ConflictError(
            f"Cannot deliver a question while the session is '{row.status}'.",
            {"current_status": row.status},
        )

    from app.repositories.question_repository import QuestionRepository

    question_repo = QuestionRepository(db)
    question = await question_repo.get_by_id(question_id)
    if question is None or question.session_id != session_id:
        raise NotFoundError("Question was not found.", {"question_id": str(question_id)})
    if question.status != "staged":
        raise ConflictError(
            f"Cannot deliver a question with status '{question.status}'.",
            {"current_status": question.status},
        )

    await lifecycle.deliver(
        db,
        session_id=session_id,
        question=question,
        window_seconds=settings.checkpoint_response_window_seconds,
        min_respondents=settings.comprehension_alert_min_respondents,
        alert_threshold=settings.comprehension_alert_threshold,
    )
    await db.commit()

    return {"status": "delivered"}


@router.get(
    "/{session_id}/responses",
    response_model=Page[ResponseOut],
    dependencies=[Depends(require_roles(Role.LECTURER, Role.ADMIN))],
)
async def list_responses(
    session_id: UUID,
    principal: CurrentUser,
    db: DbSession,
    page: Paginated,
) -> Page[ResponseOut]:
    session_repo = SessionRepository(db)
    row = await is_session_owner(
        session_repo, session_id, user_id=principal.user_id, role=principal.role
    )
    if row is None:
        raise NotFoundError("Session was not found.", {"session_id": str(session_id)})

    response_repo = ResponseRepository(db)
    responses, total = await response_repo.list_page(
        session_id, limit=page.limit, offset=page.offset
    )

    return Page[ResponseOut](
        items=[
            ResponseOut(
                id=r.response_id,
                question_id=r.question_id,
                student_id=r.student_id,
                selected_option=r.selected_option,
                free_text=r.free_text,
                is_correct=r.is_correct,
                elapsed_ms=r.elapsed_ms,
                submitted_at=r.timestamp,
            )
            for r in responses
        ],
        total=total,
        limit=page.limit,
        offset=page.offset,
    )


@router.get(
    "/{session_id}/engagement",
    response_model=list[EngagementOut],
    dependencies=[Depends(require_roles(Role.LECTURER, Role.ADMIN))],
)
async def session_engagement(
    session_id: UUID,
    principal: CurrentUser,
    db: DbSession,
) -> list[EngagementOut]:
    """Engagement only. Comprehension is served separately and the two are never
    combined into one figure."""
    session_repo = SessionRepository(db)
    row = await is_session_owner(
        session_repo, session_id, user_id=principal.user_id, role=principal.role
    )
    if row is None:
        raise NotFoundError("Session was not found.", {"session_id": str(session_id)})

    engagement_repo = EngagementRepository(db)
    records = await engagement_repo.latest_for_session(session_id)

    return [
        EngagementOut(
            student_id=record.student_id,
            session_id=session_id,
            score=record.engagement_score,
            status=EngagementStatus(record.status),
            confidence=record.confidence,
            signals_available=(
                record.signals_available.split(",") if record.signals_available else []
            ),
            computed_at=record.timestamp,
        )
        for record in records
    ]


@router.get(
    "/{session_id}/alerts",
    response_model=list[ClassComprehensionAlert],
    dependencies=[Depends(require_roles(Role.LECTURER, Role.ADMIN))],
)
async def session_alerts(
    session_id: UUID,
    principal: CurrentUser,
    db: DbSession,
) -> list[ClassComprehensionAlert]:
    session_repo = SessionRepository(db)
    row = await is_session_owner(
        session_repo, session_id, user_id=principal.user_id, role=principal.role
    )
    if row is None:
        raise NotFoundError("Session was not found.", {"session_id": str(session_id)})

    # Alerts are broadcast live over the WebSocket as they are raised (see
    # app.services.session_lifecycle); this endpoint is Phase 7's persisted
    # history view, not yet backed by a table of its own.
    return []


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
    from app.core.errors import not_implemented

    raise not_implemented("Cyber 1", "Phase 7")
