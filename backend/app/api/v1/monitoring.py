"""Error monitoring: browsers report their crashes, admins read what went wrong.

Owner: General CS. See app.core.error_log.

Reporting needs a signed-in user but no consent, since a page can crash
before the terms are accepted. Each user may report a few crashes a minute;
more than that is dropped without an error, as a looping crash would send
the same report anyway.
"""

from __future__ import annotations

import time
from collections import defaultdict, deque
from datetime import datetime
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Response, status
from pydantic import BaseModel, Field

from app.api.deps import CurrentUser, require_consents, require_roles
from app.api.v1.health import APP_VERSION
from app.core.error_log import error_log
from app.schemas.identity import ConsentType, Role

REPORTS_PER_WINDOW = 10
WINDOW_SECONDS = 60.0

router = APIRouter(tags=["monitoring"])

CLIENT_AREAS = frozenset({"admin", "consent", "lecturer", "login", "student", "teams"})
CLIENT_SUMMARIES = {
    "render": "Page failed to render",
    "script": "Browser script failed",
    "promise": "Browser operation failed",
    "load": "Page code failed to load",
}


class ClientErrorIn(BaseModel):
    kind: Literal["render", "script", "promise", "load"]
    # Older clients may still send a message. Never store it.
    message: str | None = Field(default=None, max_length=500)
    page: str = Field(min_length=1, max_length=200, description="The path, without its query.")


class ErrorGroupOut(BaseModel):
    source: Literal["server", "client"]
    level: str
    where: str = Field(description="The logger, or the page and kind for a browser crash.")
    message: str
    count: int
    first_at: datetime
    last_at: datetime
    request_id: str | None


class RecentErrorsOut(BaseModel):
    since: datetime = Field(description="When this server started counting.")
    total: int
    version: str
    server_error_spike: bool
    groups: list[ErrorGroupOut]


class _Limiter:
    def __init__(self) -> None:
        self._seen: dict[UUID, deque[float]] = defaultdict(deque)

    def allow(self, user_id: UUID, now: float) -> bool:
        times = self._seen[user_id]
        while times and now - times[0] > WINDOW_SECONDS:
            times.popleft()
        if len(times) >= REPORTS_PER_WINDOW:
            return False
        times.append(now)
        if len(self._seen) > 10_000:
            self._seen.clear()
        return True


limiter = _Limiter()


@router.post("/client-errors", status_code=status.HTTP_204_NO_CONTENT, response_class=Response)
async def report_client_error(payload: ClientErrorIn, principal: CurrentUser) -> Response:
    """A page crashed in someone's browser. Shown to admins on the status page."""
    if limiter.allow(principal.user_id, time.monotonic()):
        path = payload.page.split("?", 1)[0].split("#", 1)[0]
        area = path.removeprefix("/").split("/", 1)[0]
        page = f"/{area}" if area in CLIENT_AREAS else "Other page"
        error_log.add(
            source="client",
            level="ERROR",
            where=f"{page} ({payload.kind}, {principal.role.value})",
            message=CLIENT_SUMMARIES[payload.kind],
        )
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get(
    "/admin/errors",
    response_model=RecentErrorsOut,
    dependencies=[
        Depends(require_roles(Role.ADMIN)),
        Depends(require_consents(ConsentType.TERMS)),
    ],
)
async def recent_errors() -> RecentErrorsOut:
    """Server errors and browser crashes since this server started, grouped,
    newest first."""
    return RecentErrorsOut(
        since=error_log.started_at,
        total=error_log.total,
        version=APP_VERSION,
        server_error_spike=error_log.server_error_spike(),
        groups=[
            ErrorGroupOut.model_validate(group, from_attributes=True)
            for group in error_log.recent()
        ],
    )
