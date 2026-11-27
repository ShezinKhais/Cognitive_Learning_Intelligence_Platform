"""Only completed student chatbot streams are persisted."""

import json
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from app.services import chat_history_persistence


def _chunk(kind: str, **fields) -> bytes:
    return (json.dumps({"type": kind, **fields}) + "\n").encode()


async def _run(monkeypatch, events):
    saved = AsyncMock()
    monkeypatch.setattr(
        chat_history_persistence,
        "save_completed_exchange",
        saved,
    )

    async def stream():
        for event in events:
            yield event

    student = uuid4()
    session = uuid4()

    output = [
        chunk
        async for chunk in chat_history_persistence.save_completed_stream(
            stream(),
            student_id=student,
            session_id=session,
            request_id="request-123",
            question="Explain recursion",
            source="materials",
        )
    ]
    return output, saved, student, session


@pytest.mark.asyncio
async def test_completed_stream_is_saved_once(monkeypatch):
    events = [
        _chunk("accepted", request_id="request-123"),
        _chunk("delta", text="A base "),
        _chunk("delta", text="case matters."),
        _chunk("completed"),
    ]
    output, saved, student, session = await _run(monkeypatch, events)

    assert output == events
    saved.assert_awaited_once()
    saved_kwargs = saved.await_args.kwargs
    assert saved_kwargs["student_id"] == student
    assert saved_kwargs["session_id"] == session
    assert saved_kwargs["question"] == "Explain recursion"
    assert saved_kwargs["answer"] == "A base case matters."


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "ending",
    ["cancelled", "error", "unsupported", "empty_retrieval"],
)
async def test_noncompleted_stream_is_not_saved(monkeypatch, ending):
    events = [
        _chunk("accepted"),
        _chunk("delta", text="Partial answer"),
        _chunk(ending),
    ]
    output, saved, _, _ = await _run(monkeypatch, events)

    assert output == events
    saved.assert_not_awaited()


@pytest.mark.asyncio
async def test_incomplete_stream_is_not_saved(monkeypatch):
    _, saved, _, _ = await _run(monkeypatch, [_chunk("accepted"), _chunk("delta", text="Partial")])
    saved.assert_not_awaited()


@pytest.mark.asyncio
async def test_citations_followups_and_general_flag_are_saved(monkeypatch):
    events = [
        _chunk("delta", text="Try a base case.", grounded=False),
        _chunk("citation", citation={"id": "source-1", "number": 1}),
        _chunk("follow_up", prompt="What stops recursion?"),
        _chunk("completed"),
    ]
    _, saved, _, _ = await _run(monkeypatch, events)

    kwargs = saved.await_args.kwargs
    assert kwargs["general"] is True
    assert kwargs["citations"] == [{"id": "source-1", "number": 1}]
    assert kwargs["follow_ups"] == ["What stops recursion?"]


@pytest.mark.asyncio
async def test_database_failure_does_not_interrupt_completed_stream(monkeypatch):
    async def fail(**_kwargs):
        raise RuntimeError("Database unavailable")

    monkeypatch.setattr(chat_history_persistence, "save_completed_exchange", fail)

    events = [_chunk("delta", text="Answer"), _chunk("completed")]

    async def stream():
        for event in events:
            yield event

    result = [
        chunk
        async for chunk in chat_history_persistence.save_completed_stream(
            stream(),
            student_id=uuid4(),
            session_id=uuid4(),
            request_id="request-123",
            question="Question",
            source="materials",
        )
    ]

    assert result[:-1] == events[:-1]
    assert json.loads(result[-1]) == {"type": "completed", "history_saved": False}
