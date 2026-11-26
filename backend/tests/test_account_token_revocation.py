"""Regression tests for account-level security session invalidation."""

from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.auth import service
from app.core.config import get_settings
from app.core.security import (
    TokenValidationError,
    create_access_token,
    create_refresh_token,
    decode_access_token,
    decode_refresh_token,
)
from app.models.user import User
from app.schemas.identity import Role
from app.services import accounts as account_service

from .session_support import add_lecturer


def settings():
    return get_settings().model_copy(update={"clip_env": "production", "clip_secret_key": "k" * 32})


def identity():
    return uuid4(), "lecturer@example.com", Role.LECTURER


def tokens(user_id, email, role, version):
    config = settings()
    access, _ = create_access_token(
        user_id=user_id,
        email=email,
        role=role,
        settings=config,
        token_version=version,
    )
    claims = decode_access_token(access, config)
    refresh, _ = create_refresh_token(
        user_id=user_id,
        email=email,
        role=role,
        settings=config,
        auth_time=claims.auth_time,
        token_version=version,
    )
    return access, refresh


def test_access_and_refresh_preserve_security_version():
    user_id, email, role = identity()
    access, refresh = tokens(user_id, email, role, 7)

    assert decode_access_token(access, settings()).token_version == 7
    assert decode_refresh_token(refresh, settings()).token_version == 7


def test_invalid_token_versions_are_rejected():
    user_id, email, role = identity()

    for bad in (-1, "1", None, True):
        import jwt

        now = datetime.now(UTC)
        from datetime import timedelta

        payload = {
            "sub": str(user_id),
            "email": email,
            "role": role.value,
            "iat": now,
            "exp": now + timedelta(minutes=10),
            "token_version": bad,
        }
        encoded = jwt.encode(payload, settings().clip_secret_key, algorithm="HS256")
        with pytest.raises(TokenValidationError):
            decode_access_token(encoded, settings())


@pytest.mark.asyncio
async def test_reset_invalidates_old_access_and_refresh_tokens(monkeypatch):
    user_id, email, role = identity()
    account = SimpleNamespace(
        user_id=user_id,
        id=user_id,
        email=email,
        role=role.value,
        active=True,
        token_version=0,
    )

    class Repository:
        def __init__(self, db):
            pass

        async def get_by_id(self, requested):
            return account if requested == user_id else None

    monkeypatch.setattr(service, "UserRepository", Repository)

    old_access, old_refresh = tokens(user_id, email, role, 0)

    # Before the reset, both tokens belong to this account.
    await service.user_from_token(old_access, settings(), None)
    await service.renew_token(old_refresh, settings(), None)

    # Simulate the committed version increment performed by password reset.
    account.token_version = 1

    with pytest.raises(TokenValidationError, match="security reset"):
        await service.user_from_token(old_access, settings(), None)

    with pytest.raises(TokenValidationError, match="security reset"):
        await service.renew_token(old_refresh, settings(), None)

    # New website or Teams sign-in uses the current account version.
    new_access, new_refresh = tokens(user_id, email, role, 1)

    await service.user_from_token(new_access, settings(), None)
    renewed = await service.renew_token(new_refresh, settings(), None)

    assert decode_access_token(renewed.access_token, settings()).token_version == 1


@pytest.mark.asyncio
async def test_other_accounts_are_not_revoked(db):
    """A real password reset must not revoke a different account's tokens."""
    _, factory, created = db

    first_id = await add_lecturer(factory, created)
    second_id = await add_lecturer(factory, created)

    async with factory() as session:
        first = await session.get(User, first_id)
        second = await session.get(User, second_id)

        first_email = first.email
        second_email = second.email

    first_access, first_refresh = tokens(first_id, first_email, Role.LECTURER, 0)
    other_access, other_refresh = tokens(second_id, second_email, Role.LECTURER, 0)

    # Both accounts authenticate before the administrator resets the first.
    async with factory() as session:
        await service.user_from_token(first_access, settings(), session)
        await service.renew_token(first_refresh, settings(), session)
        await service.user_from_token(other_access, settings(), session)
        await service.renew_token(other_refresh, settings(), session)

    # Invoke the actual password-reset service, including its database commit.
    async with factory() as session:
        await account_service.reset_password(session, first_id)

    async with factory() as session:
        first = await session.get(User, first_id)
        second = await session.get(User, second_id)

        assert first.token_version == 1
        assert second.token_version == 0

        with pytest.raises(TokenValidationError, match="security reset"):
            await service.user_from_token(first_access, settings(), session)

        with pytest.raises(TokenValidationError, match="security reset"):
            await service.renew_token(first_refresh, settings(), session)

        still_active = await service.user_from_token(other_access, settings(), session)
        renewed = await service.renew_token(other_refresh, settings(), session)

        assert still_active.id == second_id
        assert decode_access_token(renewed.access_token, settings()).token_version == 0


def test_legacy_version_zero_tokens_remain_compatible():
    user_id, email, role = identity()
    access, refresh = tokens(user_id, email, role, 0)

    assert decode_access_token(access, settings()).token_version == 0
    assert decode_refresh_token(refresh, settings()).token_version == 0
