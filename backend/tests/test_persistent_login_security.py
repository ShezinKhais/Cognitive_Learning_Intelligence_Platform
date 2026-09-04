"""Tests for production-persistent login lockout state."""

from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import uuid4

import pytest

from app.auth.login_security import (
    ACCOUNT_LOCKED_ACTION,
    LOGIN_FAILED_ACTION,
    LOGIN_SUCCEEDED_ACTION,
    PersistentLoginSecurityStore,
)
from app.models.audit_log import AuditLog


class FakeResult:
    def __init__(self, value: Any = None) -> None:
        self.value = value

    def scalar_one_or_none(self) -> Any:
        return self.value

    def scalar_one(self) -> Any:
        return self.value


class FakeSession:
    def __init__(self, results: list[FakeResult]) -> None:
        self.results = iter(results)
        self.added: list[AuditLog] = []
        self.flush_count = 0
        self.commit_count = 0

    async def execute(self, _statement: Any) -> FakeResult:
        return next(self.results)

    def add(self, record: AuditLog) -> None:
        self.added.append(record)

    async def flush(self) -> None:
        self.flush_count += 1

    async def commit(self) -> None:
        self.commit_count += 1


@pytest.mark.asyncio
async def test_account_is_locked_during_lock_window() -> None:
    user_id = uuid4()
    locked_at = datetime.now(UTC) - timedelta(minutes=1)

    session = FakeSession([FakeResult(locked_at)])
    security = PersistentLoginSecurityStore(session)

    assert await security.is_locked(user_id) is True


@pytest.mark.asyncio
async def test_expired_lock_is_not_active() -> None:
    user_id = uuid4()
    locked_at = datetime.now(UTC) - timedelta(minutes=16)

    session = FakeSession([FakeResult(locked_at)])
    security = PersistentLoginSecurityStore(session)

    assert await security.is_locked(user_id) is False


@pytest.mark.asyncio
async def test_fifth_failed_login_persists_account_lock() -> None:
    user_id = uuid4()

    session = FakeSession(
        [
            FakeResult(),  # SELECT FOR UPDATE
            FakeResult(None),  # latest ACCOUNT_LOCKED
            FakeResult(None),  # latest LOGIN_SUCCEEDED
            FakeResult(5),  # failed-login count
        ]
    )

    security = PersistentLoginSecurityStore(session)

    locked = await security.record_failed_login(
        user_id,
        "203.0.113.10",
    )

    assert locked is True
    assert [record.action_type for record in session.added] == [
        LOGIN_FAILED_ACTION,
        ACCOUNT_LOCKED_ACTION,
    ]
    assert session.commit_count == 1


@pytest.mark.asyncio
async def test_failure_below_limit_does_not_lock() -> None:
    user_id = uuid4()

    session = FakeSession(
        [
            FakeResult(),
            FakeResult(None),
            FakeResult(None),
            FakeResult(4),
        ]
    )

    security = PersistentLoginSecurityStore(session)

    locked = await security.record_failed_login(
        user_id,
        "203.0.113.10",
    )

    assert locked is False
    assert [record.action_type for record in session.added] == [
        LOGIN_FAILED_ACTION,
    ]
    assert session.commit_count == 1


@pytest.mark.asyncio
async def test_successful_login_is_persisted() -> None:
    user_id = uuid4()

    session = FakeSession([FakeResult()])
    security = PersistentLoginSecurityStore(session)

    await security.record_successful_login(
        user_id,
        "203.0.113.10",
    )

    assert len(session.added) == 1
    assert session.added[0].action_type == LOGIN_SUCCEEDED_ACTION
    assert session.added[0].user_id == user_id
    assert session.commit_count == 1
