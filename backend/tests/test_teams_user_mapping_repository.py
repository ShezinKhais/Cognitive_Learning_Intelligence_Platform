"""Tests for Microsoft Teams user identity mappings."""

import uuid

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.core.config import get_settings
from app.models.user import User
from app.repositories.teams_user_mapping_repository import (
    TeamsUserMappingRepository,
)

from .database_support import require_database


@pytest.fixture
async def db():
    require_database()
    engine = create_async_engine(get_settings().database_url, poolclass=NullPool)
    session_factory = async_sessionmaker(
        engine,
        class_=AsyncSession,
        expire_on_commit=False,
    )

    async with session_factory() as session:
        yield session
        await session.rollback()

    await engine.dispose()


async def test_teams_user_mappings_handle_unmatched_duplicates_and_relinks(
    db: AsyncSession,
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level("INFO", logger="clip.teams_identity")
    first_user = User(
        name="First Teams User",
        role="student",
        email=f"teams-first-{uuid.uuid4()}@example.com",
    )
    second_user = User(
        name="Second Teams User",
        role="student",
        email=f"teams-second-{uuid.uuid4()}@example.com",
    )
    db.add_all([first_user, second_user])
    await db.flush()

    repository = TeamsUserMappingRepository(db)

    unmatched = await repository.record_unmatched(
        tenant_id="tenant-a",
        teams_user_id="teams-user-a",
    )
    duplicate = await repository.record_unmatched(
        tenant_id="tenant-a",
        teams_user_id="teams-user-a",
    )

    assert unmatched.user_id is None
    assert duplicate.mapping_id == unmatched.mapping_id
    assert (
        await repository.user_for(
            tenant_id="tenant-a",
            teams_user_id="teams-user-a",
        )
        is None
    )

    linked = await repository.link_user(
        tenant_id="tenant-a",
        teams_user_id="teams-user-a",
        user_id=first_user.user_id,
    )

    assert linked.user_id == first_user.user_id
    assert (
        await repository.user_for(
            tenant_id="tenant-a",
            teams_user_id="teams-user-a",
        )
        == first_user.user_id
    )
    assert (
        await repository.teams_user_for(
            tenant_id="tenant-a",
            user_id=first_user.user_id,
        )
        == "teams-user-a"
    )

    # Seeing the same identity again must not erase an existing match.
    preserved = await repository.record_unmatched(
        tenant_id="tenant-a",
        teams_user_id="teams-user-a",
    )
    assert preserved.user_id == first_user.user_id

    # Reassigning the Teams identity removes the previous user's mapping.
    await repository.link_user(
        tenant_id="tenant-a",
        teams_user_id="teams-user-a",
        user_id=second_user.user_id,
    )
    assert "audit_event=TEAMS_USER_MAPPING_RELINK" in caplog.text
    assert "teams-user-a" not in caplog.text

    assert (
        await repository.teams_user_for(
            tenant_id="tenant-a",
            user_id=first_user.user_id,
        )
        is None
    )
    assert (
        await repository.user_for(
            tenant_id="tenant-a",
            teams_user_id="teams-user-a",
        )
        == second_user.user_id
    )

    # Reassigning the C.L.I.P. user removes their previous Teams identity.
    await repository.link_user(
        tenant_id="tenant-a",
        teams_user_id="teams-user-b",
        user_id=second_user.user_id,
    )

    assert (
        await repository.user_for(
            tenant_id="tenant-a",
            teams_user_id="teams-user-a",
        )
        is None
    )
    assert (
        await repository.teams_user_for(
            tenant_id="tenant-a",
            user_id=second_user.user_id,
        )
        == "teams-user-b"
    )

    await repository.record_unmatched(
        tenant_id="tenant-a",
        teams_user_id="teams-user-unmatched",
    )
    unmatched_rows = await repository.list_unmatched(tenant_id="tenant-a")

    assert [row.teams_user_id for row in unmatched_rows] == ["teams-user-unmatched"]
