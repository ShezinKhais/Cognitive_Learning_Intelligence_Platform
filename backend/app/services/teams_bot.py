"""The Teams bot's side of meetings: who may post to it, and what it acts on.

Owner: General CS, Phase 4. Who may post is reviewed by Cyber 1.

Teams posts Bot Framework activities to /api/v1/teams/messages. Each carries
a token signed with Bot Framework's keys for this bot's app id, and the
serviceUrl it was sent from, which must match the one in the activity.

The token is all Bot Framework signs; the activity body is not. Every Azure
bot also has the Web Chat channel on from creation, and Direct Line can be
turned on beside it, and Bot Framework signs what those channels deliver just
as validly, with a body their client wrote. So the token is not enough to
believe a meeting started or ended. An activity is acted on only when:

- the key that signed its token is endorsed for the channel the activity
  names, as Bot Framework's own SDKs check;
- that channel is Microsoft Teams, the only one a meeting event comes from;
- it comes from this deployment's own Microsoft 365 tenant. Anyone can
  sideload a manifest carrying this bot's id into their own tenant, and
  Teams will then deliver that tenant's activities here.

The bot acts on a meeting starting or ending, which Teams sends to a bot
installed in the meeting's chat with the OnlineMeeting.ReadBasic.Chat
permission the manifest asks for. It starts or ends the linked session as
the session's lecturer, through the same service the mock adapter's routes
use, and only while that lecturer could still do so themselves. Messages,
installs and participant events are acknowledged and not acted on:
participants need BBIS's Teams user mappings first.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from functools import lru_cache
from typing import Any

import jwt
from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.errors import (
    AuthenticationError,
    ClipError,
    PermissionError_,
    ServiceUnavailableError,
)
from app.core.security import TokenValidationError, extract_bearer_token
from app.schemas.meetings import MeetingEventIn, MeetingEventKind, TeamsActivity
from app.services import session_lifecycle

log = logging.getLogger("clip.teams")

BOT_FRAMEWORK_ISSUER = "https://api.botframework.com"
BOT_FRAMEWORK_KEYS = "https://login.botframework.com/v1/.well-known/keys"
# Bot Framework allows five minutes of clock skew between the channel and the bot.
CLOCK_SKEW_SECONDS = 300

# The channelId Bot Framework gives activities from Microsoft Teams.
TEAMS_CHANNEL = "msteams"

MEETING_EVENTS = {
    "application/vnd.microsoft.meetingStart": MeetingEventKind.STARTED,
    "application/vnd.microsoft.meetingEnd": MeetingEventKind.ENDED,
}


@dataclass(frozen=True)
class BotSigningKey:
    """A Bot Framework signing key, and the channels it is endorsed to sign
    for. endorsements is None when the key is not in the published set."""

    key: Any
    endorsements: frozenset[str] | None


# The key a token was signed with, looked up by the token's kid.
KeyResolver = Callable[[str], Awaitable[BotSigningKey]]


class _BotFrameworkKeys(jwt.PyJWKClient):
    """Bot Framework's published keys, keeping each key's endorsements.

    PyJWK keeps only the key material, so the endorsements are read from the
    raw set as it is fetched. Every refresh of the cached set comes through
    here, so the two never describe different sets.
    """

    def __init__(self, uri: str) -> None:
        super().__init__(uri, cache_keys=True)
        self.endorsements: dict[str, frozenset[str]] = {}

    def fetch_data(self) -> Any:
        data = super().fetch_data()
        keys = data.get("keys") if isinstance(data, dict) else None
        self.endorsements = {
            entry["kid"]: frozenset(entry.get("endorsements") or ())
            for entry in keys or ()
            if isinstance(entry, dict) and isinstance(entry.get("kid"), str)
        }
        return data


@lru_cache
def _keys() -> _BotFrameworkKeys:
    return _BotFrameworkKeys(BOT_FRAMEWORK_KEYS)


async def bot_framework_key(token: str) -> BotSigningKey:
    keys = _keys()
    # PyJWKClient fetches with urllib, which blocks, so off the event loop.
    signing = await asyncio.to_thread(keys.get_signing_key_from_jwt, token)
    return BotSigningKey(signing.key, keys.endorsements.get(signing.key_id))


class BotAuthenticator:
    """Checks that an activity came from Teams, for this bot, in this
    organisation."""

    def __init__(
        self, app_id: str, tenant_id: str, key_for: KeyResolver = bot_framework_key
    ) -> None:
        self._app_id = app_id
        self._tenant_id = tenant_id.strip().lower()
        self._key_for = key_for

    async def verify(
        self, authorization: str | None, service_url: str, channel_id: str | None = TEAMS_CHANNEL
    ) -> None:
        """The token is Bot Framework's, for this bot, sent from service_url,
        by a key endorsed for channel_id."""
        try:
            token = extract_bearer_token(authorization)
            signing = await self._key_for(token)
            claims = jwt.decode(
                token,
                signing.key,
                algorithms=["RS256"],
                audience=self._app_id,
                issuer=BOT_FRAMEWORK_ISSUER,
                leeway=CLOCK_SKEW_SECONDS,
                options={"require": ["exp", "iss", "aud"]},
            )
        except jwt.PyJWKClientConnectionError as exc:
            raise ServiceUnavailableError("Bot Framework's signing keys are unreachable.") from exc
        except (TokenValidationError, jwt.PyJWTError) as exc:
            raise _refusal("token", str(exc)) from exc
        # A token stolen from one channel must not be replayed from another.
        if claims.get("serviceUrl") != service_url:
            raise _refusal("token", "serviceUrl mismatch")
        # A key Bot Framework has not endorsed for this channel cannot vouch
        # for an activity claiming to come from it. An empty set endorses
        # nothing in particular, as Bot Framework's SDKs read it.
        if signing.endorsements is None:
            raise _refusal("token", "signing key is not in Bot Framework's published set")
        if signing.endorsements and channel_id not in signing.endorsements:
            raise _refusal("token", f"signing key is not endorsed for channel {channel_id!r}")

    def authorize(self, activity: TeamsActivity) -> None:
        """The activity comes from Teams, in this deployment's tenant."""
        if activity.channel_id != TEAMS_CHANNEL:
            raise _refusal("origin", f"channel {activity.channel_id!r} is not Microsoft Teams")
        tenant = _tenant_of(activity)
        if tenant is None or tenant.lower() != self._tenant_id:
            raise _refusal("origin", f"tenant {tenant!r} is not this deployment's")


