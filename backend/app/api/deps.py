"""Shared FastAPI dependencies.

Anything more than one router needs lives here so routers stay thin and the
seams between workstreams are explicit.
"""

from __future__ import annotations

import logging
from typing import Annotated
from uuid import UUID

from fastapi import Depends, Query, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.service import user_from_token
from app.auth.store import get_consent_repository
from app.core.config import Settings, get_settings
from app.core.database import get_db
from app.core.errors import (
    AuthenticationError,
    ConsentRequiredError,
    PermissionError_,
)
from app.core.security import (
    TokenValidationError,
    extract_bearer_token,
)
from app.repositories.consent_repository import ConsentRepository
from app.schemas.identity import ConsentType, Role

log = logging.getLogger("clip.security")

DbSession = Annotated[
    AsyncSession,
    Depends(get_db),
]

AppSettings = Annotated[
    Settings,
    Depends(get_settings),
]


class Pagination:
    def __init__(
        self,
        limit: Annotated[
            int,
            Query(ge=1, le=200),
        ] = 50,
        offset: Annotated[
            int,
            Query(ge=0),
        ] = 0,
    ) -> None:
        self.limit = limit
        self.offset = offset


Paginated = Annotated[
    Pagination,
    Depends(Pagination),
]


class Principal:
    """The authenticated caller."""

    def __init__(
        self,
        user_id: UUID,
        role: Role,
        email: str,
    ) -> None:
        self.user_id = user_id
        self.role = role
        self.email = email

    def is_(
        self,
        *roles: Role,
    ) -> bool:
        return self.role in roles


async def get_principal(
    request: Request,
    settings: AppSettings,
    db: DbSession,
) -> Principal:
    """Resolve the caller from a signed bearer token."""

    try:
        token = extract_bearer_token(request.headers.get("Authorization"))

        user = await user_from_token(
            token,
            settings,
            db,
        )

    except TokenValidationError as exc:
        log.warning(
            "security_event=TOKEN_REJECTED reason=%s",
            str(exc),
        )

        raise AuthenticationError("Authentication is required.") from exc

    return Principal(
        user_id=user.id,
        role=user.role,
        email=user.email,
    )


CurrentUser = Annotated[
    Principal,
    Depends(get_principal),
]


def require_roles(
    *roles: Role,
):
    """Require one of the supplied roles for a route or router."""

    async def _guard(
        principal: CurrentUser,
    ) -> Principal:
        if not principal.is_(*roles):
            log.warning(
                ("security_event=ACCESS_DENIED user_id=%s actual_role=%s required_roles=%s"),
                principal.user_id,
                principal.role.value,
                ",".join(role.value for role in roles),
            )

            raise PermissionError_(
                "Your role does not permit this action.",
                {
                    "required": [role.value for role in roles],
                    "actual": principal.role.value,
                },
            )

        return principal

    return _guard


def require_consents(
    *consents: ConsentType,
):
    """Require explicitly granted consent without merging categories.

    Development uses the temporary in-memory consent store.
    Production uses Nour's persisted Consent table.
    """

    async def _guard(
        principal: CurrentUser,
        settings: AppSettings,
        db: DbSession,
    ) -> Principal:
        if settings.is_production:
            repository = ConsentRepository(db)

            granted = await repository.granted_for(principal.user_id)

        else:
            granted = get_consent_repository(settings).granted_for(principal.user_id)

        missing = [consent for consent in consents if consent not in granted]

        if missing:
            log.warning(
                ("security_event=ACCESS_DENIED user_id=%s missing_consents=%s"),
                principal.user_id,
                ",".join(consent.value for consent in missing),
            )

            raise ConsentRequiredError(
                "Required consent has not been granted.",
                {"missing": [consent.value for consent in missing]},
            )

        return principal

    return _guard
