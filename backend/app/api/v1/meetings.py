"""Teams meeting routes: linking a session to a meeting, and the meeting's
own events.

Owner: General CS, Phase 4. Until the Teams bot is permitted, these are the
mock adapter: staff, or a development tool acting for them, post what the
meeting did. The bot will hand its events to the same service, so both
paths start and end sessions the same way.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Path

from app.api.deps import CurrentUser, DbSession, require_consents, require_roles
from app.schemas.identity import ConsentType, Role
from app.schemas.meetings import MAX_MEETING_ID_LENGTH, MeetingEventIn, MeetingLinkRequest
from app.schemas.session import SessionOut
from app.services import session_lifecycle

router = APIRouter(
    prefix="/meetings",
    tags=["meetings"],
    dependencies=[
        Depends(require_consents(ConsentType.TERMS)),
        Depends(require_roles(Role.LECTURER, Role.ADMIN)),
    ],
)


@router.put("/{meeting_id}", response_model=SessionOut)
async def link_meeting(
    meeting_id: Annotated[str, Path(min_length=1, max_length=MAX_MEETING_ID_LENGTH)],
    payload: MeetingLinkRequest,
    principal: CurrentUser,
    db: DbSession,
) -> SessionOut:
    """Hold a session in this meeting. Either side's old link is replaced."""
    return await session_lifecycle.link_meeting(db, principal, meeting_id, payload.session_id)


@router.post("/events", response_model=SessionOut)
async def meeting_event(
    event: MeetingEventIn,
    principal: CurrentUser,
    db: DbSession,
) -> SessionOut:
    """Start or end the meeting's session, creating one for a meeting that
    starts with none linked when the course is named."""
    return await session_lifecycle.handle_meeting_event(db, principal, event)
