"""Cyber 1, Phase 4: consent in a live class, the Teams in-meeting panel's
socket included.

Terms consent is needed to be in the class. Engagement monitoring, camera
and microphone consent each govern what is kept about the student, and
declining any of them never blocks the class or lowers a score. A withdrawal
takes effect at once.
"""

from __future__ import annotations

import asyncio
from uuid import UUID

import pytest
from starlette.websockets import WebSocketDisconnect

from app.auth.store import LECTURER_ID, STUDENT_ID
from app.realtime.classroom import Classroom, classroom
from app.realtime.consent import ConsentRegistry, permitted_signal
from app.realtime.hub import Connection
from app.schemas.events import AttentionSignalPayload, PromptAckPayload, ServerEventType
from app.schemas.identity import ConsentType, Role

from .classroom_support import (
    FakeSocket,
    answer_to,
    deliver_next,
    join_as,
    make_room,
    make_row,
)
from .dev_credentials import STUDENT_PASSWORD
from .session_support import (
    add_course,
    add_question,
    create_session,
    enrol,
    sign_in_as,
    token_for,
)

TERMS = ConsentType.TERMS
MONITORING = ConsentType.ENGAGEMENT_MONITORING
CAMERA = ConsentType.CAMERA
MICROPHONE = ConsentType.MICROPHONE

SIGNAL = AttentionSignalPayload(
    gaze_on_screen_ratio=0.9, face_present=True, speaking=True, window_seconds=5.0
)


class _PromptLog:
    def __init__(self) -> None:
        self.outcomes: list = []

    async def record_prompt(self, outcome) -> None:  # noqa: ANN001
        self.outcomes.append(outcome)


async def _class_with(*students: set[ConsentType], window: float = 0.05, missed: int = 0):  # noqa: ANN202
    """A running class, as production has it: nobody is assumed to consent.
    One student per consent set, admitted with it."""
    room, events = make_room(window=window, missed=missed, consents=ConsentRegistry())
    row = make_row()
    room.activate(row.session_id)
    joined = []
    for granted in students:
        socket, user = await join_as(events, row.session_id, Role.STUDENT)
        room.admit_consents(user, granted, room.consents.version(user))
        joined.append((socket, user))
    return room, events, row, joined


async def _close(room: Classroom, row, *answering: UUID) -> None:  # noqa: ANN001
    question = await deliver_next(room, row)
    for student in answering:
        assert (
            await room.submit(
                row.session_id, student, Role.STUDENT, answer_to(question.question_id)
            )
        ).accepted
    await asyncio.sleep(0.15)


# -- what the registry assumes ---------------------------------------------------


def test_nobody_is_monitored_on_an_assumption() -> None:
    registry = ConsentRegistry()

    assert not registry.monitored(STUDENT_ID)
    assert permitted_signal(SIGNAL, registry.granted(STUDENT_ID)) is None


def test_a_read_a_withdrawal_overtook_cannot_undo_it() -> None:
    """The socket reads consent, then awaits the database before admitting
    the student. A withdrawal recorded meanwhile must win."""
    registry = ConsentRegistry()
    read_at = registry.version(STUDENT_ID)
    registry.set(STUDENT_ID, {TERMS})  # the withdrawal, while the socket waited

    held = registry.admit(STUDENT_ID, {TERMS, MONITORING}, read_at)

    assert held == {TERMS}
    assert not registry.monitored(STUDENT_ID)


def test_a_signal_keeps_only_what_consent_covers() -> None:
    assert permitted_signal(SIGNAL, frozenset({MONITORING, CAMERA, MICROPHONE})) == SIGNAL
    assert permitted_signal(SIGNAL, frozenset({MONITORING})).model_dump() == {
        "gaze_on_screen_ratio": None,
        "face_present": None,
        "speaking": None,
        "window_seconds": 5.0,
    }
    no_camera = permitted_signal(SIGNAL, frozenset({MONITORING, MICROPHONE}))
    assert (no_camera.gaze_on_screen_ratio, no_camera.face_present, no_camera.speaking) == (
        None,
        None,
        True,
    )


# -- declining monitoring never blocks the class ----------------------------------


@pytest.mark.usefixtures("fake_session_repository")
async def test_a_student_who_declined_monitoring_answers_but_is_not_scored_or_prompted() -> None:
    room, _, row, [(watched, monitored), (unwatched, declined)] = await _class_with(
        {TERMS, MONITORING}, {TERMS}, missed=1
    )

    # Neither answers the first question: both have let one pass.
    await _close(room, row)
    # The one who declined still answers the next, like anyone in the class.
    await _close(room, row, declined)

    assert [s.user_id for s in room.engagement(row.session_id)] == [monitored]
    assert watched.of(ServerEventType.PROMPT_ATTENTION)
    assert unwatched.of(ServerEventType.PROMPT_ATTENTION) == []
    assert await room.prompt_student(row.session_id, declined, "Still with us?") is None
    await room.shutdown()


