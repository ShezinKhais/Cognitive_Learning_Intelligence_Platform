"""Password-reset revocation tested against a real PostgreSQL account."""

import pytest

from app.auth.service import renew_token, user_from_token
from app.core.config import get_settings
from app.core.security import (
    TokenValidationError,
    create_access_token,
    create_refresh_token,
    decode_access_token,
    verify_password,
)
from app.models.user import User
from app.schemas.identity import Role
from app.services import accounts

from .session_support import add_lecturer


async def test_password_reset_revokes_both_token_types_in_postgres(db):
    _, factory, created = db
    user_id = await add_lecturer(factory, created)

    settings = get_settings().model_copy(
        update={"clip_env": "production", "clip_secret_key": "k" * 32}
    )

    async with factory() as session:
        user = await session.get(User, user_id)
        email = user.email

        assert user.token_version == 0

    old_access, _ = create_access_token(
        user_id=user_id,
        email=email,
        role=Role.LECTURER,
        settings=settings,
        token_version=0,
    )

    old_claims = decode_access_token(old_access, settings)

    old_refresh, _ = create_refresh_token(
        user_id=user_id,
        email=email,
        role=Role.LECTURER,
        settings=settings,
        auth_time=old_claims.auth_time,
        token_version=0,
    )

    # Both tokens authenticate before the reset.
    async with factory() as session:
        await user_from_token(old_access, settings, session)
        await renew_token(old_refresh, settings, session)

    # Perform a real administrator-style password reset.
    async with factory() as session:
        _, replacement_password = await accounts.reset_password(
            session, user_id
        )

    async with factory() as session:
        user = await session.get(User, user_id)

        assert user.token_version == 1
        assert verify_password(replacement_password, user.password_hash)

        # Previously issued access tokens are immediately rejected.
        with pytest.raises(TokenValidationError, match="security reset"):
            await user_from_token(old_access, settings, session)

        # Previously issued refresh tokens cannot renew the session.
        with pytest.raises(TokenValidationError, match="security reset"):
            await renew_token(old_refresh, settings, session)

    # New sign-in tokens using the latest account version work.
    new_access, _ = create_access_token(
        user_id=user_id,
        email=email,
        role=Role.LECTURER,
        settings=settings,
        token_version=1,
    )

    claims = decode_access_token(new_access, settings)

    new_refresh, _ = create_refresh_token(
        user_id=user_id,
        email=email,
        role=Role.LECTURER,
        settings=settings,
        auth_time=claims.auth_time,
        token_version=1,
    )

    async with factory() as session:
        current_user = await user_from_token(
            new_access, settings, session
        )
        renewed = await renew_token(
            new_refresh, settings, session
        )

    assert current_user.id == user_id
    assert decode_access_token(
        renewed.access_token, settings
    ).token_version == 1
