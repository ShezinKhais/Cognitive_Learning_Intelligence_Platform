"""Review regression tests for account-specific password revocation."""

import pytest

from app.auth.service import renew_token, user_from_token
from app.core.config import get_settings
from app.core.security import (
    TokenValidationError,
    create_access_token,
    create_refresh_token,
    decode_access_token,
    hash_password,
)
from app.models.audit_log import AuditLog
from app.models.user import User
from app.schemas.identity import Role
from app.services import accounts

from .session_support import add_lecturer, sign_in_as


def credentials(user_id, email, settings):
    access, _ = create_access_token(
        user_id=user_id,
        email=email,
        role=Role.LECTURER,
        settings=settings,
        token_version=0,
    )
    claims = decode_access_token(access, settings)
    refresh, _ = create_refresh_token(
        user_id=user_id,
        email=email,
        role=Role.LECTURER,
        settings=settings,
        auth_time=claims.auth_time,
        token_version=0,
    )
    return access, refresh


async def test_self_service_change_invalidates_old_tokens(db, app):
    from sqlalchemy import delete

    client, factory, created = db
    settings = get_settings().model_copy(
        update={"clip_env": "production", "clip_secret_key": "k" * 32}
    )
    app.dependency_overrides[get_settings] = lambda: settings

    user_id = await add_lecturer(factory, created)

    async with factory() as session:
        user = await session.get(User, user_id)
        user.password_hash = hash_password("old password with enough length")
        email = user.email
        await session.commit()

    old_access, old_refresh = credentials(user_id, email, settings)

    async with factory() as session:
        await user_from_token(old_access, settings, session)
        await renew_token(old_refresh, settings, session)

    sign_in_as(app, user_id, Role.LECTURER)

    try:
        response = client.post(
            "/api/v1/auth/password",
            json={
                "current_password": "old password with enough length",
                "new_password": "new password with enough length",
            },
        )
        assert response.status_code == 204, response.text

        async with factory() as session:
            user = await session.get(User, user_id)
            assert user.token_version == 1

            with pytest.raises(TokenValidationError, match="security reset"):
                await user_from_token(old_access, settings, session)

            with pytest.raises(TokenValidationError, match="security reset"):
                await renew_token(old_refresh, settings, session)
    finally:
        async with factory() as session:
            await session.execute(delete(AuditLog).where(AuditLog.user_id == user_id))
            await session.commit()


async def test_real_reset_preserves_other_account_tokens(db):
    _, factory, created = db
    settings = get_settings().model_copy(
        update={"clip_env": "production", "clip_secret_key": "k" * 32}
    )

    target_id = await add_lecturer(factory, created)
    other_id = await add_lecturer(factory, created)

    async with factory() as session:
        target = await session.get(User, target_id)
        other = await session.get(User, other_id)
        target_email = target.email
        other_email = other.email

    target_access, target_refresh = credentials(target_id, target_email, settings)
    other_access, other_refresh = credentials(other_id, other_email, settings)

    async with factory() as session:
        await accounts.reset_password(session, target_id)

    async with factory() as session:
        with pytest.raises(TokenValidationError, match="security reset"):
            await user_from_token(target_access, settings, session)

        with pytest.raises(TokenValidationError, match="security reset"):
            await renew_token(target_refresh, settings, session)

        other_user = await user_from_token(other_access, settings, session)
        renewed = await renew_token(other_refresh, settings, session)

        assert other_user.id == other_id
        assert decode_access_token(renewed.access_token, settings).token_version == 0