@pytest.mark.usefixtures("fake_session_repository")
async def test_nothing_from_before_consent_ever_counts() -> None:
    """A student who declined is not watched meanwhile, so consenting later
    starts from nothing. One question shown since then is not yet a rate."""
    room, _, row, [(_, student)] = await _class_with({TERMS})
    await _close(room, row)  # shown, let pass, while not consenting

    room.admit_consents(student, {TERMS, MONITORING}, room.consents.version(student))
    await _close(room, row, student)

    [scored] = room.engagement(row.session_id)
    assert scored.engagement.signals_available == ["response_timing"]
    await room.shutdown()


@pytest.mark.usefixtures("fake_session_repository")
async def test_a_signal_from_a_student_who_declined_monitoring_is_not_kept() -> None:
    room, _, row, [(_, declined)] = await _class_with({TERMS})

    assert not await room.record_attention(row.session_id, declined, SIGNAL)
    await room.shutdown()


@pytest.mark.usefixtures("fake_session_repository")
async def test_declining_the_camera_never_lowers_a_score() -> None:
    """The camera-derived parts of a signal are dropped, not scored as zero,
    so the score rests on the same evidence as if nothing had been sent.
    Scored, this signal would pull the score down to near 0.5."""
    room, _, row, [(_, no_camera)] = await _class_with({TERMS, MONITORING})
    looking_away = AttentionSignalPayload(
        gaze_on_screen_ratio=0.0, face_present=False, window_seconds=5.0
    )
    assert await room.record_attention(row.session_id, no_camera, looking_away)

    await _close(room, row, no_camera)

    [scored] = room.engagement(row.session_id)
    assert scored.engagement.signals_available == ["response_timing"]
    assert scored.engagement.score > 0.9
    await room.shutdown()


# -- a withdrawal takes effect at once --------------------------------------------


@pytest.mark.usefixtures("fake_session_repository")
async def test_withdrawing_monitoring_mid_class_stops_it_at_once() -> None:
    room, _, row, [(_, student)] = await _class_with({TERMS, MONITORING}, window=0.05)
    log = _PromptLog()
    room.prompt_recorder = log
    await _close(room, row)
    prompt = await room.prompt_student(row.session_id, student, "Still with us?")
    assert prompt is not None and room.engagement(row.session_id)

    await room.withdraw_consent(student, MONITORING)

    assert room.engagement(row.session_id) == []
    # The prompt on screen is taken down and nothing about it is recorded.
    ack = PromptAckPayload(prompt_id=prompt.prompt_id)
    assert not await room.acknowledge_prompt(row.session_id, student, ack)
    assert await room.prompt_student(row.session_id, student, "Still with us?") is None
    await _close(room, row)
    assert room.engagement(row.session_id) == []
    assert log.outcomes == []
    await room.shutdown()


@pytest.mark.usefixtures("fake_session_repository")
async def test_a_score_is_not_reported_once_monitoring_consent_is_gone() -> None:
    """Consent can change without passing through this process's consent
    route, and is then read afresh when the student next joins. A score kept
    from before is no longer reported."""
    room, _, row, [(_, student)] = await _class_with({TERMS, MONITORING})
    await _close(room, row, student)
    assert room.engagement(row.session_id)

    room.admit_consents(student, {TERMS}, room.consents.version(student))

    assert room.engagement(row.session_id) == []
    await room.shutdown()


@pytest.mark.usefixtures("fake_session_repository")
async def test_withdrawing_the_camera_drops_what_it_saw_at_once() -> None:
    room, _, row, [(_, student)] = await _class_with({TERMS, MONITORING, CAMERA, MICROPHONE})
    assert await room.record_attention(row.session_id, student, SIGNAL)

    await room.withdraw_consent(student, CAMERA)
    await _close(room, row, student)

    [scored] = room.engagement(row.session_id)
    assert "gaze" not in scored.engagement.signals_available
    assert "face_presence" not in scored.engagement.signals_available
    await room.shutdown()


@pytest.mark.usefixtures("fake_session_repository")
async def test_withdrawing_terms_closes_only_that_students_class_sockets() -> None:
    class Closing(FakeSocket):
        def __init__(self) -> None:
            super().__init__()
            self.closed: tuple[int, str] | None = None

        async def close(self, code: int, reason: str) -> None:
            self.closed = (code, reason)

    room, events, row, [(_, classmate)] = await _class_with({TERMS})
    in_class, own_channel = Closing(), Closing()
    await events.join(Connection(in_class, STUDENT_ID, row.session_id, Role.STUDENT))  # type: ignore[arg-type]
    await events.join(Connection(own_channel, STUDENT_ID, None, Role.STUDENT))  # type: ignore[arg-type]

    await room.withdraw_consent(STUDENT_ID, TERMS)

    assert in_class.closed == (4003, "consent withdrawn")
    assert own_channel.closed is None
    assert events.student_ids(row.session_id) == {classmate}
    await room.shutdown()


