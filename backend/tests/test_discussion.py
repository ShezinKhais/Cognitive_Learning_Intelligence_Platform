from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from sqlalchemy import delete

from app.auth.store import LECTURER_ID, STUDENT_ID
from app.models.discussion_note import DiscussionNote
from app.models.session import Session
from app.schemas.chat import ChatRequest
from app.schemas.identity import Role
from app.services import tutor_chat
from app.services.tutor_chat import DiscussionSource, discussion_chunks

from .session_support import add_course, add_lecturer, create_session, enrol, sign_in_as


def test_discussion_retrieval_uses_topic_matches_or_recent_notes_for_a_recap():
    now = datetime.now(UTC)
    note = DiscussionSource(uuid4(), now, "Normalization reduces redundant database values.")
    old = DiscussionSource(uuid4(), now - timedelta(minutes=20), "Networks carry packets.")
    assert discussion_chunks((old, note), "Explain normalization", 6)[0].chunk_id == note.note_id
    assert discussion_chunks((old, note), "Explain photosynthesis", 6) == []
    assert discussion_chunks((old, note), "What did I miss?", 1)[0].chunk_id == note.note_id


def test_discussion_time_window_cannot_be_reversed():
    from pydantic import ValidationError

    now = datetime.now(UTC)
    with pytest.raises(ValidationError):
        ChatRequest(
            request_id="test",
            question="Recap",
            source="discussion",
            discussion_since=now,
            discussion_until=now - timedelta(minutes=1),
        )


async def test_notes_publish_live_persist_after_end_and_respect_course_access(db, app, monkeypatch):
    client, factory, created = db
    course = await add_course(factory, created)
    sign_in_as(app, LECTURER_ID, Role.LECTURER)
    session = create_session(client, course)
    session_id = session["id"]
    from uuid import UUID

    async with factory() as sql:
        row = await sql.get(Session, UUID(session_id))
        row.status = "active"
        await sql.commit()

    path = f"/api/v1/sessions/{session_id}/discussion"
    note_id = str(uuid4())
    payload = {
        "occurred_at": datetime.now(UTC).isoformat(),
        "text": "Normalization reduces redundant database values.",
        "shareable_confirmed": False,
    }
    assert client.put(f"{path}/{note_id}", json=payload).status_code == 422
    payload["shareable_confirmed"] = True
    first = client.put(f"{path}/{note_id}", json=payload)
    assert first.status_code == 200, first.text
    assert client.put(f"{path}/{note_id}", json=payload).status_code == 200
    assert len(client.get(path).json()["notes"]) == 1

    sign_in_as(app, STUDENT_ID, Role.STUDENT)
    assert client.get(path).status_code == 404
    await enrol(factory, course)
    assert client.get(path).status_code == 200
    assert client.put(f"{path}/{note_id}", json=payload).status_code == 403

    other = await add_lecturer(factory, created)
    sign_in_as(app, other, Role.LECTURER)
    assert client.get(path).status_code == 404
    assert client.delete(f"{path}/{note_id}").status_code == 404

    async with factory() as sql:
        row = await sql.get(Session, UUID(session_id))
        row.status = "ended"
        row.ended_at = datetime.now(UTC)
        await sql.commit()
    sign_in_as(app, STUDENT_ID, Role.STUDENT)
    result = client.get(path)
    assert result.json()["notes"][0]["text"] == payload["text"]
    assert result.headers["cache-control"] == "no-store"

    async def generated(self, prompt):
        yield "Normalization reduces redundant values. Which benefit follows? [1]"

    monkeypatch.setattr(tutor_chat.TutorExchange, "_generate", generated)
    limiter = tutor_chat.ChatLimiter(30, 60)
    monkeypatch.setattr(tutor_chat, "get_chat_limiter", lambda: limiter)
    response = client.post(
        f"/api/v1/sessions/{session_id}/chat",
        json={
            "request_id": "discussion-test",
            "question": "Explain normalization",
            "source": "discussion",
        },
    )
    assert response.status_code == 200, response.text
    import json

    events = [json.loads(line) for line in response.text.splitlines()]
    assert events[-1]["type"] == "completed", events
    citation = next(e["citation"] for e in events if e["type"] == "citation")
    assert citation["id"] == note_id
    assert "Discussion note" in citation["material_title"]

    response = client.post(
        f"/api/v1/sessions/{session_id}/chat",
        json={
            "request_id": "discussion-empty",
            "question": "Explain normalization",
            "source": "discussion",
            "discussion_until": (datetime.now(UTC) - timedelta(days=1)).isoformat(),
        },
    )
    assert "empty_retrieval" in response.text

    sign_in_as(app, LECTURER_ID, Role.LECTURER)
    assert client.delete(f"{path}/{note_id}").status_code == 200
    assert client.get(path).json()["notes"] == []
    assert client.put(f"{path}/{note_id}", json=payload).status_code == 200
    async with factory() as sql:
        await sql.execute(delete(Session).where(Session.session_id == UUID(session_id)))
        await sql.commit()
        assert await sql.get(DiscussionNote, UUID(note_id)) is None
