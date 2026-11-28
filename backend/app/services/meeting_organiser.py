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
from urllib.parse import quote, unquote, urlsplit
from uuid import UUID

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
_SHORT_PATH = re.compile(r"/meet/([0-9]{6,32})/?")


def short_meeting_id(join_url: str) -> str | None:
    try:
        url = urlsplit(join_url.strip())
    except ValueError:
        return None
    if url.scheme != "https" or url.netloc.lower() != "teams.microsoft.com":
        return None
    match = _SHORT_PATH.fullmatch(url.path)
    return match.group(1) if match else None


SHORT_LINK_MESSAGE = (
    "This is a short Teams link. Open the meeting, add C.L.I.P from Apps if needed, "
    "and use the C.L.I.P panel to link your class. You can also paste a full "
    "teams.microsoft.com/l/meetup-join/ link here."
)
NOT_IN_MEETING_MESSAGE = (
    "C.L.I.P is not in this meeting yet. Open the meeting in Teams, add C.L.I.P "
    "from Apps, then link it here."
)


async def lookup_short_meeting(
    client: httpx.AsyncClient, headers: dict[str, str], teams_user: str, short_id: str
) -> str | None:
    """Resolve a meeting through the signed-in organiser's tenant account."""
    organiser = str(UUID(teams_user))
    if not re.fullmatch(r"[0-9]{6,32}", short_id):
        return None
    response = await client.get(
        f"https://graph.microsoft.com/v1.0/users/{organiser}/onlineMeetings",
        headers=headers,
        params={"$filter": f"joinMeetingIdSettings/joinMeetingId eq '{short_id}'"},
    )
    if response.status_code in (403, 404):
        return None
    response.raise_for_status()
    body = response.json()
    matches = body.get("value") if isinstance(body, dict) else None
    if not isinstance(matches, list) or len(matches) != 1 or body.get("@odata.nextLink"):
        return None
    meeting = matches[0]
    if not isinstance(meeting, dict):
        return None
    current = meeting
    for key in ("participants", "organizer", "identity", "user"):
        current = current.get(key) if isinstance(current, dict) else None
    if not isinstance(current, dict) or str(current.get("id", "")).lower() != organiser:
        return None
    chat = meeting.get("chatInfo")
    thread = chat.get("threadId") if isinstance(chat, dict) else None
    if isinstance(thread, str) and MEETING_THREAD.fullmatch(thread):
        return thread
    web_url = meeting.get("joinWebUrl")
    return thread_in(web_url) if isinstance(web_url, str) else None


async def resolve_short_meeting(
    db: AsyncSession, principal: Principal, settings: Settings, short_id: str
) -> str | None:
    # Use the same tenant credentials as transcript imports. The Graph
    # access policy and our organiser check both apply to the lookup.
    from app.services.transcript_minutes import graph_token

    teams_user = await TeamsUserMappingRepository(db).teams_user_for(
        tenant_id=settings.tenant_id, user_id=principal.user_id
    )
    if teams_user is None:
        return None
    try:
        async with httpx.AsyncClient(timeout=5, follow_redirects=False) as client:
            headers = {"Authorization": f"Bearer {await graph_token(client, settings)}"}
            return await lookup_short_meeting(client, headers, teams_user, short_id)
    except (httpx.HTTPError, ServiceUnavailableError, ValueError) as exc:
        log.info("Teams short-link lookup failed: %s", type(exc).__name__)
        return None


async def meeting_for_join_link(
    db: AsyncSession,
    join_url: str,
    settings: Settings,
    fetch=None,
    *,
    principal: Principal | None = None,
) -> str:
    """The meeting id for the meeting this join link opens.

    The id comes from the link itself. Teams is then asked about the meeting
    through the bot, and only answers for a meeting the bot is in, so a link
    to a meeting without C.L.I.P is refused with what to do about it.
    """
    thread = thread_in(join_url)
    if thread is None and (short_id := short_meeting_id(join_url)):
        if principal is not None and settings.teams_notifications_enabled:
            thread = await resolve_short_meeting(db, principal, settings, short_id)
        if thread is None:
            raise ValidationError(SHORT_LINK_MESSAGE)
    if thread is None:
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
