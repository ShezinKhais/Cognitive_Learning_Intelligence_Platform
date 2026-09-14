"""User channels on the hub.

Owner: General CS, Phase 2.

Separate from test_ws.py, which covers the socket handshake and the client
protocol. These exercise the hub object directly: who an event can be addressed
to, and in what order it arrives.
"""

from __future__ import annotations

import asyncio
import time
from uuid import uuid4

import pytest

from app.realtime import hub as hub_module
from app.realtime.hub import (
    MAX_TRACKED_SESSIONS,
    Connection,
    SessionHub,
)
from app.schemas.events import ServerEventType


class _FakeSocket:
    def __init__(self, fail: bool = False) -> None:
        self.sent: list[dict] = []
        self.fail = fail

    async def send_json(self, payload: dict) -> None:
        if self.fail:
            raise ConnectionResetError("client gone")

        self.sent.append(payload)


async def test_a_connection_without_a_session_can_still_be_reached() -> None:
    """Upload progress belongs to the uploader, not to a class.

    A lecturer preparing material names no session, so before the user channel
    existed they joined no room and every delivery path returned nothing.
    """
    hub = SessionHub()
    lecturer = uuid4()
    socket = _FakeSocket()

    await hub.join(
        Connection(
            socket,
            lecturer,
            None,
        )
    )  # type: ignore[arg-type]

    delivered = await hub.send_to_user_channel(
        lecturer,
        ServerEventType.MATERIAL_PROGRESS,
        {"stage": "extracting", "percent": 30},
    )

    assert delivered == 1
    assert socket.sent[0]["type"] == ServerEventType.MATERIAL_PROGRESS.value
    assert socket.sent[0]["data"]["percent"] == 30


async def test_user_channel_reaches_every_connection_a_lecturer_holds() -> None:
    """Teams in the desktop app and a browser tab are both live sockets."""
    hub = SessionHub()
    lecturer = uuid4()
    sockets = [_FakeSocket() for _ in range(3)]

    for socket in sockets:
        await hub.join(
            Connection(
                socket,
                lecturer,
                None,
            )
        )  # type: ignore[arg-type]

    delivered = await hub.send_to_user_channel(
        lecturer,
        ServerEventType.MATERIAL_PROGRESS,
        {},
    )

    assert delivered == 3
    assert all(len(socket.sent) == 1 for socket in sockets)


async def test_user_channel_sequence_numbers_increase() -> None:
    """A lecturer watching an import detects a gap the same way a student does."""
    hub = SessionHub()
    lecturer = uuid4()
    socket = _FakeSocket()

    await hub.join(
        Connection(
            socket,
            lecturer,
            None,
        )
    )  # type: ignore[arg-type]

    for _ in range(3):
        await hub.send_to_user_channel(
            lecturer,
            ServerEventType.MATERIAL_PROGRESS,
            {},
        )

    assert [frame["seq"] for frame in socket.sent] == [1, 2, 3]


async def test_user_channel_delivery_to_nobody_is_not_an_error() -> None:
    """Closing the tab must not fail the import that is still running."""
    hub = SessionHub()

    delivered = await hub.send_to_user_channel(
        uuid4(),
        ServerEventType.MATERIAL_PROGRESS,
        {},
    )

    assert delivered == 0


async def test_a_dead_socket_is_dropped_from_the_user_channel() -> None:
    hub = SessionHub()
    lecturer = uuid4()
    dead = _FakeSocket(fail=True)
    alive = _FakeSocket()

    for socket in (dead, alive):
        await hub.join(
            Connection(
                socket,
                lecturer,
                None,
            )
        )  # type: ignore[arg-type]

    assert (
        await hub.send_to_user_channel(
            lecturer,
            ServerEventType.MATERIAL_PROGRESS,
            {},
        )
        == 1
    )

    # The dead socket is gone, so the next send does not retry it.
    assert (
        await hub.send_to_user_channel(
            lecturer,
            ServerEventType.MATERIAL_PROGRESS,
            {},
        )
        == 1
    )
    assert len(alive.sent) == 2


async def test_a_live_user_channel_keeps_its_counter_when_the_ceiling_is_reached() -> None:
    """Eviction looks at rooms and at users.

    Consulting only the room index marks every user channel idle, and a
    lecturer watching an upload sees the seq restart at 1 mid-import.
    """
    hub = SessionHub()
    lecturer = uuid4()

    await hub.join(
        Connection(
            _FakeSocket(),
            lecturer,
            None,
        )
    )  # type: ignore[arg-type]

    assert (
        hub.build(
            lecturer,
            ServerEventType.MATERIAL_PROGRESS,
            {},
        ).seq
        == 1
    )

    for _ in range(MAX_TRACKED_SESSIONS + 50):
        hub.build(
            uuid4(),
            ServerEventType.PONG,
            {},
        )

    assert (
        hub.build(
            lecturer,
            ServerEventType.MATERIAL_PROGRESS,
            {},
        ).seq
        == 2
    )


