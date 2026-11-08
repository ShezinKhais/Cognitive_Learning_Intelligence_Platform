import asyncio
import io
import wave
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest

from app.auth.store import LECTURER_ID, STUDENT_ID
from app.core.errors import ConflictError, ValidationError
from app.models.session import Session
from app.schemas.identity import Role
from app.services import live_transcription as live
from app.services import local_speech, tutor_chat
from app.services.tutor_chat import DiscussionSource, discussion_chunks

from .session_support import add_course, create_session, enrol, sign_in_as


def wav(seconds=10, channels=1, rate=16000):
    output = io.BytesIO()
    with wave.open(output, "wb") as writer:
        writer.setnchannels(channels)
        writer.setsampwidth(2)
        writer.setframerate(rate)
        writer.writeframes(b"\0\0" * (seconds * rate * channels))
    return output.getvalue()


def test_audio_boundary_rejects_wrong_format_oversize_and_incomplete_data():
    assert local_speech.validate_wav(wav()) == 10
    for invalid in (b"not audio", wav(channels=2), wav(rate=8000), wav(seconds=13), wav()[:-2]):
        with pytest.raises(ValidationError):
            local_speech.validate_wav(invalid)


def test_capture_leases_are_exclusive_bounded_and_expire(monkeypatch):
    clock = [0.0]
    monkeypatch.setattr(live.time, "monotonic", lambda: clock[0])
    store = live.Captures()
    session, user = uuid4(), uuid4()
    item = store.start(session, user)
    with pytest.raises(ConflictError):
        store.start(session, user)
    with pytest.raises(ConflictError):
        store.require(session, item.id, uuid4())
    clock[0] = live.LEASE_SECONDS + 1
    assert store.active(session) is None


def test_recap_samples_the_window_and_topic_questions_find_live_speech():
    now = datetime.now(UTC)
    sources = tuple(
        DiscussionSource(
            uuid4(),
            now + timedelta(seconds=i * 10),
            f"Normalization reduces duplicates. Segment {i}.",
            "live_transcript",
        )
        for i in range(60)
    )
    chunks = discussion_chunks(sources, "What did I miss?", 5)
    assert chunks[0].chunk_id == sources[0].note_id
    assert chunks[-1].chunk_id == sources[-1].note_id
    assert "live_transcript" in chunks[0].chunk_text
    assert (
        discussion_chunks(sources, "What did the lecturer just say?", 1)[0].chunk_id
        == sources[-1].note_id
    )
    assert discussion_chunks(sources, "Explain normalization", 5)
    assert not discussion_chunks(sources, "Explain photosynthesis", 5)


async def test_native_inference_cancellation_keeps_the_capacity_slot(monkeypatch):
    import threading

    engine = local_speech.LocalSpeech()
    entered, release = asyncio.Event(), threading.Event()
    loop = asyncio.get_running_loop()

    def recognize(*_):
        loop.call_soon_threadsafe(entered.set)
        release.wait(5)
        return "Teaching text"

    monkeypatch.setattr(local_speech, "configured", lambda _: True)
    monkeypatch.setattr(local_speech, "_recognize", recognize)
    first = asyncio.create_task(engine.transcribe(b"", SimpleNamespace()))
    await entered.wait()
    first.cancel()
    with pytest.raises(asyncio.CancelledError):
        await first
    with pytest.raises(local_speech.SpeechUnavailable):
        await engine.transcribe(b"", SimpleNamespace())
    release.set()
    await engine.running


