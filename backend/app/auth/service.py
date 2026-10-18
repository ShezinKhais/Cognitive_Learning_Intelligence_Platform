"""Authentication service shared by HTTP and WebSocket entry points."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.store import get_consent_repository, get_user_repository
from app.core.config import Settings
from app.core.security import (
    TokenClaims,
    TokenValidationError,
    create_access_token,
    decode_access_token,
    decode_refresh_token,
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

    return await _holder(claims, settings, db)


async def _holder(
    claims: TokenClaims,
    settings: Settings,
    db: AsyncSession,
) -> AuthenticatedUser:
    """The account a token's claims name, while it still matches them."""

    user = await active_user(claims.user_id, settings, db)

    if user is None:
        raise TokenValidationError("user is unavailable")

    if user.email.lower() != claims.email.lower() or user.role != claims.role:
        raise TokenValidationError("token identity no longer matches the user")

    return user


@dataclass(frozen=True, slots=True)
class RenewedToken:
    access_token: str
    expires_in: int
    user: AuthenticatedUser


async def renew_token(
    refresh_token: str,
    settings: Settings,
    db: AsyncSession,
) -> RenewedToken:
    """A fresh access token for the holder of a still-valid refresh token.

    The refresh token lives in an httpOnly cookie, so a script on the page
    cannot read it, and an access token is refused here: one stolen from the
    page dies at its own expiry instead of being renewed. The account is
    checked again as it stands now: it must exist, be active and have the
    role the sign-in was for. The new token keeps the original sign-in time,
    and none is issued once max_sign_in_hours have passed since it, so
    refreshing never stands in for signing in.
    """

    claims = decode_refresh_token(refresh_token, settings)
    user = await _holder(claims, settings, db)

    if datetime.now(UTC) >= claims.auth_time + timedelta(hours=settings.max_sign_in_hours):
        raise TokenValidationError("sign-in has reached its maximum length")

    renewed, expires_in = create_access_token(
        user_id=user.id,
        role=user.role,
        email=user.email,
        settings=settings,
        auth_time=claims.auth_time,
    )
    return RenewedToken(access_token=renewed, expires_in=expires_in, user=user)
