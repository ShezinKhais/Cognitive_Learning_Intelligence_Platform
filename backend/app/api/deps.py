"""Shared FastAPI dependencies.

Anything more than one router needs lives here so routers stay thin and the
seams between workstreams are explicit.
"""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import Depends, Query, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings, get_settings
from app.core.database import get_db
from app.core.errors import AuthenticationError, PermissionError_
from app.schemas.identity import Role

DbSession = Annotated[AsyncSession, Depends(get_db)]
AppSettings = Annotated[Settings, Depends(get_settings)]


class Pagination:
    def __init__(
        self,
        limit: Annotated[int, Query(ge=1, le=200)] = 50,
        offset: Annotated[int, Query(ge=0)] = 0,
    ) -> None:
        self.limit = limit
        self.offset = offset


Paginated = Annotated[Pagination, Depends(Pagination)]


class Principal:
    """The authenticated caller.

    Populated by the auth dependency below. Handlers should depend on this
    rather than reading headers themselves.
    """

    def __init__(self, user_id: UUID, role: Role, email: str) -> None:
        self.user_id = user_id
        self.role = role
        self.email = email

    def is_(self, *roles: Role) -> bool:
        return self.role in roles


async def get_principal(request: Request) -> Principal:
    """Resolve the caller from the request.

    Owner: Cyber 1, Phase 1. Real token validation replaces the body of this
    function; the signature is the seam and should not change. Until then it
    rejects everything, so no route can accidentally appear to work while
    unauthenticated.
    """
    raise AuthenticationError(
        "Authentication is not wired up yet.",
        {"owner": "Cyber 1", "phase": "Phase 1"},
    )


CurrentUser = Annotated[Principal, Depends(get_principal)]


def require_roles(*roles: Role):
    """Route guard. Usage:

        @router.get("/x", dependencies=[Depends(require_roles(Role.LECTURER))])

    Owner: Cyber 1 extends this with ownership checks (does this lecturer own
    this session) in Phase 1.
    """

    async def _guard(principal: CurrentUser) -> Principal:
        if not principal.is_(*roles):
            raise PermissionError_(
                "Your role does not permit this action.",
                {"required": [r.value for r in roles], "actual": principal.role.value},
            )
        return principal

    return _guard
