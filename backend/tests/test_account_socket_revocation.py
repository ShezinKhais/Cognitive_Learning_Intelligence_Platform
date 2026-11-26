"""WebSocket revocation tests for account credential changes."""

from uuid import uuid4

import pytest

from app.realtime.hub import Connection, SessionHub
from app.schemas.identity import Role


class FakeSocket:
    def __init__(self):
        self.closed = []

    async def close(self, *, code, reason):
        self.closed.append((code, reason))


@pytest.mark.asyncio
async def test_password_reset_closes_all_channels_for_only_target_account():
    registry = SessionHub()
    target = uuid4()
    unaffected = uuid4()
    session = uuid4()

    target_session_socket = FakeSocket()
    target_progress_socket = FakeSocket()
    other_session_socket = FakeSocket()
    other_progress_socket = FakeSocket()

    await registry.join(Connection(target_session_socket, target, session, Role.STUDENT))
    await registry.join(Connection(target_progress_socket, target, None, Role.STUDENT))
    await registry.join(Connection(other_session_socket, unaffected, session, Role.STUDENT))
    await registry.join(Connection(other_progress_socket, unaffected, None, Role.STUDENT))

    closed = await registry.close_user_sessions(
        target,
        4001,
        "account credentials changed",
        include_user_channel=True,
    )

    assert closed == 2
    assert target_session_socket.closed == [(4001, "account credentials changed")]
    assert target_progress_socket.closed == [(4001, "account credentials changed")]
    assert other_session_socket.closed == []
    assert other_progress_socket.closed == []

    assert registry.connection_count(session, target) == 0
    assert registry.connection_count(session, unaffected) == 1
    assert registry.participant_count(session) == 1


@pytest.mark.asyncio
async def test_consent_withdrawal_preserves_personal_channel():
    registry = SessionHub()
    student = uuid4()
    session = uuid4()

    session_socket = FakeSocket()
    progress_socket = FakeSocket()

    await registry.join(Connection(session_socket, student, session, Role.STUDENT))
    await registry.join(Connection(progress_socket, student, None, Role.STUDENT))

    closed = await registry.close_user_sessions(student, 4003, "consent withdrawn")

    assert closed == 1
    assert session_socket.closed == [(4003, "consent withdrawn")]
    assert progress_socket.closed == []
    assert registry.connection_count(session, student) == 0
    assert registry.participant_count(student) == 1
