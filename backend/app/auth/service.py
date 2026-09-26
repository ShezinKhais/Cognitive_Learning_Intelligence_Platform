"""Authentication service shared by HTTP and WebSocket entry points."""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.store import get_consent_repository, get_user_repository
from app.core.config import Settings
from app.core.security import (
    TokenValidationError,
    decode_access_token,
)
from app.repositories.consent_repository import ConsentRepository
from app.repositories.user_repository import UserRepository
from app.schemas.identity import ConsentType, Role


@dataclass(frozen=True, slots=True)
class AuthenticatedUser:
    id: UUID
    email: str
    role: Role


async def active_user(
    user_id: UUID,
    settings: Settings,
    db: AsyncSession,
) -> AuthenticatedUser | None:
    """The account as it stands now, or None if it is gone or disabled."""

    if settings.is_production:
        user = await UserRepository(db).get_by_id(user_id)
    else:
        user = get_user_repository(settings).get_by_id(user_id)

    if user is None or not user.active:
        return None

    role = user.role if isinstance(user.role, Role) else Role(user.role)
    return AuthenticatedUser(id=user.id, email=user.email, role=role)


async def granted_consents(
    user_id: UUID,
    settings: Settings,
    db: AsyncSession,
) -> set[ConsentType]:
    """The consent types the user has granted and not since revoked."""

    if settings.is_production:
        return await ConsentRepository(db).granted_for(user_id)
    return get_consent_repository(settings).granted_for(user_id)


async def user_from_token(
    token: str,
    settings: Settings,
    db: AsyncSession,
) -> AuthenticatedUser:
    """Validate a bearer token and resolve its current user."""

    claims = decode_access_token(
        token,
        settings,
    )

    user = await active_user(claims.user_id, settings, db)

    if user is None:
        raise TokenValidationError("user is unavailable")

    if user.email.lower() != claims.email.lower() or user.role != claims.role:
        raise TokenValidationError("token identity no longer matches the user")

    return user
