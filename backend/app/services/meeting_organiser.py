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
from sqlalchemy.dialects.postgresql import insert
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
from app.schemas.meetings import MEETING_THREAD, meeting_id_for_thread
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


def thread_in(join_url: str) -> str | None:
    """The meeting chat thread a Teams join link names, or None."""
    found = MEETING_THREAD.search(unquote(unquote(join_url)))
    return found.group(0) if found else None


# The short links Outlook and new Teams put in invitations
# (teams.microsoft.com/meet/<number>?p=<passcode>) carry no meeting chat.
_SHORT_LINK = re.compile(r"^https://teams\.(microsoft|live)\.com/meet/\d+", re.I)


def is_short_link(join_url: str) -> bool:
    return bool(_SHORT_LINK.match(join_url.strip()))


SHORT_LINK_MESSAGE = (
    "That is a short Teams link, which does not say which meeting it is. Open the "
    "meeting in Teams and link it from C.L.I.P in the meeting, or copy its full link "
    "(it starts https://teams.microsoft.com/l/meetup-join/)."
)
NOT_IN_MEETING_MESSAGE = (
    "C.L.I.P is not in this meeting yet. Open the meeting in Teams, add C.L.I.P "
    "from Apps, then link it here."
)


async def meeting_for_join_link(
    db: AsyncSession, join_url: str, settings: Settings, fetch=None
) -> str:
    """The meeting id for the meeting this join link opens.

    The id comes from the link itself. Teams is then asked about the meeting
    through the bot, and only answers for a meeting the bot is in, so a link
    to a meeting without C.L.I.P is refused with what to do about it.
    """
    thread = thread_in(join_url)
    if thread is None:
        if is_short_link(join_url):
            raise ValidationError(SHORT_LINK_MESSAGE)
        raise ValidationError(
            "That is not a Teams meeting link. Copy it from the meeting's "
            "invitation: Join the meeting now."
        )
    derived = meeting_id_for_thread(thread)
    tenant = func.lower(TeamsMeetingReference.tenant_id) == settings.tenant_id.lower()
    meeting_id = await db.scalar(
        select(TeamsMeetingReference.meeting_id)
        .where(
            tenant,
            (TeamsMeetingReference.meeting_id == derived)
            | func.lower(TeamsMeetingReference.conversation_id).startswith(thread.lower()),
        )
        .order_by(TeamsMeetingReference.seen_at.desc())
        .limit(1)
    )
    if meeting_id is not None or not settings.teams_notifications_enabled:
        return meeting_id or derived
    # Nothing from this meeting has reached the bot since it was added, or it
    # was added before C.L.I.P could tell a meeting from its chat. Every
    # meeting in the tenant is reached through the same connector, so ask
    # Teams about this one there.
    service_url = await db.scalar(
        select(TeamsMeetingReference.service_url)
        .where(tenant)
        .order_by(TeamsMeetingReference.seen_at.desc())
        .limit(1)
    )
    if service_url is None:
        raise ConflictError(NOT_IN_MEETING_MESSAGE)
    try:
        await (fetch or fetch_meeting_details)(settings, service_url, derived)
    except httpx.HTTPStatusError as exc:
        if exc.response.status_code in (401, 403, 404):
            raise ConflictError(NOT_IN_MEETING_MESSAGE) from exc
        raise ServiceUnavailableError("Teams did not answer. Try again.") from exc
    except (httpx.HTTPError, ValueError) as exc:
        raise ServiceUnavailableError("Teams did not answer. Try again.") from exc
    await db.execute(
        insert(TeamsMeetingReference)
        .values(
            meeting_id=derived,
            service_url=service_url,
            conversation_id=thread,
            tenant_id=settings.tenant_id,
        )
        .on_conflict_do_nothing(index_elements=[TeamsMeetingReference.meeting_id])
    )
    await db.commit()
    return derived
