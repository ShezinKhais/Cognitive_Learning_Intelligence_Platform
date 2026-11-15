"""A signed-in user changing their own password."""

from __future__ import annotations

import asyncio

from sqlalchemy import delete, select

from app.core.config import get_settings
from app.core.security import hash_password, verify_password
from app.models.audit_log import AuditLog
from app.models.user import User
from app.schemas.identity import Role

from .session_support import add_lecturer, db, sign_in_as  # noqa: F401

PATH = "/api/v1/auth/password"
OLD = "an old password that works"
NEW = "a brand new long password"


def test_development_accounts_keep_their_fixed_passwords(client) -> None:  # noqa: ANN001
    from app.api.deps import Principal, get_principal
    from app.auth.store import LECTURER_ID

    client.app.dependency_overrides[get_principal] = lambda: Principal(
        user_id=LECTURER_ID, role=Role.LECTURER, email="lecturer@clip.example.com"
    )
    try:
        response = client.post(PATH, json={"current_password": OLD, "new_password": NEW})
    finally:
        client.app.dependency_overrides.clear()
    assert response.status_code == 409


async def test_a_user_changes_their_password_with_the_current_one(db, app) -> None:  # noqa: F811
    client, factory, created = db
    production = get_settings().model_copy(update={"clip_env": "production"})
    app.dependency_overrides[get_settings] = lambda: production
    user_id = await add_lecturer(factory, created)
    async with factory() as seed:
        user = await seed.get(User, user_id)
        user.password_hash = hash_password(OLD)
        await seed.commit()
    sign_in_as(app, user_id, Role.LECTURER)

    try:
        wrong = client.post(PATH, json={"current_password": "not it at all", "new_password": NEW})
        short = client.post(PATH, json={"current_password": OLD, "new_password": "short"})
        same = client.post(PATH, json={"current_password": OLD, "new_password": OLD})
        changed = client.post(PATH, json={"current_password": OLD, "new_password": NEW})

        assert wrong.status_code == 422
        assert short.status_code == 422
        assert same.status_code == 422
        assert changed.status_code == 204, changed.text
        async with factory() as look:
            stored = await look.get(User, user_id)
            assert verify_password(NEW, stored.password_hash)
            assert not verify_password(OLD, stored.password_hash)
            changes = await look.scalars(
                select(AuditLog.action_type).where(
                    AuditLog.user_id == user_id, AuditLog.action_type == "PASSWORD_CHANGED"
                )
            )
            # One change, and nothing recorded for the refused attempts.
            assert list(changes) == ["PASSWORD_CHANGED"]
    finally:
        # The failed attempt and the change are audited against this user.
        async with factory() as cleanup:
            await cleanup.execute(delete(AuditLog).where(AuditLog.user_id == user_id))
            await cleanup.commit()


async def test_a_second_change_waits_and_checks_the_new_password(db, app) -> None:  # noqa: F811
    """Two changes at once: the second waits for the first and must then
    give the password the first one set."""
    client, factory, created = db
    production = get_settings().model_copy(update={"clip_env": "production"})
    app.dependency_overrides[get_settings] = lambda: production
    user_id = await add_lecturer(factory, created)
    async with factory() as seed:
        user = await seed.get(User, user_id)
        user.password_hash = hash_password(OLD)
        await seed.commit()
    sign_in_as(app, user_id, Role.LECTURER)
    other = "the password the first change set"

    try:
        async with factory() as first:
            held = await first.get(User, user_id, with_for_update=True)
            second = asyncio.create_task(
                asyncio.to_thread(
                    client.post, PATH, json={"current_password": OLD, "new_password": NEW}
                )
            )
            # Long enough for the second request to read the user while the
            # first holds the row.
            await asyncio.sleep(1.0)
            held.password_hash = hash_password(other)
            await first.commit()
        response = await asyncio.wait_for(second, 30)

        assert response.status_code == 422, response.text
        async with factory() as look:
            stored = await look.get(User, user_id)
            assert verify_password(other, stored.password_hash)
    finally:
        async with factory() as cleanup:
            await cleanup.execute(delete(AuditLog).where(AuditLog.user_id == user_id))
            await cleanup.commit()
