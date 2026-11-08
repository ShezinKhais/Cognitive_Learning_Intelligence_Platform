"""Is this a class? Starting one from a Teams meeting with no session,
against a real database. Commits become flushes and every test is rolled
back."""

import uuid

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.api.deps import Principal
from app.core.config import get_settings
from app.models.course import Course
from app.models.course_enrollment import CourseLecturer
from app.models.session import Session
from app.models.teams_meeting_reference import TeamsMeetingReference
from app.models.user import User
from app.schemas.identity import Role
from app.schemas.meetings import MeetingClassStart
from app.services import unscheduled_class

from .database_support import require_database


@pytest.fixture
async def db():
    require_database()
    engine = create_async_engine(get_settings().database_url, poolclass=NullPool)
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as session:
        session.commit = session.flush  # type: ignore[method-assign]
        yield session
        await session.rollback()
    await engine.dispose()


@pytest.fixture
async def world(db):
    taught = Course(code=f"UC{uuid.uuid4().hex[:6]}".upper(), name="Taught")
    # A realistic code, letters then digits, so a title can name it.
    other = Course(code=f"ZQ{uuid.uuid4().int % 9000 + 1000}", name="Other")
    lecturer = User(name="Lecturer", role="lecturer", email=f"{uuid.uuid4().hex}@t.test")
    db.add_all([taught, other, lecturer])
    await db.flush()
    db.add(CourseLecturer(course_id=taught.id, user_id=lecturer.user_id))
    await db.flush()
    return taught, other, Principal(lecturer.user_id, Role.LECTURER, lecturer.email)


async def test_the_course_named_in_the_meeting_title_is_offered(db, world) -> None:
    taught, other, lecturer = world
    suggestion = await unscheduled_class.suggest(db, lecturer, f"{other.code} Week 5 Lecture")
    assert suggestion.course_code == other.code
    assert suggestion.title == f"{other.code} Week 5 Lecture"
    assert [c.code for c in suggestion.courses] == [taught.code]


async def test_with_no_code_in_the_title_the_lecturers_own_course_is_offered(db, world) -> None:
    taught, _, lecturer = world
    suggestion = await unscheduled_class.suggest(db, lecturer, "Revision catch-up")
    assert suggestion.course_code == taught.code
    untitled = await unscheduled_class.suggest(db, lecturer, None)
    assert untitled.title == "Class" and untitled.meeting_title is None


async def test_the_meeting_title_is_read_from_teams(db, monkeypatch) -> None:
    meeting_id = f"meeting-{uuid.uuid4().hex}"
    settings = get_settings().model_copy(update={"teams_notifications_enabled": True})
    db.add(
        TeamsMeetingReference(
            meeting_id=meeting_id,
            service_url="https://smba.trafficmanager.net/emea/",
            conversation_id="19:meeting",
            tenant_id=settings.tenant_id or "tenant",
        )
    )
    await db.flush()

    async def details(_settings, _url, _meeting):
        return {"details": {"title": "  CSIT321 Week 5  "}}

    async def broken(_settings, _url, _meeting):
        raise ValueError("no body")

    assert (
        await unscheduled_class.meeting_title(db, meeting_id, settings, details) == "CSIT321 Week 5"
    )
    assert await unscheduled_class.meeting_title(db, meeting_id, settings, broken) is None
    assert await unscheduled_class.meeting_title(db, "unknown", settings, details) is None


async def test_yes_creates_links_and_starts_the_class(db, world) -> None:
    taught, _, lecturer = world
    checked = []

    async def organiser(_db, principal, meeting_id, _settings):
        checked.append((principal.user_id, meeting_id))

    meeting_id = f"meeting-{uuid.uuid4().hex}"
    started = await unscheduled_class.start_class(
        db,
        lecturer,
        meeting_id,
        MeetingClassStart(course_code=taught.code, title="Unplanned revision"),
        get_settings(),
        check_organiser=organiser,
    )
    assert checked == [(lecturer.user_id, meeting_id)]
    assert started.status == "active" and started.title == "Unplanned revision"
    row = await db.get(Session, started.id)
    assert row is not None and row.course_id == taught.id and row.mode == "teams"
