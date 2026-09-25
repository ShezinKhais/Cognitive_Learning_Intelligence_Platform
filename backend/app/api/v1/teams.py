"""The Teams bot's messaging endpoint.

Owner: General CS, Phase 4. Teams authenticates with a Bot Framework token,
not a C.L.I.P one, so this router sits outside the bearer and consent
guards the other routes use. Without Teams credentials it refuses every
activity; the meeting routes are the fallback.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Annotated

from fastapi import APIRouter, Depends, Request

from app.api.deps import AppSettings, DbSession
from app.core.errors import ServiceUnavailableError
from app.schemas.meetings import TeamsActivity
from app.services import teams_bot

router = APIRouter(prefix="/teams", tags=["teams"])


@lru_cache
def _authenticator(app_id: str) -> teams_bot.BotAuthenticator:
    return teams_bot.BotAuthenticator(app_id)


class TeamsNotConfiguredError(ServiceUnavailableError):
    """Expected until the tenant exists, so logged as one line, not a trace."""

    log_traceback = False


async def get_bot_authenticator(settings: AppSettings) -> teams_bot.BotAuthenticator:
    if not settings.teams_configured:
        raise TeamsNotConfiguredError(
            "Teams is not configured. Send meeting events to /api/v1/meetings/events."
        )
    return _authenticator(settings.client_id)


@router.post("/messages", response_model=None)
async def bot_messages(
    activity: TeamsActivity,
    request: Request,
    db: DbSession,
    authenticator: Annotated[teams_bot.BotAuthenticator, Depends(get_bot_authenticator)],
) -> None:
    """Receive an activity from Teams. Meeting starts and ends are applied to
    the linked session; everything else is acknowledged."""
    await authenticator.verify(request.headers.get("Authorization"), activity.service_url)
    await teams_bot.handle_activity(db, activity)
