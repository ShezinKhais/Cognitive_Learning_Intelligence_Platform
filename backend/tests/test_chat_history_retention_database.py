"""Verify chatbot retention batches against development PostgreSQL."""

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from sqlalchemy import func, select

from app.models.student_chat_exchange import StudentChatExchange
from app.models.user import User
from app.services import retention_tasks


@pytest.mark.asyncio
async def test_postgres_retention_removes_only_expired_exchanges(db, monkeypatch):
    _client, factory, created = db

    # A global retention task must never run over existing
    # student history merely to exercise an integration test.
    async with factory() as session:
        existing = await session.scalar(select(func.count()).select_from(StudentChatExchange))

    if existing != 0:
        pytest.skip(
            "Retention integration requires an empty development "
            "chat-history table to avoid deleting existing records."
        )

    now = datetime.now(UTC)
    cutoff = now - timedelta(days=30)
    student_id = uuid4()

    async with factory() as session:
        session.add(
            User(
                user_id=student_id,
                name="Retention Test Student",
                email=f"{student_id.hex}@chat-history.test",
                role="student",
            )
        )
        await session.commit()

    created["user"].append(student_id)

    samples = [
        ("Oldest", now - timedelta(days=60)),
        ("Older", now - timedelta(days=45)),
        ("Recent", now - timedelta(days=2)),
    ]

    async with factory() as session:
        for question, timestamp in samples:
            session.add(
                StudentChatExchange(
                    student_id=student_id,
                    session_id=None,
                    request_id=uuid4().hex,
                    question=question,
                    answer=f"Answer for {question}",
                    source="materials",
                    phase="completed",
                    citations=[],
                    follow_ups=[],
                    general=False,
                    explanation=None,
                    created_at=timestamp,
                )
            )
        await session.commit()

    audit = AsyncMock()
    monkeypatch.setattr(retention_tasks, "record_event", audit)

    job = retention_tasks.ChatHistoryPurge(sessions=lambda: factory)

    assert await job.purge(cutoff, 1) == 1

    async with factory() as session:
        remaining = await session.scalars(
            select(StudentChatExchange.question)
            .where(StudentChatExchange.student_id == student_id)
            .order_by(StudentChatExchange.created_at)
        )
        assert list(remaining) == ["Older", "Recent"]

    assert await job.purge(cutoff, 1) == 1

    async with factory() as session:
        remaining = await session.scalars(
            select(StudentChatExchange.question).where(StudentChatExchange.student_id == student_id)
        )
        assert list(remaining) == ["Recent"]

    assert await job.purge(cutoff, 1) == 0
    assert audit.await_count == 2

    for call in audit.await_args_list:
        details = call.kwargs["details"]
        assert details["task"] == "student-chat-history"
        assert details["chatbot_exchanges"] == 1
        assert "question" not in details
        assert "answer" not in details
