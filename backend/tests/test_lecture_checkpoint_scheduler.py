"""Regression tests for transcript-aware automatic delivery."""

from uuid import UUID

import pytest

from app.schemas.events import ServerEventType
from app.schemas.identity import Role
from app.services import lecture_checkpoint_selection

from .classroom_support import (
    FakeDb,
    FakeRepository,
    StagedQuestion,
    join_as,
    make_room,
    make_row,
)

pytestmark = pytest.mark.usefixtures("fake_session_repository")


async def test_automatic_delivery_skips_without_evidence(monkeypatch):
    room, events = make_room()
    row = make_row()
    row.question_selection_enabled = True
    socket, _ = await join_as(events, row.session_id, Role.STUDENT)
    staged = StagedQuestion(question_text="What are mammals?")
    FakeRepository.staged.append(staged)

    async def no_match(db, session, checkpoint_at):
        assert session.session_id == row.session_id
        return None

    monkeypatch.setattr(
        lecture_checkpoint_selection,
        "choose_recent_question",
        no_match,
    )

    try:
        live = room.activate(row.session_id)
        assert await room._deliver_on_schedule(live)
        assert not socket.of(ServerEventType.QUESTION_DELIVERED)
        assert FakeRepository.staged == [staged]
    finally:
        await room.shutdown()


async def test_automatic_delivery_uses_selected_question(monkeypatch):
    room, events = make_room()
    row = make_row()
    row.question_selection_enabled = True
    socket, _ = await join_as(events, row.session_id, Role.STUDENT)

    unrelated = StagedQuestion(question_text="What are mammals?")
    related = StagedQuestion(question_text="What are enzymes?")
    FakeRepository.staged.extend([unrelated, related])

    async def select_enzyme(db, session, checkpoint_at) -> UUID:
        assert session.session_id == row.session_id
        return related.question_id

    monkeypatch.setattr(
        lecture_checkpoint_selection,
        "choose_recent_question",
        select_enzyme,
    )

    try:
        live = room.activate(row.session_id)
        assert await room._deliver_on_schedule(live)
        [event] = socket.of(ServerEventType.QUESTION_DELIVERED)
        assert event["data"]["question_id"] == str(related.question_id)
        assert FakeRepository.staged == [unrelated]
    finally:
        await room.shutdown()


async def test_manual_delivery_does_not_require_transcript(monkeypatch):
    room, events = make_room()
    row = make_row()
    row.question_selection_enabled = True
    socket, _ = await join_as(events, row.session_id, Role.STUDENT)
    staged = StagedQuestion(question_text="Manual lecturer question")
    FakeRepository.staged.append(staged)

    async def must_not_run(db, session, checkpoint_at):
        raise AssertionError("Manual delivery must not consult Whisper.")

    monkeypatch.setattr(
        lecture_checkpoint_selection,
        "choose_recent_question",
        must_not_run,
    )

    try:
        delivered = await room.deliver(FakeDb(), row, staged.question_id)
        assert delivered is not None
        assert delivered.question_id == staged.question_id
        assert len(socket.of(ServerEventType.QUESTION_DELIVERED)) == 1
    finally:
        await room.shutdown()
