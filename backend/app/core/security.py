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
) -> tuple[str, int]:
    """Create a signed JWT and return it with its lifetime in seconds."""
    lifetime = expires_delta or timedelta(minutes=settings.access_token_expire_minutes)

    now = datetime.now(UTC)
    expires_at = now + lifetime

    payload = {
        "sub": str(user_id),
        "role": role.value,
        "email": email,
        "iat": now,
        "exp": expires_at,
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

        if not email:
            raise ValueError("empty email")

    except (jwt.PyJWTError, KeyError, TypeError, ValueError) as exc:
        raise TokenValidationError("invalid or expired access token") from exc

    return TokenClaims(
        user_id=user_id,
        role=role,
        email=email,
    )


def extract_bearer_token(authorization: str | None) -> str:
    """Extract a bearer token without accepting alternate or ambiguous schemes."""
    if not authorization:
        raise TokenValidationError("authorization header missing")

    scheme, separator, token = authorization.partition(" ")

    if not separator or scheme.lower() != "bearer" or not token.strip():
        raise TokenValidationError("authorization header is not a bearer token")

    return token.strip()
