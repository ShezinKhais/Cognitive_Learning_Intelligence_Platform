"""Password changes must succeed even if socket revocation fails."""

from unittest.mock import AsyncMock

from sqlalchemy import delete

from app.auth.store import ADMIN_ID
from app.core.config import get_settings
from app.core.security import hash_password
from app.models.audit_log import AuditLog
from app.models.user import User
from app.realtime.hub import hub
from app.schemas.identity import Role

from .session_support import add_lecturer, sign_in_as


async def test_self_service_change_survives_socket_failure(db, app, monkeypatch):
    client, factory, created = db
    settings = get_settings().model_copy(
        update={
            "clip_env": "production",
            "clip_secret_key": "k" * 32,
        }
    )
    app.dependency_overrides[get_settings] = lambda: settings

    user_id = await add_lecturer(factory, created)

    async with factory() as session:
        user = await session.get(User, user_id)
        user.password_hash = hash_password("my previous long password")
        await session.commit()

    sign_in_as(app, user_id, Role.LECTURER)

    closing = AsyncMock(side_effect=RuntimeError("simulated socket error"))
    monkeypatch.setattr(hub, "close_user_sessions", closing)

    try:
        response = client.post(
            "/api/v1/auth/password",
            json={
                "current_password": "my previous long password",
                "new_password": "my replacement long password",
            },
        )

        assert response.status_code == 204, response.text
        closing.assert_awaited_once_with(
            user_id,
            4001,
            "account credentials changed",
            include_user_channel=True,
        )

        async with factory() as session:
            user = await session.get(User, user_id)
            assert user.token_version == 1
    finally:
        async with factory() as session:
            await session.execute(delete(AuditLog).where(AuditLog.user_id == user_id))
            await session.commit()


async def test_admin_reset_survives_socket_failure(db, app, monkeypatch):
    client, factory, created = db
    target_id = await add_lecturer(factory, created)

    sign_in_as(app, ADMIN_ID, Role.ADMIN)

    closing = AsyncMock(side_effect=RuntimeError("simulated socket error"))
    monkeypatch.setattr(hub, "close_user_sessions", closing)

    try:
        response = client.post(f"/api/v1/admin/accounts/{target_id}/password")

        assert response.status_code == 200, response.text
        closing.assert_awaited_once_with(
            target_id,
            4001,
            "account credentials changed",
            include_user_channel=True,
        )

        async with factory() as session:
            target = await session.get(User, target_id)
            assert target.token_version == 1
    finally:
        async with factory() as session:
            await session.execute(delete(AuditLog).where(AuditLog.target_id == target_id))
            await session.commit()
