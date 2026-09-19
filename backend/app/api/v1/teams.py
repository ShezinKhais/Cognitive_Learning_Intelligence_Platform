"""Teams meeting-event webhook.

New in Phase 4. Handler bodies are owned by:
  General CS: event handling, automatic session creation and archival
  BBIS:       meeting/user-mapping persistence, roster sync
  AI 1:       content-readiness gate before a Teams meeting can go live
  Cyber 1:    signature verification, least-privilege access

Not a lecturer- or student-facing route: it authenticates the caller (real
Teams infrastructure, or the mock adapter standing in for it -- see
app.services.teams_security) by HMAC signature, not by user JWT, the same
way any other inbound webhook would. Nothing here trusts course, session or
identity data from the request body without checking it against what the
admin console has already established: an unknown course_code or organizer
email is ignored rather than used to create new privileged rows.
"""

from __future__ import annotations

from fastapi import APIRouter, Request

from app.api.deps import AppSettings, DbSession
from app.core.errors import PermissionError_
from app.repositories.course_repository import CourseRepository
from app.repositories.session_repository import SessionRepository
from app.repositories.teams_repository import TeamsRepository
from app.repositories.user_repository import UserRepository
from app.schemas.identity import Role
from app.schemas.teams import (
    TeamsEventType,
    TeamsMeetingEventRequest,
    TeamsMeetingEventResult,
)
from app.services.content_readiness import check_session_readiness
from app.services.session_lifecycle import lifecycle
from app.services.teams_roster import sync_roster
from app.services.teams_security import SIGNATURE_HEADER, verify_teams_signature

router = APIRouter(prefix="/teams", tags=["teams"])


@router.post("/events", response_model=TeamsMeetingEventResult)
async def teams_meeting_event(
    payload: TeamsMeetingEventRequest,
    request: Request,
    db: DbSession,
    settings: AppSettings,
) -> TeamsMeetingEventResult:
    raw_body = await request.body()
    signature = request.headers.get(SIGNATURE_HEADER)
    if not verify_teams_signature(raw_body, signature, settings):
        raise PermissionError_("Invalid or missing Teams event signature.", {})

    if payload.event is TeamsEventType.MEETING_STARTED:
        result = await _handle_meeting_started(db, settings, payload)
    else:
        result = await _handle_meeting_ended(db, payload)

    await db.commit()
    return result


async def _handle_meeting_started(
    db: DbSession,
    settings: AppSettings,
    payload: TeamsMeetingEventRequest,
) -> TeamsMeetingEventResult:
    teams_repo = TeamsRepository(db)

    existing_session = await teams_repo.get_session_for_meeting(payload.teams_meeting_id)
    if existing_session is not None:
        # Webhook delivery is at-least-once by design; replaying a
        # meeting.started event must not create a second session.
        return TeamsMeetingEventResult(
            status="already_linked",
            session_id=existing_session.session_id,
            reason="This meeting is already linked to a session.",
        )

    course = await CourseRepository(db).get_by_code(payload.course_code)
    if course is None:
        return TeamsMeetingEventResult(status="ignored", reason="Unknown course_code.")

    organizer = None
    if payload.organizer_email:
        organizer = await UserRepository(db).get_by_email(str(payload.organizer_email))
    if organizer is None or organizer.role != Role.LECTURER.value:
        return TeamsMeetingEventResult(
            status="ignored", reason="Organizer is not a known lecturer."
        )

    session_repo = SessionRepository(db)
    session_row = await teams_repo.find_unlinked_prepared_session(
        course_id=course.id, instructor_id=organizer.user_id
    )
    if session_row is None:
        session_row = await session_repo.create(
            instructor_id=organizer.user_id,
            course_id=course.id,
            title=payload.title,
            starts_at=None,
        )
    await teams_repo.link_meeting(
        session_id=session_row.session_id,
        teams_meeting_id=payload.teams_meeting_id,
        tenant_id=payload.tenant_id,
    )

    roster_summary = await sync_roster(
        db,
        session_id=session_row.session_id,
        course_id=course.id,
        participants=payload.participants,
    )

    readiness = await check_session_readiness(
        db, course_id=course.id, session_id=session_row.session_id
    )
    if not readiness.ready:
        return TeamsMeetingEventResult(
            status="blocked",
            session_id=session_row.session_id,
            reason=readiness.reason,
            roster=roster_summary,
        )

    await session_repo.transition(session_row, status="active")
    lifecycle.start_cycle(
        session_row.session_id,
        interval_seconds=settings.checkpoint_interval_seconds,
        window_seconds=settings.checkpoint_response_window_seconds,
        min_respondents=settings.comprehension_alert_min_respondents,
        alert_threshold=settings.comprehension_alert_threshold,
    )

    return TeamsMeetingEventResult(
        status="started",
        session_id=session_row.session_id,
        roster=roster_summary,
    )


async def _handle_meeting_ended(
    db: DbSession,
    payload: TeamsMeetingEventRequest,
) -> TeamsMeetingEventResult:
    teams_repo = TeamsRepository(db)
    session_row = await teams_repo.get_session_for_meeting(payload.teams_meeting_id)
    if session_row is None:
        return TeamsMeetingEventResult(
            status="ignored", reason="No session linked to this meeting."
        )

    if session_row.status in {"prepared", "active", "ending"}:
        session_repo = SessionRepository(db)
        await lifecycle.end_session(db, session_repo, session_row)

    await teams_repo.mark_meeting_ended(payload.teams_meeting_id)

    return TeamsMeetingEventResult(status="ended", session_id=session_row.session_id)
