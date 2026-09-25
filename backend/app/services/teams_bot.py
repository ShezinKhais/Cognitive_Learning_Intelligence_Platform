"""The Teams bot's side of meetings: who may post to it, and what it acts on.

Owner: General CS, Phase 4.

Teams posts Bot Framework activities to /api/v1/teams/messages. Each carries
a token signed with Bot Framework's keys for this bot's app id, and the
serviceUrl it was sent from, which must match the one in the activity.

The bot acts on a meeting starting or ending, which Teams sends to a bot
installed in the meeting's chat with the OnlineMeeting.ReadBasic.Chat
permission the manifest asks for. It starts or ends the linked session as
the session's lecturer, through the same service the mock adapter's routes
use. Messages, installs and participant events are acknowledged and not
acted on: participants need BBIS's Teams user mappings first.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from functools import lru_cache
from typing import Any

import jwt
from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AuthenticationError, ClipError, ServiceUnavailableError
from app.core.security import TokenValidationError, extract_bearer_token
from app.schemas.meetings import MeetingEventIn, MeetingEventKind, TeamsActivity
from app.services import session_lifecycle

log = logging.getLogger("clip.teams")

BOT_FRAMEWORK_ISSUER = "https://api.botframework.com"
BOT_FRAMEWORK_KEYS = "https://login.botframework.com/v1/.well-known/keys"
# Bot Framework allows five minutes of clock skew between the channel and the bot.
CLOCK_SKEW_SECONDS = 300

MEETING_EVENTS = {
    "application/vnd.microsoft.meetingStart": MeetingEventKind.STARTED,
    "application/vnd.microsoft.meetingEnd": MeetingEventKind.ENDED,
}

# The key a token was signed with, looked up by the token's kid.
KeyResolver = Callable[[str], Awaitable[Any]]


@lru_cache
def _keys() -> jwt.PyJWKClient:
    return jwt.PyJWKClient(BOT_FRAMEWORK_KEYS, cache_keys=True)


async def bot_framework_key(token: str) -> Any:
    # PyJWKClient fetches with urllib, which blocks, so off the event loop.
    signing = await asyncio.to_thread(_keys().get_signing_key_from_jwt, token)
    return signing.key


class BotAuthenticator:
    """Checks that an activity came from Teams, for this bot."""

    def __init__(self, app_id: str, key_for: KeyResolver = bot_framework_key) -> None:
        self._app_id = app_id
        self._key_for = key_for

    async def verify(self, authorization: str | None, service_url: str) -> None:
        try:
            token = extract_bearer_token(authorization)
            key = await self._key_for(token)
            claims = jwt.decode(
                token,
                key,
                algorithms=["RS256"],
                audience=self._app_id,
                issuer=BOT_FRAMEWORK_ISSUER,
                leeway=CLOCK_SKEW_SECONDS,
                options={"require": ["exp", "iss", "aud"]},
            )
        except jwt.PyJWKClientConnectionError as exc:
            raise ServiceUnavailableError("Bot Framework's signing keys are unreachable.") from exc
        except (TokenValidationError, jwt.PyJWTError) as exc:
            log.warning("security_event=BOT_TOKEN_REJECTED reason=%s", exc)
            raise AuthenticationError("The activity is not from Teams.") from exc
        # A token stolen from one channel must not be replayed from another.
        if claims.get("serviceUrl") != service_url:
            log.warning("security_event=BOT_TOKEN_REJECTED reason=serviceUrl mismatch")
            raise AuthenticationError("The activity is not from Teams.")


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


async def handle_activity(db: AsyncSession, activity: TeamsActivity) -> None:
    """Apply a meeting's start or end to its session.

    A refusal, such as a start with nothing staged, is logged rather than
    returned: Teams would retry an error, and retrying cannot fix it. The
    lecturer can still start the class themselves.
    """
    event = meeting_event(activity)
    if event is None:
        return
    owner = await session_lifecycle.meeting_owner(db, event.meeting_id)
    if owner is None:
        log.info("meeting %s %s, but no session is linked to it", event.meeting_id, event.kind)
        return
    try:
        await session_lifecycle.handle_meeting_event(db, owner, event)
    except ClipError as exc:
        await db.rollback()
        log.warning("meeting %s %s was not applied: %s", event.meeting_id, event.kind, exc)
