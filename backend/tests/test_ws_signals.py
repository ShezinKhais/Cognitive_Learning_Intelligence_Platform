"""Attention signals and breakout rooms through a real WebSocket: what the
socket accepts, what it throttles, and how the rooms then stand.

Owner: General CS, Phase 6.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from uuid import UUID

from app.auth.store import LECTURER_ID
from app.realtime.classroom import classroom
from app.schemas.identity import ConsentType, Role

from .dev_credentials import LECTURER_PASSWORD, STUDENT_PASSWORD
from .session_support import (
    add_course,
    add_question,
    create_session,
    enrol,
    sign_in_as,
    token_for,
)

STUDENT_EMAIL = "student@clip.example.com"
LECTURER_EMAIL = "lecturer@clip.example.com"
EVERYTHING = (
    ConsentType.TERMS,
    ConsentType.ENGAGEMENT_MONITORING,
    ConsentType.CAMERA,
    ConsentType.MICROPHONE,
)
SIGNAL = {"gaze_on_screen_ratio": 0.9, "face_present": True, "speaking": False, "window_seconds": 5}


async def _running_session(db, app):  # noqa: ANN001, ANN202
    """A started session of a course the development student is on, run by
    the development lecturer, who is signed in for the REST calls."""
    client, factory, created = db
    course = await add_course(factory, created)
    await enrol(factory, course)
    await add_question(db, course, LECTURER_ID)
    sign_in_as(app, LECTURER_ID, Role.LECTURER)
    session = create_session(client, course)
    assert client.post(f"/api/v1/sessions/{session['id']}/start").status_code == 200
    return client, session


@contextmanager
def _joined(client, token: str, session_id: str | None) -> Iterator:  # noqa: ANN001
    """A socket past its handshake: ready, then the session's state."""
    with client.websocket_connect("/ws/session") as ws:
        data = {"token": token, "session_id": session_id}
        ws.send_json({"type": "auth", "data": data})
        assert ws.receive_json()["type"] == "ready"
        if session_id is not None:
            assert ws.receive_json()["type"] == "session.state"
        yield ws


def _until_pong(ws) -> list[dict]:  # noqa: ANN001
    """Everything the server sent in answer to the frames before a ping, and
    then the pong that closes the list. Waits for ever if it never comes,
    like the other socket tests."""
    ws.send_json({"type": "ping"})
    received = []
    while (message := ws.receive_json())["type"] != "pong":
        received.append(message)
    return received


def _rooms(session: dict) -> list[dict]:
    """How the session's rooms stand now, as a lecturer's panel is told."""
    return [room.model_dump(mode="json") for room in classroom.rooms(UUID(session["id"]))]


def _codes(messages: list[dict]) -> list[tuple[str, str]]:
    return [(m["type"], m["data"].get("code", "")) for m in messages]


async def test_a_student_confirming_a_room_is_put_in_it(db, app) -> None:
    client, session = await _running_session(db, app)
    token = token_for(client, STUDENT_EMAIL, STUDENT_PASSWORD, EVERYTHING)

    try:
        with _joined(client, token, session["id"]) as ws:
            ws.send_json({"type": "room.confirm", "data": {"room_label": "Room 1"}})
            # Nothing is said back to the student, so the pong is all there is.
            assert _until_pong(ws) == []
            listed = _rooms(session)
    finally:
        client.post(f"/api/v1/sessions/{session['id']}/end")

    assert listed == [
        {
            "room_label": "Room 1",
            "status": "unknown",
            "members": 1,
            "speaking_now": 0,
            "silence_seconds": 0,
            "task_interactions": 0,
        }
    ]


async def test_a_room_label_with_nothing_to_show_is_refused_with_its_code(db, app) -> None:
    client, session = await _running_session(db, app)
    token = token_for(client, STUDENT_EMAIL, STUDENT_PASSWORD)

    try:
        with _joined(client, token, session["id"]) as ws:
            ws.send_json({"type": "room.confirm", "data": {"room_label": "\x07"}})
            refused = _until_pong(ws)
            listed = _rooms(session)
    finally:
        client.post(f"/api/v1/sessions/{session['id']}/end")

    assert _codes(refused) == [("error", "ROOM_LABEL_INVALID")]
    assert listed == []