def _tenant_of(activity: TeamsActivity) -> str | None:
    tenant = (activity.channel_data or {}).get("tenant")
    tenant_id = tenant.get("id") if isinstance(tenant, dict) else None
    return tenant_id if isinstance(tenant_id, str) and tenant_id else None


def _refusal(what: str, reason: str) -> ClipError:
    """Why an activity is refused: a bad token is a 401, a wrong origin a 403."""
    if what == "token":
        log.warning("security_event=BOT_TOKEN_REJECTED reason=%s", reason)
        return AuthenticationError("The activity is not from Teams.")
    log.warning("security_event=BOT_ACTIVITY_REJECTED reason=%s", reason)
    return PermissionError_("This bot only serves its own organisation's Teams.")


def meeting_event(activity: TeamsActivity) -> MeetingEventIn | None:
    """The meeting start or end an activity reports, or None for anything else."""
    kind = MEETING_EVENTS.get(activity.name or "") if activity.type == "event" else None
    if kind is None:
        return None
    meeting = (activity.channel_data or {}).get("meeting") or {}
    meeting_id = meeting.get("id") if isinstance(meeting, dict) else None
    if not isinstance(meeting_id, str) or not meeting_id:
        log.warning("a meeting %s arrived without a meeting id", kind.value)
        return None
    try:
        return MeetingEventIn(kind=kind, meeting_id=meeting_id)
    except ValidationError:
        # An error here would be retried by Teams for ever.
        log.warning("a meeting %s arrived with a meeting id C.L.I.P cannot hold", kind.value)
        return None


async def handle_activity(db: AsyncSession, activity: TeamsActivity, settings: Settings) -> None:
    """Apply a meeting's start or end to its session.

    A refusal, such as a start with nothing staged or a lecturer who can no
    longer be acted for, is logged rather than returned: Teams would retry
    an error, and retrying cannot fix it. The lecturer can still start the
    class themselves.
    """
    event = meeting_event(activity)
    if event is None:
        return
    try:
        owner = await session_lifecycle.meeting_owner(db, event.meeting_id, settings)
        if owner is None:
            log.info("meeting %s %s, but no session is linked to it", event.meeting_id, event.kind)
            return
        await session_lifecycle.handle_meeting_event(db, owner, event)
    except ClipError as exc:
        await db.rollback()
        log.warning("meeting %s %s was not applied: %s", event.meeting_id, event.kind, exc)
