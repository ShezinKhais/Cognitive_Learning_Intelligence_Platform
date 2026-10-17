"""The audit log: writing entries, reading them back, and keeping personal
content out of them. Database tests run against a real database."""

import uuid
from types import SimpleNamespace

import pytest
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.core.config import get_settings
from app.models.audit_log import AuditLog
from app.models.user import User
from app.repositories.audit_repository import checked_details, list_events, record_event

from .database_support import require_database

# --------------------------------------------------------------------------
# What may be written
# --------------------------------------------------------------------------


def test_details_keep_counts_flags_and_short_text():
    details = {"rows": 42, "dry_run": True, "ratio": 0.5, "reason": "retention", "none": None}
    assert checked_details(details) == details


def test_details_reject_a_nested_value():
    with pytest.raises(ValueError):
        checked_details({"answers": ["free text a student wrote"]})


def test_details_reject_long_text():
    with pytest.raises(ValueError):
        checked_details({"note": "x" * 201})


async def test_an_entry_needs_a_sensible_action_name():
    with pytest.raises(ValueError):
        await record_event(None, action_type="")
    with pytest.raises(ValueError):
        await record_event(None, action_type="x" * 101)


# --------------------------------------------------------------------------
# Storing and reading entries, against a real database
# --------------------------------------------------------------------------


@pytest.fixture
async def database():
    require_database()
    engine = create_async_engine(get_settings().database_url, poolclass=NullPool)
    yield async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    await engine.dispose()


@pytest.fixture
async def audit(database):
    """A real user to act as, and a target type unique to this test so its rows
    can be told apart and removed afterwards."""
    marker = f"test-{uuid.uuid4().hex[:12]}"
    async with database() as db:
        actor = User(name="Audit Admin", role="admin", email=f"a-{uuid.uuid4()}@example.com")
        db.add(actor)
        await db.commit()
        ids = SimpleNamespace(user=actor.user_id, marker=marker)

    yield ids

    async with database() as db:
        await db.execute(delete(AuditLog).where(AuditLog.target_type == ids.marker))
        await db.execute(delete(AuditLog).where(AuditLog.user_id == ids.user))
        await db.execute(delete(User).where(User.user_id == ids.user))
        await db.commit()


async def test_an_entry_keeps_its_actor_target_and_details(database, audit):
    target = uuid.uuid4()
    async with database() as db:
        await record_event(
            db,
            action_type="DELETION_APPROVED",
            user_id=audit.user,
            target_type=audit.marker,
            target_id=target,
            details={"rows": 12},
        )
        await db.commit()

    async with database() as db:
        [entry], total = await list_events(db, target_type=audit.marker)

    assert total == 1
    assert entry.action_type == "DELETION_APPROVED"
    assert entry.user_id == audit.user
    assert entry.target_id == target
    assert entry.details == {"rows": 12}
    assert entry.timestamp is not None


async def test_a_system_action_needs_no_user(database, audit):
    async with database() as db:
        await record_event(
            db,
            action_type="RETENTION_PURGE",
            target_type=audit.marker,
            details={"sessions": 3, "dry_run": False},
        )
        await db.commit()

    async with database() as db:
        [entry], _ = await list_events(db, target_type=audit.marker)

    assert entry.user_id is None
    assert entry.details == {"sessions": 3, "dry_run": False}


async def test_entries_come_back_newest_first_and_can_be_paged(database, audit):
    for number in range(3):
        async with database() as db:
            await record_event(
                db,
                action_type="TEST_STEP",
                user_id=audit.user,
                target_type=audit.marker,
                details={"step": number},
            )
            await db.commit()

    async with database() as db:
        rows, total = await list_events(db, target_type=audit.marker)
        page, page_total = await list_events(db, target_type=audit.marker, limit=2, offset=2)

    assert total == page_total == 3
    assert [row.details["step"] for row in rows] == [2, 1, 0]
    assert [row.details["step"] for row in page] == [0]


async def test_entries_can_be_filtered_by_action_and_actor(database, audit):
    async with database() as db:
        await record_event(db, action_type="TEST_A", user_id=audit.user, target_type=audit.marker)
        await record_event(db, action_type="TEST_B", user_id=audit.user, target_type=audit.marker)
        await db.commit()

    async with database() as db:
        only_a, total = await list_events(db, action_type="TEST_A", user_id=audit.user)

    assert total == 1
    assert [row.action_type for row in only_a] == ["TEST_A"]
