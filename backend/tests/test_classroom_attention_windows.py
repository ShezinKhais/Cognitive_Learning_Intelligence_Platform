"""Attention signals reaching the analytics layer: the classroom hands each
finished minute to the AttentionRecorder.

Owner: General CS, Phase 6 (#59).
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

import pytest

from app.realtime import classroom as classroom_module
from app.realtime import recorders as recorders_module
from app.realtime.consent import ConsentRegistry
from app.schemas.events import AttentionSignalPayload
from app.schemas.identity import ConsentType, Role
from app.schemas.session import SessionStatus

from .classroom_support import join_as, make_room, make_row

pytestmark = pytest.mark.usefixtures("fake_session_repository")

START = datetime(2026, 10, 13, 10, 0, 1, tzinfo=UTC)
EVERYTHING = {
    ConsentType.TERMS,
    ConsentType.ENGAGEMENT_MONITORING,
    ConsentType.CAMERA,
    ConsentType.MICROPHONE,
}


@dataclass
class _Summaries:
    stored: list = field(default_factory=list)
    fail_with: Exception | None = None
    hang: bool = False
    # How long each call takes, in turn; calls after these take no time.
    delays: list[float] = field(default_factory=list)

    async def record_windows(self, windows) -> None:  # noqa: ANN001
        if self.hang:
            await asyncio.sleep(10)
        await asyncio.sleep(self.delays.pop(0) if self.delays else 0.0)
        if self.fail_with is not None:
            raise self.fail_with
        self.stored.extend(windows)


async def _stored(room, row) -> None:  # noqa: ANN001
    """Wait for the minutes being stored in the background."""
    live = room.get_running(row.session_id)
    await asyncio.gather(*live.storing)


@pytest.fixture
def clock(monkeypatch: pytest.MonkeyPatch):  # noqa: ANN201
    now = [START]
    monkeypatch.setattr(classroom_module, "_now", lambda: now[0])

    def advance(seconds: float) -> None:
        now[0] += timedelta(seconds=seconds)

    return advance


async def _room(consents: ConsentRegistry | None = None):  # noqa: ANN202
    room, events = make_room(consents=consents)
    row = make_row()
    room.activate(row.session_id)
    _, student = await join_as(events, row.session_id, Role.STUDENT)
    summaries = _Summaries()
    room.attention_recorder = summaries
    return room, row, student, summaries


def _signal(**fields: object) -> AttentionSignalPayload:
    fields.setdefault("window_seconds", 5.0)
    return AttentionSignalPayload(**fields)  # type: ignore[arg-type]


async def test_a_finished_minute_is_stored_once_the_next_begins(clock) -> None:  # noqa: ANN001
    room, row, student, summaries = await _room()
    for _ in range(3):
        assert await room.record_attention(row.session_id, student, _signal(speaking=True))
        clock(5)
    assert summaries.stored == []

    clock(60)
    assert await room.record_attention(row.session_id, student, _signal(speaking=False))
    await _stored(room, row)

    [minute] = summaries.stored
    assert (minute.session_id, minute.user_id) == (row.session_id, student)
    assert minute.window_start == START.replace(second=0)
    assert [s.speaking for s in minute.signals] == [True, True, True]
    await room.shutdown()


async def test_ending_the_session_stores_the_minute_still_open(clock) -> None:  # noqa: ANN001
    room, row, student, summaries = await _room()
    assert await room.record_attention(row.session_id, student, _signal(face_present=True))

    await room.end(row.session_id, SessionStatus.ENDED, 0)

    [minute] = summaries.stored
    assert minute.signals[0].face_present is True


async def test_pausing_keeps_the_minute_so_it_is_stored_once(clock) -> None:  # noqa: ANN001
    """A pause stores nothing: the minute it falls in may carry on after the
    resume, and is stored once, whole, when it is over."""
    room, row, student, summaries = await _room()
    assert await room.record_attention(row.session_id, student, _signal())
    live = room.get_running(row.session_id)
    assert live is not None
    live.countdown.pause()

    clock(5)
    assert await room.record_attention(row.session_id, student, _signal())
    await room.end(row.session_id, SessionStatus.ENDED, 0)

    [minute] = summaries.stored
    assert len(minute.signals) == 2


async def test_a_flood_of_signals_keeps_one_every_two_seconds(clock) -> None:  # noqa: ANN001
    room, row, student, summaries = await _room()
    for _ in range(20):
        assert await room.record_attention(row.session_id, student, _signal())
        clock(0.1)

    await room.end(row.session_id, SessionStatus.ENDED, 0)

    [minute] = summaries.stored
    assert len(minute.signals) == 1


async def test_withdrawing_monitoring_means_the_open_minute_is_never_stored(
    clock,  # noqa: ANN001
) -> None:
    consents = ConsentRegistry(EVERYTHING)
    room, row, student, summaries = await _room(consents)
    assert await room.record_attention(row.session_id, student, _signal(gaze_on_screen_ratio=0.9))

    await room.withdraw_consent(student, ConsentType.ENGAGEMENT_MONITORING)
    await room.end(row.session_id, SessionStatus.ENDED, 0)

    assert summaries.stored == []


async def test_withdrawing_the_camera_strips_it_from_the_open_minute(clock) -> None:  # noqa: ANN001
    consents = ConsentRegistry(EVERYTHING)
    room, row, student, summaries = await _room(consents)
    assert await room.record_attention(
        row.session_id, student, _signal(gaze_on_screen_ratio=0.9, face_present=True, speaking=True)
    )

    await room.withdraw_consent(student, ConsentType.CAMERA)
    await room.end(row.session_id, SessionStatus.ENDED, 0)

    [minute] = summaries.stored
    kept = minute.signals[0]
    assert (kept.gaze_on_screen_ratio, kept.face_present, kept.speaking) == (None, None, True)


async def test_a_store_that_fails_changes_nothing_for_the_class(
    clock,  # noqa: ANN001
    caplog: pytest.LogCaptureFixture,
) -> None:
    room, row, student, summaries = await _room()
    summaries.fail_with = RuntimeError("database is down")
    assert await room.record_attention(row.session_id, student, _signal())
    clock(60)

    with caplog.at_level("ERROR", logger="clip.classroom"):
        assert await room.record_attention(row.session_id, student, _signal())
        await _stored(room, row)

    assert "could not record attention summaries" in caplog.text
    await room.shutdown()


async def test_the_student_whose_signal_ends_a_minute_does_not_wait_for_it_to_be_stored(
    clock,  # noqa: ANN001
) -> None:
    """Their next answer is read from the same socket, and must not be held
    past its window by a slow store."""
    room, row, student, summaries = await _room()
    summaries.hang = True
    assert await room.record_attention(row.session_id, student, _signal())
    clock(60)

    async with asyncio.timeout(0.5):
        assert await room.record_attention(row.session_id, student, _signal())
    await room.shutdown()


async def test_ending_the_session_waits_for_minutes_still_being_stored(clock) -> None:  # noqa: ANN001
    room, row, student, summaries = await _room()
    # The minute already being stored is the slow one, so ending has to wait
    # for it, not only for the minute it hands over itself.
    summaries.delays = [0.1]
    assert await room.record_attention(row.session_id, student, _signal(speaking=True))
    clock(60)
    assert await room.record_attention(row.session_id, student, _signal(speaking=False))

    await room.end(row.session_id, SessionStatus.ENDED, 0)

    # Stored concurrently, so in either order: compared by minute.
    stored = sorted(summaries.stored, key=lambda w: w.window_start)
    assert [w.signals[0].speaking for w in stored] == [True, False]


async def test_a_store_that_hangs_is_given_up_on_at_the_end(
    clock,  # noqa: ANN001
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(recorders_module, "RECORD_TIMEOUT_SECONDS", 0.05)
    room, row, student, summaries = await _room()
    summaries.hang = True
    assert await room.record_attention(row.session_id, student, _signal())

    async with asyncio.timeout(1):
        await room.end(row.session_id, SessionStatus.ENDED, 0)


async def test_no_recorder_means_nothing_is_stored_and_nothing_breaks(clock) -> None:  # noqa: ANN001
    room, row, student, _ = await _room()
    room.attention_recorder = None
    assert await room.record_attention(row.session_id, student, _signal())

    await room.end(row.session_id, SessionStatus.ENDED, 0)
