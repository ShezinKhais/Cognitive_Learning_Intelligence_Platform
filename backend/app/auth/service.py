"""Authentication service shared by HTTP and WebSocket entry points."""

from __future__ import annotations

from app.auth.store import UserRecord, get_user_repository
from app.core.config import Settings
from app.core.security import TokenValidationError, decode_access_token


def user_from_token(token: str, settings: Settings) -> UserRecord:
    claims = decode_access_token(token, settings)
    user = get_user_repository(settings).get_by_id(claims.user_id)

    if user is None or not user.active:
        raise TokenValidationError("user is unavailable")
    if user.email.lower() != claims.email or user.role is not claims.role:
        raise TokenValidationError("token identity no longer matches the user")
    return user
