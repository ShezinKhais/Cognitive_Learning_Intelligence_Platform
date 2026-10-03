"""Tests for Teams roster synchronization and participant matching."""

import uuid
from datetime import UTC, datetime

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.core.config import get_settings
from app.core.errors import ValidationError
from app.models.course import Course
from app.models.session import Session
from app.models.user import User
from app.repositories.teams_roster_repository import (
    MAX_ROSTER_PARTICIPANTS,
    RosterParticipantInput,
    TeamsRosterRepository,
)
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


async def test_roster_sync_classifies_records_and_is_idempotent(
    db: AsyncSession,
) -> None:
    lecturer = User(
        name="Roster Lecturer",
        role="lecturer",
        email=f"roster-lecturer-{uuid.uuid4()}@example.com",
    )
    matched_user = User(
        name="Mapped Student",
        role="student",
        email=f"roster-student-{uuid.uuid4()}@example.com",
    )
    course = Course(
        code=f"ROSTER-{uuid.uuid4().hex[:8]}",
        name="Teams Roster Persistence",
    )
    db.add_all([lecturer, matched_user, course])
    await db.flush()

    session = Session(
        instructor_id=lecturer.user_id,
        course_id=course.id,
        title="Roster session",
        start_time=datetime.now(UTC),
        end_time=None,
        mode="teams",
        status="scheduled",
    )
    db.add(session)
    await db.flush()

    identity_repository = TeamsUserMappingRepository(db)
    await identity_repository.link_user(
        tenant_id="tenant-a",
        teams_user_id="teams-user-matched",
        user_id=matched_user.user_id,
    )

    repository = TeamsRosterRepository(db)
    participants = [
        RosterParticipantInput(
            tenant_id="tenant-a",
            teams_user_id="teams-user-matched",
            display_name="Mapped Student",
        ),
        RosterParticipantInput(
            tenant_id="tenant-a",
            teams_user_id="teams-user-unmatched",
            display_name="Unknown Student",
        ),
        RosterParticipantInput(
            tenant_id=None,
            teams_user_id=None,
            display_name="Missing Identity",
        ),
        RosterParticipantInput(
            tenant_id="tenant-a",
            teams_user_id="teams-user-matched",
            display_name="Duplicate Student",
        ),
    ]

    sync = await repository.record_sync(
        meeting_id="meeting-roster",
        session_id=session.session_id,
        source_event_id="roster-event-1",
        event_type="snapshot",
        participants=participants,
    )
    rows = await repository.list_participants(sync.sync_id)

    assert sync.status == "processed"
    assert sync.participant_count == 4
    assert sync.matched_count == 1
    assert sync.unmatched_count == 1
    assert sync.missing_count == 1
    assert sync.duplicate_count == 1
    assert [row.match_status for row in rows] == [
        "matched",
        "unmatched",
        "missing",
        "duplicate",
    ]
    assert rows[0].user_id == matched_user.user_id
    assert rows[1].user_id is None
    assert rows[2].teams_user_id is None
    assert rows[3].reason == "Teams identity is duplicated in this roster event."

    unmatched = await identity_repository.list_unmatched(tenant_id="tenant-a")
    assert [row.teams_user_id for row in unmatched] == ["teams-user-unmatched"]

    repeated = await repository.record_sync(
        meeting_id="meeting-roster",
        session_id=session.session_id,
        source_event_id="roster-event-1",
        event_type="snapshot",
        participants=[],
    )
    repeated_rows = await repository.list_participants(repeated.sync_id)

    assert repeated.sync_id == sync.sync_id
    assert len(repeated_rows) == 4


async def test_roster_sync_rejects_an_oversized_event(
    db: AsyncSession,
) -> None:
    repository = TeamsRosterRepository(db)
    participants = [
        RosterParticipantInput(
            tenant_id=None,
            teams_user_id=None,
            display_name=None,
        )
        for _ in range(MAX_ROSTER_PARTICIPANTS + 1)
    ]

    with pytest.raises(
        ValidationError,
        match="Teams roster event contains too many participants",
    ):
        await repository.record_sync(
            meeting_id="meeting-oversized",
            session_id=None,
            source_event_id="oversized-event",
            event_type="snapshot",
            participants=participants,
        )
