"""Tests for persistent Teams meeting-to-session links."""

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime

import pytest
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.core.config import get_settings
from app.models.course import Course
from app.models.session import Session
from app.models.teams_meeting_link import TeamsMeetingLink
from app.models.user import User
from app.repositories.teams_meeting_repository import DatabaseMeetingDirectory

from .database_support import require_database


@dataclass(frozen=True)
class MeetingStoreSetup:
    directory: DatabaseMeetingDirectory
    first_session_id: uuid.UUID
    second_session_id: uuid.UUID


@pytest.fixture
async def meeting_store() -> MeetingStoreSetup:
    require_database()
    engine = create_async_engine(get_settings().database_url, poolclass=NullPool)
    session_factory = async_sessionmaker(
        engine,
        class_=AsyncSession,
        expire_on_commit=False,
    )

    lecturer_id: uuid.UUID
    course_id: uuid.UUID
    first_session_id: uuid.UUID
    second_session_id: uuid.UUID

    async with session_factory() as session:
        lecturer = User(
            name="Teams Lecturer",
            role="lecturer",
            email=f"teams-lecturer-{uuid.uuid4()}@example.com",
        )
        course = Course(
            code=f"TEAMS-{uuid.uuid4().hex[:8]}",
            name="Teams Persistence",
        )
        session.add_all([lecturer, course])
        await session.flush()

        first_session = Session(
            instructor_id=lecturer.user_id,
            course_id=course.id,
            title="First Teams session",
            start_time=datetime.now(UTC),
            end_time=None,
            mode="teams",
            status="scheduled",
        )
        second_session = Session(
            instructor_id=lecturer.user_id,
            course_id=course.id,
            title="Second Teams session",
            start_time=datetime.now(UTC),
            end_time=None,
            mode="teams",
            status="scheduled",
        )
        session.add_all([first_session, second_session])
        await session.commit()

        lecturer_id = lecturer.user_id
        course_id = course.id
        first_session_id = first_session.session_id
        second_session_id = second_session.session_id

    try:
        yield MeetingStoreSetup(
            directory=DatabaseMeetingDirectory(session_factory),
            first_session_id=first_session_id,
            second_session_id=second_session_id,
        )
    finally:
        async with session_factory() as session:
            await session.execute(
                delete(TeamsMeetingLink).where(
                    TeamsMeetingLink.session_id.in_([first_session_id, second_session_id])
                )
            )
            await session.execute(
                delete(Session).where(Session.session_id.in_([first_session_id, second_session_id]))
            )
            await session.execute(delete(Course).where(Course.id == course_id))
            await session.execute(delete(User).where(User.user_id == lecturer_id))
            await session.commit()

        await engine.dispose()


async def test_meeting_links_persist_and_replace_both_sides(
    meeting_store: MeetingStoreSetup,
) -> None:
    directory = meeting_store.directory
    first_session_id = meeting_store.first_session_id
    second_session_id = meeting_store.second_session_id

    assert await directory.session_for("meeting-a") is None
    assert await directory.meeting_for(first_session_id) is None

    await directory.link("meeting-a", first_session_id)

    assert await directory.session_for("meeting-a") == first_session_id
    assert await directory.meeting_for(first_session_id) == "meeting-a"

    # Moving the meeting removes its previous session association.
    await directory.link("meeting-a", second_session_id)

    assert await directory.meeting_for(first_session_id) is None
    assert await directory.session_for("meeting-a") == second_session_id

    # Moving the session removes its previous meeting association.
    await directory.link("meeting-b", second_session_id)

    assert await directory.session_for("meeting-a") is None
    assert await directory.session_for("meeting-b") == second_session_id
    assert await directory.meeting_for(second_session_id) == "meeting-b"

    # A duplicated Teams event remains idempotent.
    await directory.link("meeting-b", second_session_id)

    assert await directory.session_for("meeting-b") == second_session_id
    assert await directory.meeting_for(second_session_id) == "meeting-b"