async def test_leaving_clears_the_user_index() -> None:
    hub = SessionHub()
    lecturer = uuid4()
    connection = Connection(
        _FakeSocket(),
        lecturer,
        None,
    )  # type: ignore[arg-type]

    await hub.join(connection)
    await hub.leave(connection)

    assert (
        await hub.send_to_user_channel(
            lecturer,
            ServerEventType.MATERIAL_PROGRESS,
            {},
        )
        == 0
    )


async def test_a_session_connection_is_reachable_on_both_channels() -> None:
    """Joining a session must not cost a connection its own address."""
    hub = SessionHub()
    session = uuid4()
    student = uuid4()
    socket = _FakeSocket()

    await hub.join(
        Connection(
            socket,
            student,
            session,
        )
    )  # type: ignore[arg-type]

    assert hub.participant_count(session) == 1
    assert (
        await hub.send_to_user_channel(
            student,
            ServerEventType.MATERIAL_PROGRESS,
            {},
        )
        == 1
    )
    assert (
        await hub.broadcast(
            session,
            ServerEventType.SESSION_STATE,
            {},
        )
        == 1
    )


async def test_concurrent_progress_arrives_in_sequence_order() -> None:
    """A lecturer can have two uploads processing at once, and both report on
    the same channel. Sockets do not complete their writes in equal time, so
    numbering and delivery have to be one step or the client sees 2 then 1 and
    reads a gap where nothing was lost."""

    class UnevenSocket:
        def __init__(self) -> None:
            self.received: list[int] = []

        async def send_json(self, payload: dict) -> None:
            await asyncio.sleep(0.01 if payload["seq"] % 2 else 0.0)
            self.received.append(payload["seq"])

    hub = SessionHub()
    lecturer = uuid4()
    socket = UnevenSocket()
    await hub.join(Connection(socket, lecturer, None))

    await asyncio.gather(
        *[
            hub.send_to_user_channel(lecturer, ServerEventType.MATERIAL_PROGRESS, {})
            for _ in range(6)
        ]
    )

    assert socket.received == [1, 2, 3, 4, 5, 6]


class _StalledSocket:
    """A client that has stopped acknowledging without closing the connection."""

    def __init__(self) -> None:
        self.attempts = 0

    async def send_json(self, payload: dict) -> None:
        self.attempts += 1
        await asyncio.sleep(3600)


async def test_a_stalled_lecturer_does_not_hold_up_another_lecturers_progress() -> None:
    """One lock for the whole hub, held across socket writes, meant a single
    stuck connection stopped progress reaching every lecturer on the process."""
    hub = SessionHub()
    stalled, other = uuid4(), uuid4()
    await hub.join(Connection(_StalledSocket(), stalled, None))
    healthy = _FakeSocket()
    await hub.join(Connection(healthy, other, None))

    stuck = asyncio.create_task(
        hub.send_to_user_channel(stalled, ServerEventType.MATERIAL_PROGRESS, {})
    )
    await asyncio.sleep(0)

    started = time.monotonic()
    delivered = await hub.send_to_user_channel(other, ServerEventType.MATERIAL_PROGRESS, {})

    assert delivered == 1
    assert time.monotonic() - started < 0.5
    stuck.cancel()


async def test_a_socket_that_stops_acknowledging_is_dropped(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Treated like a closed socket: the client reconnects and resumes, which
    beats every later event for that lecturer waiting on it."""
    monkeypatch.setattr(hub_module, "SEND_TIMEOUT_SECONDS", 0.05)
    hub = SessionHub()
    lecturer = uuid4()
    socket = _StalledSocket()
    await hub.join(Connection(socket, lecturer, None))

    first = await hub.send_to_user_channel(lecturer, ServerEventType.MATERIAL_PROGRESS, {})
    second = await hub.send_to_user_channel(lecturer, ServerEventType.MATERIAL_PROGRESS, {})

    assert first == 0
    assert second == 0
    assert socket.attempts == 1


async def test_a_stalled_socket_in_a_class_does_not_stall_the_broadcast(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Broadcast walks the room one socket at a time, so without a bound one
    student in a tunnel holds a question back from the other thirty-nine."""
    monkeypatch.setattr(hub_module, "SEND_TIMEOUT_SECONDS", 0.05)
    hub = SessionHub()
    session = uuid4()
    await hub.join(Connection(_StalledSocket(), uuid4(), session))
    listening = _FakeSocket()
    await hub.join(Connection(listening, uuid4(), session))

    delivered = await hub.broadcast(session, ServerEventType.PONG, {})

    assert delivered == 1
    assert len(listening.sent) == 1


async def test_per_user_delivery_locks_are_released_once_idle() -> None:
    """A lock per user is only safe if it goes away again. Otherwise every
    lecturer who ever uploaded leaves an entry behind for the life of the
    process."""
    hub = SessionHub()
    lecturers = [uuid4() for _ in range(50)]
    for lecturer in lecturers:
        await hub.join(Connection(_FakeSocket(), lecturer, None))

    await asyncio.gather(
        *[
            hub.send_to_user_channel(lecturer, ServerEventType.MATERIAL_PROGRESS, {})
            for lecturer in lecturers
            for _ in range(3)
        ]
    )

    assert hub._delivery_locks == {}
    assert hub._delivery_waiters == {}