# -- through the socket and the consent route --------------------------------------


def _refused(client, token: str, session_id: str) -> WebSocketDisconnect:  # noqa: ANN001
    with pytest.raises(WebSocketDisconnect) as refused:  # noqa: PT012
        with client.websocket_connect("/ws/session") as ws:
            ws.send_json({"type": "auth", "data": {"token": token, "session_id": session_id}})
            ws.receive_json()
            ws.receive_json()
    return refused.value


async def test_a_student_without_terms_consent_cannot_join_their_class(db, app) -> None:
    client, factory, created = db
    course = await add_course(factory, created)
    await enrol(factory, course)
    sign_in_as(app, LECTURER_ID, Role.LECTURER)
    session = create_session(client, course)
    token = token_for(client, "student@clip.example.com", STUDENT_PASSWORD, consents=())

    refused = _refused(client, token, session["id"])

    assert (refused.code, refused.reason) == (4003, "consent required")


async def test_withdrawing_terms_takes_a_student_out_of_the_class(db, app) -> None:
    client, factory, created = db
    course = await add_course(factory, created)
    await enrol(factory, course)
    sign_in_as(app, LECTURER_ID, Role.LECTURER)
    session = create_session(client, course)
    token = token_for(client, "student@clip.example.com", STUDENT_PASSWORD)

    with pytest.raises(WebSocketDisconnect) as closed:  # noqa: PT012
        with client.websocket_connect("/ws/session") as ws:
            ws.send_json({"type": "auth", "data": {"token": token, "session_id": session["id"]}})
            assert ws.receive_json()["type"] == "ready"
            assert ws.receive_json()["type"] == "session.state"
            sign_in_as(app, STUDENT_ID, Role.STUDENT)
            withdrawn = client.post(
                "/api/v1/auth/consent", json={"consent_type": "terms", "granted": False}
            )
            assert withdrawn.status_code == 201
            # The close was sent before the route returned, so it arrives
            # ahead of the pong. Still in the class, the pong comes instead,
            # and the test fails rather than waiting for ever.
            ws.send_json({"type": "ping"})
            reply = ws.receive_json()
            pytest.fail(f"still in the class: {reply}")

    assert closed.value.code == 4003


async def test_a_signal_from_a_student_who_declined_monitoring_is_refused_with_a_reason(
    db, app
) -> None:
    client, factory, created = db
    course = await add_course(factory, created)
    await enrol(factory, course)
    await add_question(db, course, LECTURER_ID)
    sign_in_as(app, LECTURER_ID, Role.LECTURER)
    session = create_session(client, course)
    assert client.post(f"/api/v1/sessions/{session['id']}/start").status_code == 200
    token = token_for(client, "student@clip.example.com", STUDENT_PASSWORD)

    try:
        with client.websocket_connect("/ws/session") as ws:
            ws.send_json({"type": "auth", "data": {"token": token, "session_id": session["id"]}})
            assert ws.receive_json()["type"] == "ready"
            assert ws.receive_json()["type"] == "session.state"
            ws.send_json({"type": "signal.attention", "data": SIGNAL.model_dump(mode="json")})
            # A ping behind it, so a signal kept in silence shows as a pong
            # rather than a wait for ever.
            ws.send_json({"type": "ping"})
            refused = ws.receive_json()
    finally:
        client.post(f"/api/v1/sessions/{session['id']}/end")

    assert (refused["type"], refused["data"]["code"]) == ("error", "CONSENT_REQUIRED")


async def test_the_consent_route_applies_a_withdrawal_now_and_a_grant_at_the_next_join(
    db, app
) -> None:
    """A grant waits to be read back from the store at the next join, so no
    class acts on one the request might not commit."""
    client, _, _ = db
    sign_in_as(app, STUDENT_ID, Role.STUDENT)
    classroom.admit_consents(
        STUDENT_ID, {TERMS, MONITORING}, classroom.consents.version(STUDENT_ID)
    )

    client.post(
        "/api/v1/auth/consent", json={"consent_type": "engagement_monitoring", "granted": False}
    )
    assert not classroom.consents.monitored(STUDENT_ID)

    client.post(
        "/api/v1/auth/consent", json={"consent_type": "engagement_monitoring", "granted": True}
    )
    assert not classroom.consents.monitored(STUDENT_ID)
