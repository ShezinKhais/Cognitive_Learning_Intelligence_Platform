"""Teams meeting routes: linking a session to a meeting, and the meeting's
own events.

Owner: General CS, Phase 4. Until the Teams bot is permitted, these are the
mock adapter: staff, or a development tool acting for them, post what the
meeting did. The bot will hand its events to the same service, so both
paths start and end sessions the same way.
"""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Path, Request

from app.api.deps import AppSettings, CurrentUser, DbSession, require_consents, require_roles
from app.core.audit import audit_action
from app.schemas.identity import ConsentType, Role
from app.schemas.meetings import (
    MAX_MEETING_ID_LENGTH,
    MeetingClassStart,
    MeetingClassSuggestion,
    MeetingEventIn,
    MeetingJoinLinkRequest,
    MeetingLinkRequest,
    TeamsEndOption,
    TeamsUpdatesMute,
    TeamsUpdatesOut,
)
from app.schemas.session import SessionOut
from app.services import meeting_organiser, session_lifecycle, teams_presence, unscheduled_class
from app.services import teams_updates as teams_updates_service

router = APIRouter(
    prefix="/meetings",
    tags=["meetings"],
    dependencies=[
        Depends(require_consents(ConsentType.TERMS)),
        Depends(require_roles(Role.LECTURER, Role.ADMIN)),
    ],
)


@router.post("/join-link", response_model=SessionOut)
@audit_action("MEETING_LINKED")
async def link_meeting_by_join_link(
    payload: MeetingJoinLinkRequest,
    principal: CurrentUser,
    request: Request,
    settings: AppSettings,
    db: DbSession,
) -> SessionOut:
    """Hold a session in the Teams meeting a join link opens, from the
    C.L.I.P website. The meeting must have C.L.I.P added to it, and with
    Teams live a lecturer must be its organiser. Once linked, the meeting
    starting starts the class, the class starting opens C.L.I.P for everyone
    in the call, and the class ends with the meeting or once everyone has
    left it."""
    meeting_id = await meeting_organiser.meeting_for_join_link(db, payload.join_url, settings)
    await meeting_organiser.require_organiser(db, principal, meeting_id, settings)
    return await session_lifecycle.link_meeting(db, principal, meeting_id, payload.session_id)


@router.get("/{meeting_id}", response_model=SessionOut)
async def meeting_session(
    meeting_id: Annotated[str, Path(min_length=1, max_length=MAX_MEETING_ID_LENGTH)],
    principal: CurrentUser,
    db: DbSession,
) -> SessionOut:
    """The session this meeting holds, if the caller runs it or is an admin.
    For the lecturer's Teams tab, which knows the meeting but not the session."""
    return await session_lifecycle.meeting_session(db, principal, meeting_id)


@router.put("/{meeting_id}", response_model=SessionOut)
@audit_action("MEETING_LINKED")
async def link_meeting(
    meeting_id: Annotated[str, Path(min_length=1, max_length=MAX_MEETING_ID_LENGTH)],
    payload: MeetingLinkRequest,
    principal: CurrentUser,
    request: Request,
    settings: AppSettings,
    db: DbSession,
) -> SessionOut:
    """Hold a session in this meeting. Either side's old link is replaced.
    With Teams live, a lecturer must be the meeting's organiser; admins may
    link any meeting."""
    await meeting_organiser.require_organiser(db, principal, meeting_id, settings)
    return await session_lifecycle.link_meeting(db, principal, meeting_id, payload.session_id)


@router.get("/{meeting_id}/class-suggestion", response_model=MeetingClassSuggestion)
async def class_suggestion(
    meeting_id: Annotated[str, Path(min_length=1, max_length=MAX_MEETING_ID_LENGTH)],
    principal: CurrentUser,
    settings: AppSettings,
    db: DbSession,
) -> MeetingClassSuggestion:
    """For a meeting with no session: the course and title to offer when
    the side panel asks whether this is a class, guessed from the meeting's
    title."""
    title = await unscheduled_class.meeting_title(db, meeting_id, settings)
    return await unscheduled_class.suggest(db, principal, title)


@router.post("/{meeting_id}/class", response_model=SessionOut)
@audit_action("UNSCHEDULED_CLASS_STARTED")
async def start_class(
    meeting_id: Annotated[str, Path(min_length=1, max_length=MAX_MEETING_ID_LENGTH)],
    payload: MeetingClassStart,
    principal: CurrentUser,
    request: Request,
    settings: AppSettings,
    db: DbSession,
) -> SessionOut:
    """Yes, this is a class: create its session, link it to this meeting and
    start it. Only the meeting's organiser, or an admin."""
    return await unscheduled_class.start_class(db, principal, meeting_id, payload, settings)


@router.post("/events", response_model=SessionOut)
@audit_action("MEETING_EVENT_APPLIED")
async def meeting_event(
    event: MeetingEventIn,
    principal: CurrentUser,
    request: Request,
    settings: AppSettings,
    db: DbSession,
) -> SessionOut:
    """Start or end the meeting's session, creating one for a meeting that
    starts with none linked when the course is named."""
    return await session_lifecycle.handle_meeting_event(db, principal, event)


@router.get("/sessions/{session_id}/updates", response_model=TeamsUpdatesOut)
async def teams_updates(
    session_id: UUID, principal: CurrentUser, settings: AppSettings, db: DbSession
) -> TeamsUpdatesOut:
    """The latest Teams updates for the lecturer's class, for the pop-up
    they open, and how many of its students C.L.I.P can reach in Teams."""
    return await teams_updates_service.updates(db, principal, session_id, settings)


@router.put("/sessions/{session_id}/updates", response_model=TeamsUpdatesOut)
async def mute_teams_updates(
    session_id: UUID,
    payload: TeamsUpdatesMute,
    principal: CurrentUser,
    settings: AppSettings,
    db: DbSession,
) -> TeamsUpdatesOut:
    """Mute, or unmute, the lecturer's Teams pop-ups for the rest of the class.
    The updates are still listed."""
    return await teams_updates_service.mute(db, principal, session_id, payload.muted, settings)


@router.put("/sessions/{session_id}/end-when-lecturer-leaves", response_model=SessionOut)
@audit_action("TEAMS_END_OPTION_CHANGED")
async def end_when_lecturer_leaves(
    session_id: UUID,
    payload: TeamsEndOption,
    principal: CurrentUser,
    request: Request,
    settings: AppSettings,
    db: DbSession,
) -> SessionOut:
    """Whether the class ends when its lecturer leaves the linked Teams call,
    after the same short wait as an emptied call."""
    return await teams_presence.set_end_when_lecturer_leaves(
        db, principal, session_id, payload.end_when_lecturer_leaves
    )


@router.post("/sessions/{session_id}/keep-running", response_model=SessionOut)
@audit_action("TEAMS_AUTO_END_CANCELLED", commit=True)
async def keep_running(
    session_id: UUID,
    principal: CurrentUser,
    request: Request,
    settings: AppSettings,
    db: DbSession,
) -> SessionOut:
    """Cancel the wait to end a class whose Teams call has emptied, or whose
    lecturer has left it. 404 when no such wait is running."""
    return await teams_presence.keep_running(db, principal, session_id)
