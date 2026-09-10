"""Authentication service shared by HTTP and WebSocket entry points."""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.store import get_user_repository
from app.core.config import Settings
from app.core.security import (
    TokenValidationError,
    decode_access_token,
)
from app.repositories.user_repository import UserRepository
from app.schemas.identity import Role


@dataclass(frozen=True, slots=True)
class AuthenticatedUser:
    id: UUID
    email: str
    role: Role


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

    if settings.is_production:
        repository = UserRepository(db)

        user = await repository.get_by_id(claims.user_id)
    else:
        user = get_user_repository(settings).get_by_id(claims.user_id)

    if user is None or not user.active:
        raise TokenValidationError("user is unavailable")

    role = user.role if isinstance(user.role, Role) else Role(user.role)

    if user.email.lower() != claims.email.lower() or role != claims.role:
        raise TokenValidationError("token identity no longer matches the user")

    return AuthenticatedUser(
        id=user.id,
        email=user.email,
        role=role,
    )
