"""Password hashing and signed access-token helpers.

The functions in this module contain no FastAPI code, which keeps them usable
from HTTP routes, WebSocket authentication and tests.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import UUID

import jwt

from app.core.config import Settings
from app.schemas.identity import Role

PASSWORD_SCHEME = "pbkdf2_sha256"
PASSWORD_ITERATIONS = 600_000

# Phase 1 uses one fixed JWT algorithm in every environment.
JWT_ALGORITHM = "HS256"

# Marks a refresh token. An access token carries no "typ", so tokens issued
# before refresh tokens existed still decode as access tokens.
REFRESH_TOKEN_TYPE = "refresh"

# Used when an email does not exist so login still performs an expensive
# password verification and does not reveal registered emails through timing.
DUMMY_PASSWORD_HASH = (
    "pbkdf2_sha256$600000$Q0xJUGR1bW15aGFzaDEyMw==$6HsrKfB216tUzMDFP5fxt2-u35x_US-yzfbMSVRaAqE="
)


class TokenValidationError(ValueError):
    """Raised when a bearer token cannot be trusted."""


@dataclass(frozen=True, slots=True)
class TokenClaims:
    user_id: UUID
    role: Role
    email: str
    # When the user typed their password. A refreshed token keeps the time of
    # the sign-in it came from, so the sign-in as a whole can be capped.
    auth_time: datetime


def hash_password(password: str) -> str:
    """Hash a password with salted PBKDF2-HMAC-SHA256."""
    if not password:
        raise ValueError("password cannot be empty")

    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        salt,
        PASSWORD_ITERATIONS,
    )

    return "$".join(
        (
            PASSWORD_SCHEME,
            str(PASSWORD_ITERATIONS),
            base64.urlsafe_b64encode(salt).decode("ascii"),
            base64.urlsafe_b64encode(digest).decode("ascii"),
        )
    )


def verify_password(password: str, password_hash: str) -> bool:
    """Verify a password without revealing parsing or timing details."""
    try:
        scheme, iterations_raw, salt_raw, expected_raw = password_hash.split("$", 3)

        if scheme != PASSWORD_SCHEME:
            return False

        iterations = int(iterations_raw)
        salt = base64.urlsafe_b64decode(salt_raw.encode("ascii"))
        expected = base64.urlsafe_b64decode(expected_raw.encode("ascii"))

        actual = hashlib.pbkdf2_hmac(
            "sha256",
            password.encode("utf-8"),
            salt,
            iterations,
        )

        return hmac.compare_digest(actual, expected)

    except (TypeError, ValueError):
        return False


def create_access_token(
    *,
    user_id: UUID,
    role: Role,
    email: str,
    settings: Settings,
    expires_delta: timedelta | None = None,
    auth_time: datetime | None = None,
) -> tuple[str, int]:
    """Create a signed JWT and return it with its lifetime in seconds.

    `auth_time` is the sign-in the token belongs to, now for a login. No token
    outlives that sign-in by more than max_sign_in_hours, so a refreshed token
    is cut short when the cap is near.
    """
    lifetime = expires_delta or timedelta(minutes=settings.access_token_expire_minutes)

    now = datetime.now(UTC)
    signed_in = auth_time or now
    expires_at = min(now + lifetime, signed_in + timedelta(hours=settings.max_sign_in_hours))
    lifetime = expires_at - now

    payload = {
        "sub": str(user_id),
        "role": role.value,
        "email": email,
        "iat": now,
        "exp": expires_at,
        "auth_time": int(signed_in.timestamp()),
    }

    token = jwt.encode(
        payload,
        settings.clip_secret_key,
        algorithm=JWT_ALGORITHM,
    )

    return token, max(0, int(lifetime.total_seconds()))


def decode_access_token(token: str, settings: Settings) -> TokenClaims:
    """Validate a JWT's signature, expiry and required identity claims."""
    try:
        payload = jwt.decode(
            token,
            settings.clip_secret_key,
            algorithms=[JWT_ALGORITHM],
            options={"require": ["sub", "role", "email", "iat", "exp"]},
        )

        user_id = UUID(str(payload["sub"]))
        role = Role(str(payload["role"]))
        email = str(payload["email"]).strip().lower()
        # Tokens issued before auth_time was added began their sign-in when
        # they were issued.
        auth_time = datetime.fromtimestamp(int(payload.get("auth_time", payload["iat"])), UTC)

        if not email:
            raise ValueError("empty email")

        # A refresh token is signed with the same key and must never be
        # accepted where an access token is expected.
        if payload.get("typ") is not None:
            raise ValueError("not an access token")

    except (jwt.PyJWTError, KeyError, TypeError, ValueError) as exc:
        raise TokenValidationError("invalid or expired access token") from exc

    return TokenClaims(
        user_id=user_id,
        role=role,
        email=email,
        auth_time=auth_time,
    )


def create_refresh_token(
    *,
    user_id: UUID,
    role: Role,
    email: str,
    settings: Settings,
    auth_time: datetime,
) -> tuple[str, int]:
    """Create the token kept in the httpOnly refresh cookie.

    It lasts as long as the sign-in may, max_sign_in_hours from auth_time,
    and only ever buys access tokens: decode_access_token refuses it.
    """
    now = datetime.now(UTC)
    expires_at = auth_time + timedelta(hours=settings.max_sign_in_hours)

    payload = {
        "typ": REFRESH_TOKEN_TYPE,
        "sub": str(user_id),
        "role": role.value,
        "email": email,
        "iat": now,
        "exp": expires_at,
        "auth_time": int(auth_time.timestamp()),
    }

    token = jwt.encode(payload, settings.clip_secret_key, algorithm=JWT_ALGORITHM)
    return token, max(0, int((expires_at - now).total_seconds()))


def decode_refresh_token(token: str, settings: Settings) -> TokenClaims:
    """Validate a refresh token: signature, expiry, type and identity claims."""
    try:
        payload = jwt.decode(
            token,
            settings.clip_secret_key,
            algorithms=[JWT_ALGORITHM],
            options={"require": ["typ", "sub", "role", "email", "iat", "exp", "auth_time"]},
        )

        if payload["typ"] != REFRESH_TOKEN_TYPE:
            raise ValueError("not a refresh token")

        user_id = UUID(str(payload["sub"]))
        role = Role(str(payload["role"]))
        email = str(payload["email"]).strip().lower()
        auth_time = datetime.fromtimestamp(int(payload["auth_time"]), UTC)

        if not email:
            raise ValueError("empty email")

    except (jwt.PyJWTError, KeyError, TypeError, ValueError) as exc:
        raise TokenValidationError("invalid or expired refresh token") from exc

    return TokenClaims(user_id=user_id, role=role, email=email, auth_time=auth_time)


def extract_bearer_token(authorization: str | None) -> str:
    """Extract a bearer token without accepting alternate or ambiguous schemes."""
    if not authorization:
        raise TokenValidationError("authorization header missing")

    scheme, separator, token = authorization.partition(" ")

    if not separator or scheme.lower() != "bearer" or not token.strip():
        raise TokenValidationError("authorization header is not a bearer token")

    return token.strip()
