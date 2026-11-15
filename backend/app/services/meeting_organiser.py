"""Who may link a session to a Teams meeting: its organiser, or an admin.

Owner: General CS, Phase 4. Reviewed by Cyber 1.

A meeting id is not a secret. Anyone in a meeting can read it from the Teams
client, so without this check any lecturer in a meeting could link their own
session to it, and the bot would then start and end their class with someone
else's meeting.

The organiser comes from Teams itself, through the bot: the Bot Framework
meeting API (GET {serviceUrl}v1/meetings/{id}) returns the organiser's Entra
object id, which is compared with the Teams account the lecturer signed in
with (their TeamsUserMapping). Nothing the browser says about the meeting is
trusted.

It only applies when Teams is live (TEAMS_NOTIFICATIONS_ENABLED), because that
is when the bot keeps a reference to each meeting it is in. In development
and with the mock adapter there is no meeting to ask about, and the check is
skipped.
"""

from __future__ import annotations

import logging
import re
from urllib.parse import quote, unquote

import httpx
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import Principal
from app.core.config import Settings
from app.core.errors import (
    ConflictError,
    PermissionError_,
    ServiceUnavailableError,
    ValidationError,
)
from app.models.teams_meeting_reference import TeamsMeetingReference
from app.repositories.teams_user_mapping_repository import TeamsUserMappingRepository
from app.schemas.identity import Role
from app.services.teams_notifications import connector_url, notifications

log = logging.getLogger("clip.teams.organiser")


def organiser_of(details: object) -> str | None:
    """The organiser's Entra object id in a Bot Framework meeting details body."""
    if not isinstance(details, dict):
        return None
    organiser = details.get("organizer")
    oid = organiser.get("aadObjectId") if isinstance(organiser, dict) else None
    return oid.lower() if isinstance(oid, str) and oid else None


async def fetch_meeting_details(settings: Settings, service_url: str, meeting_id: str) -> dict:
    base = connector_url(service_url)
    async with httpx.AsyncClient(timeout=4, follow_redirects=False) as client:
        token = await notifications.access_token(client, settings)
        response = await client.get(
            base + f"v1/meetings/{quote(meeting_id, safe='')}",
            headers={"Authorization": f"Bearer {token}"},
        )
        response.raise_for_status()
        body = response.json()
    return body if isinstance(body, dict) else {}


async def require_organiser(
    db: AsyncSession,
    principal: Principal,
    meeting_id: str,
    settings: Settings,
    fetch=fetch_meeting_details,
) -> None:
    """Refuse a lecturer who did not organise this meeting. Admins may link any."""
    if not settings.teams_notifications_enabled or principal.is_(Role.ADMIN):
        return
    teams_user = await TeamsUserMappingRepository(db).teams_user_for(
        tenant_id=settings.tenant_id, user_id=principal.user_id
    )
    if teams_user is None:
        raise PermissionError_(
            "Open C.L.I.P in Teams once so your Teams account is linked, then try again."
        )
    reference = await db.scalar(
        select(TeamsMeetingReference).where(TeamsMeetingReference.meeting_id == meeting_id)
    )
    if reference is None or reference.tenant_id.lower() != settings.tenant_id.lower():
        raise ConflictError(
            "C.L.I.P is not in this meeting yet. Add it from Apps in the meeting, then try again."
        )
    try:
        details = await fetch(settings, reference.service_url, meeting_id)
    except (httpx.HTTPError, ValueError) as exc:
        log.warning("meeting details for %s unavailable: %s", meeting_id, type(exc).__name__)
        raise ServiceUnavailableError(
            "Teams could not confirm who organised this meeting. Try again."
        ) from exc
    organiser = organiser_of(details)
    if organiser is None or organiser != teams_user.lower():
        log.warning(
            "security_event=MEETING_LINK_NOT_ORGANISER user=%s meeting=%s",
            principal.user_id,
            meeting_id,
        )
        raise PermissionError_("Only the meeting's organiser can link a session to it.")


# A Teams join link carries the meeting chat's thread, which is the
# conversation the bot posts into once it is in the meeting.
_THREAD = re.compile(r"19:meeting_[A-Za-z0-9_\-]+@thread\.v2")


def thread_in(join_url: str) -> str | None:
    """The meeting chat thread a Teams join link names, or None."""
    found = _THREAD.search(unquote(unquote(join_url)))
    return found.group(0) if found else None


async def meeting_for_join_link(db: AsyncSession, join_url: str, settings: Settings) -> str:
    """The meeting id the bot knows for the meeting this join link opens.

    The bot learns a meeting's id when it is added to the meeting, so the
    link is matched against the meetings it is in. A link to a meeting it
    has not been added to is refused with what to do about it.
    """
    thread = thread_in(join_url)
    if thread is None:
        raise ValidationError(
            "That is not a Teams meeting link. Copy it from the meeting's "
            "invitation: Join the meeting now."
        )
    meeting_id = await db.scalar(
        select(TeamsMeetingReference.meeting_id)
        .where(
            func.lower(TeamsMeetingReference.conversation_id).startswith(thread.lower()),
            func.lower(TeamsMeetingReference.tenant_id) == settings.tenant_id.lower(),
        )
        .order_by(TeamsMeetingReference.seen_at.desc())
        .limit(1)
    )
    if meeting_id is None:
        raise ConflictError(
            "C.L.I.P is not in this meeting yet. Open the meeting in Teams, add C.L.I.P "
            "from Apps, then link it here."
        )
    return meeting_id