async def test_live_audio_becomes_chat_source_with_review_and_removal_controls(
    db, app, monkeypatch
):
    client, factory, created = db
    course = await add_course(factory, created)
    await enrol(factory, course)
    sign_in_as(app, LECTURER_ID, Role.LECTURER)
    sid = UUID(create_session(client, course)["id"])
    async with factory() as sql:
        row = await sql.get(Session, sid)
        row.status = "active"
        row.start_time = datetime.now(UTC) - timedelta(minutes=10)
        await sql.commit()
    monkeypatch.setattr(live, "captures", live.Captures())
    monkeypatch.setattr(local_speech, "configured", lambda _: True)
    from unittest.mock import AsyncMock

    recognize = AsyncMock(return_value="Normalization reduces redundant database values.")
    monkeypatch.setattr(local_speech.speech, "transcribe", recognize)
    base = f"/api/v1/sessions/{sid}"
    assert (
        client.post(
            base + "/live-transcription/start", json={"automatic_sharing_confirmed": False}
        ).status_code
        == 422
    )
    sign_in_as(app, STUDENT_ID, Role.STUDENT)
    assert (
        client.post(
            base + "/live-transcription/start", json={"automatic_sharing_confirmed": True}
        ).status_code
        == 403
    )
    sign_in_as(app, uuid4(), Role.LECTURER)
    assert client.get(base + "/live-transcription").status_code == 404
    sign_in_as(app, LECTURER_ID, Role.LECTURER)
    started = client.post(
        base + "/live-transcription/start", json={"automatic_sharing_confirmed": True}
    )
    assert started.status_code == 200, started.text
    capture_id = started.json()["capture_id"]
    beginning = (datetime.now(UTC) - timedelta(seconds=12)).isoformat()
    path = base + f"/live-transcription/{capture_id}/chunks/0"
    response = client.post(
        path, params={"started_at": beginning}, content=wav(), headers={"Content-Type": "audio/wav"}
    )
    assert response.status_code == 200, response.text
    note = response.json()["note"]
    assert note["origin"] == "live_transcript"
    repeated = client.post(path, params={"started_at": beginning}, content=wav())
    assert repeated.status_code == 200
    assert recognize.await_count == 1
    sign_in_as(app, STUDENT_ID, Role.STUDENT)
    discussion = client.get(base + "/discussion")
    assert discussion.json()["live_transcription_active"]
    assert discussion.json()["notes"][0]["text"].startswith("Normalization")

    async def generate(self, prompt):
        yield "Normalization reduces redundant values. Which benefit follows? [1]"

    monkeypatch.setattr(tutor_chat.TutorExchange, "_generate", generate)
    monkeypatch.setattr(tutor_chat, "get_chat_limiter", lambda: tutor_chat.ChatLimiter(30, 60))
    answer = client.post(
        base + "/chat",
        json={
            "request_id": "live-test",
            "source": "discussion",
            "question": "Explain normalization",
        },
    )
    assert "Automatic live transcript (unreviewed)" in answer.text, answer.text
    assert '"type":"completed"' in answer.text

    sign_in_as(app, LECTURER_ID, Role.LECTURER)
    correction = client.put(
        base + f"/discussion/{note['note_id']}",
        json={
            "occurred_at": beginning,
            "text": "Normalization reduces duplicated database values.",
            "shareable_confirmed": True,
        },
    )
    assert correction.status_code == 200
    assert correction.json()["origin"] == "lecturer"
    assert client.delete(base + f"/discussion/{note['note_id']}").status_code == 200
    assert client.post(path, params={"started_at": beginning}, content=wav()).json()["note"] is None
    assert recognize.await_count == 1
    assert client.post(base + f"/live-transcription/{capture_id}/stop").status_code == 200
    assert client.post(path, params={"started_at": beginning}, content=wav()).status_code == 409
    assert client.get(base + "/discussion").json()["notes"] == []


async def test_stopping_capture_during_inference_prevents_publication(db, app, monkeypatch):
    from unittest.mock import AsyncMock

    client, factory, created = db
    course = await add_course(factory, created)
    sign_in_as(app, LECTURER_ID, Role.LECTURER)
    sid = UUID(create_session(client, course)["id"])
    async with factory() as sql:
        row = await sql.get(Session, sid)
        row.status = "active"
        await sql.commit()
    monkeypatch.setattr(live, "captures", live.Captures())
    monkeypatch.setattr(local_speech, "configured", lambda _: True)
    base = f"/api/v1/sessions/{sid}/live-transcription"
    started = client.post(base + "/start", json={"automatic_sharing_confirmed": True}).json()
    cap = UUID(started["capture_id"])

    async def transcribe(*_):
        live.captures.stop(sid, cap)
        return "Private words after stopping must not be shared."

    monkeypatch.setattr(local_speech.speech, "transcribe", AsyncMock(side_effect=transcribe))
    result = client.post(
        base + f"/{cap}/chunks/0",
        params={"started_at": (datetime.now(UTC) - timedelta(seconds=12)).isoformat()},
        content=wav(),
    )
    assert result.status_code == 409, result.text
    assert client.get(f"/api/v1/sessions/{sid}/discussion").json()["notes"] == []