async def test_a_room_confirmation_with_no_label_is_a_malformed_event(db, app) -> None:
    client, session = await _running_session(db, app)
    token = token_for(client, STUDENT_EMAIL, STUDENT_PASSWORD)

    try:
        with _joined(client, token, session["id"]) as ws:
            ws.send_json({"type": "room.confirm", "data": {"room_label": ""}})
            refused = _until_pong(ws)
    finally:
        client.post(f"/api/v1/sessions/{session['id']}/end")

    assert _codes(refused) == [("error", "MALFORMED_EVENT")]


async def test_room_confirm_without_a_session_is_not_in_session(db, app) -> None:
    client, _, _ = db
    token = token_for(client, STUDENT_EMAIL, STUDENT_PASSWORD)

    with _joined(client, token, None) as ws:
        ws.send_json({"type": "room.confirm", "data": {"room_label": "Room 1"}})
        refused = _until_pong(ws)

    assert _codes(refused) == [("error", "NOT_IN_SESSION")]


async def test_room_confirm_from_a_lecturer_socket_is_not_in_session(db, app) -> None:
    client, session = await _running_session(db, app)
    token = token_for(client, LECTURER_EMAIL, LECTURER_PASSWORD)

    try:
        with _joined(client, token, session["id"]) as ws:
            ws.send_json({"type": "room.confirm", "data": {"room_label": "Room 1"}})
            refused = _until_pong(ws)
            listed = _rooms(session)
    finally:
        client.post(f"/api/v1/sessions/{session['id']}/end")

    assert _codes(refused) == [("error", "NOT_IN_SESSION")]
    assert listed == []


async def test_a_burst_of_signals_past_the_allowance_gets_one_error_and_the_socket_stays_usable(
    db, app
) -> None:
    client, session = await _running_session(db, app)
    token = token_for(client, STUDENT_EMAIL, STUDENT_PASSWORD, EVERYTHING)

    try:
        with _joined(client, token, session["id"]) as ws:
            for _ in range(12):
                ws.send_json({"type": "signal.attention", "data": SIGNAL})
            # Five fit the burst. The other seven are dropped, and say so once.
            throttled = _until_pong(ws)
            usable = _until_pong(ws)
    finally:
        client.post(f"/api/v1/sessions/{session['id']}/end")

    assert _codes(throttled) == [("error", "RATE_LIMITED")]
    assert "signal.attention" in throttled[0]["data"]["detail"]
    assert usable == []


async def test_signals_inside_the_allowance_get_no_error(db, app) -> None:
    client, session = await _running_session(db, app)
    token = token_for(client, STUDENT_EMAIL, STUDENT_PASSWORD, EVERYTHING)

    try:
        with _joined(client, token, session["id"]) as ws:
            for _ in range(5):
                ws.send_json({"type": "signal.attention", "data": SIGNAL})
            answered = _until_pong(ws)
    finally:
        client.post(f"/api/v1/sessions/{session['id']}/end")

    assert answered == []


async def test_room_confirm_spam_is_rate_limited(db, app) -> None:
    client, session = await _running_session(db, app)
    token = token_for(client, STUDENT_EMAIL, STUDENT_PASSWORD)

    try:
        with _joined(client, token, session["id"]) as ws:
            for number in range(8):
                ws.send_json({"type": "room.confirm", "data": {"room_label": f"Room {number}"}})
            throttled = _until_pong(ws)
            listed = _rooms(session)
    finally:
        client.post(f"/api/v1/sessions/{session['id']}/end")

    assert _codes(throttled) == [("error", "RATE_LIMITED")]
    assert "room.confirm" in throttled[0]["data"]["detail"]
    # Three confirmations fit the burst; the student ended up in the third room.
    assert [(r["room_label"], r["members"]) for r in listed] == [("Room 2", 1)]
