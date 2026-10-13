"""Attention signals gathered into one-minute windows, before they are stored.

Owner: General CS, Phase 6 (#59).
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

from app.realtime.attention import Attention
from app.realtime.attention_windows import AttentionWindows, window_start
from app.schemas.events import AttentionSignalPayload

SESSION = uuid4()
MINUTE = datetime(2026, 10, 13, 10, 0, tzinfo=UTC)


def at(seconds: float) -> datetime:
    return MINUTE + timedelta(seconds=seconds)


def signal(**fields: object) -> AttentionSignalPayload:
    fields.setdefault("window_seconds", 5.0)
    return AttentionSignalPayload(**fields)  # type: ignore[arg-type]


def test_a_minutes_signals_are_kept_together_until_the_minute_is_over() -> None:
    windows, student = AttentionWindows(SESSION), uuid4()

    for second in (5, 10, 15):
        _, finished = windows.add(student, signal(gaze_on_screen_ratio=0.5), at(second))
        assert finished == []
    _, finished = windows.add(student, signal(gaze_on_screen_ratio=0.9), at(65))

    [minute] = finished
    assert (minute.session_id, minute.user_id) == (SESSION, student)
    assert minute.window_start == MINUTE
    assert [s.gaze_on_screen_ratio for s in minute.signals] == [0.5, 0.5, 0.5]
    [rest] = windows.drain()
    assert rest.window_start == MINUTE + timedelta(minutes=1)
    assert [s.gaze_on_screen_ratio for s in rest.signals] == [0.9]


def test_a_new_minute_hands_over_every_students_finished_minute() -> None:
    """A student who stopped sending is not left waiting for their own next
    signal: anyone's signal in a later minute ends theirs."""
    windows, quiet, talker = AttentionWindows(SESSION), uuid4(), uuid4()
    windows.add(quiet, signal(), at(10))
    windows.add(talker, signal(), at(20))

    _, finished = windows.add(talker, signal(), at(70))

    assert {w.user_id for w in finished} == {quiet, talker}


def test_a_signal_sent_too_soon_after_the_last_is_dropped() -> None:
    windows, student = AttentionWindows(SESSION), uuid4()
    windows.add(student, signal(), at(5))

    kept, finished = windows.add(student, signal(), at(6))

    assert kept is None and finished == []
    [minute] = windows.drain()
    assert len(minute.signals) == 1


def test_a_signal_counts_for_no_more_time_than_really_passed() -> None:
    windows, student = AttentionWindows(SESSION), uuid4()

    first, _ = windows.add(student, signal(window_seconds=3600), at(1))
    second, _ = windows.add(student, signal(window_seconds=3600), at(6))
    honest, _ = windows.add(student, signal(window_seconds=4.0), at(11))

    assert first is not None and first.window_seconds == 60.0
    assert second is not None and second.window_seconds == 5.0
    assert honest is not None and honest.window_seconds == 4.0


def test_forgetting_a_student_drops_their_unsent_minute() -> None:
    windows, student, other = AttentionWindows(SESSION), uuid4(), uuid4()
    windows.add(student, signal(), at(5))
    windows.add(other, signal(), at(5))

    windows.forget(student)

    assert [w.user_id for w in windows.drain()] == [other]


def test_restricting_a_student_narrows_their_unsent_minute() -> None:
    windows, student = AttentionWindows(SESSION), uuid4()
    windows.add(student, signal(gaze_on_screen_ratio=0.7, speaking=True), at(5))

    windows.restrict(student, lambda s: s.model_copy(update={"gaze_on_screen_ratio": None}))

    [minute] = windows.drain()
    assert minute.signals[0].gaze_on_screen_ratio is None
    assert minute.signals[0].speaking is True


def test_restricting_away_every_signal_leaves_nothing_to_store() -> None:
    windows, student = AttentionWindows(SESSION), uuid4()
    windows.add(student, signal(), at(5))

    windows.restrict(student, lambda s: None)

    assert windows.drain() == []


def test_draining_hands_over_everything_once() -> None:
    windows = AttentionWindows(SESSION)
    windows.add(uuid4(), signal(), at(5))

    assert len(windows.drain()) == 1
    assert windows.drain() == []


def test_windows_start_on_the_minute() -> None:
    assert window_start(at(59.9)) == MINUTE


# -- through Attention, where consent withdrawal reaches the windows -----------


def test_attention_keeps_the_held_signal_for_scoring() -> None:
    attention, student = Attention(SESSION), uuid4()

    attention.observe(student, signal(window_seconds=3600, gaze_on_screen_ratio=0.4), at(5))

    held = attention._students[student].current_signal(at(6))  # noqa: SLF001
    assert held is not None and held.window_seconds == 60.0


def test_a_dropped_signal_does_not_replace_the_last_one_kept() -> None:
    attention, student = Attention(SESSION), uuid4()
    attention.observe(student, signal(gaze_on_screen_ratio=0.4), at(5))

    attention.observe(student, signal(gaze_on_screen_ratio=0.9), at(5.5))

    held = attention._students[student].current_signal(at(6))  # noqa: SLF001
    assert held is not None and held.gaze_on_screen_ratio == 0.4


def test_withdrawing_monitoring_drops_the_unsent_minute() -> None:
    attention, student = Attention(SESSION), uuid4()
    attention.observe(student, signal(), at(5))

    attention.forget(student)

    assert attention.windows.drain() == []


def test_withdrawing_the_camera_narrows_the_unsent_minute() -> None:
    attention, student = Attention(SESSION), uuid4()
    attention.observe(student, signal(gaze_on_screen_ratio=0.7, face_present=True), at(5))

    attention.restrict_signal(
        student,
        lambda s: s.model_copy(update={"gaze_on_screen_ratio": None, "face_present": None}),
    )

    [minute] = attention.windows.drain()
    assert (minute.signals[0].gaze_on_screen_ratio, minute.signals[0].face_present) == (None, None)
