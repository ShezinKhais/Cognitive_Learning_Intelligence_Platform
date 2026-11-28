"""Scheduled retention of student-private chatbot history."""

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from app.services import retention_tasks


class FakeSession:
    def __init__(self, ids):
        self.ids = ids
        self.queries = []
        self.execute = AsyncMock()
        self.commit = AsyncMock()

    async def scalars(self, statement):
        self.queries.append(statement)
        return self.ids


class FakeContext:
    def __init__(self, session):
        self.session = session

    async def __aenter__(self):
        return self.session

    async def __aexit__(self, *_args):
        return False


@pytest.mark.asyncio
async def test_expired_exchanges_are_deleted_in_batches(monkeypatch):
    ids = [uuid4(), uuid4()]
    db = FakeSession(ids)
    audit = AsyncMock()
    monkeypatch.setattr(retention_tasks, "record_event", audit)

    job = retention_tasks.ChatHistoryPurge(sessions=lambda: lambda: FakeContext(db))
    cutoff = datetime.now(UTC) - timedelta(days=30)
    count = await job.purge(cutoff, 2)

    assert count == 2
    assert db.commit.await_count == 1
    assert db.execute.await_count == 1
    assert db.queries

    listing = db.queries[0]
    assert "student_chat_exchange" in str(listing)
    assert "created_at" in str(listing)
    assert listing._limit_clause.value == 2

    deleting = db.execute.await_args.args[0]
    values = list(deleting.compile().params.values())
    assert any(isinstance(value, (list, tuple, set)) and set(value) == set(ids) for value in values)
    assert cutoff in values

    audit.assert_awaited_once()
    details = audit.await_args.kwargs["details"]
    assert details["chatbot_exchanges"] == 2
    assert "question" not in details
    assert "answer" not in details


@pytest.mark.asyncio
async def test_empty_history_does_not_write_or_audit(monkeypatch):
    db = FakeSession([])
    audit = AsyncMock()
    monkeypatch.setattr(retention_tasks, "record_event", audit)

    job = retention_tasks.ChatHistoryPurge(sessions=lambda: lambda: FakeContext(db))
    cutoff = datetime.now(UTC) - timedelta(days=30)

    assert await job.purge(cutoff, 20) == 0
    db.execute.assert_not_awaited()
    db.commit.assert_not_awaited()
    audit.assert_not_awaited()


def test_chat_history_has_independent_retention_task():
    assert retention_tasks.ChatHistoryPurge.name == "student-chat-history"
    assert retention_tasks.SessionDataPurge.name != (retention_tasks.ChatHistoryPurge.name)
