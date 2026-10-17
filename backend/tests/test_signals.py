"""Attention signals on their way to scoring: the per-socket throttle and the
rolling window of summaries.

Owner: General CS, Phase 6.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from app.realtime.signals import MAX_SAMPLES, SignalWindow, Throttle
from app.schemas.events import AttentionSignalPayload

T0 = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)
LONG = 30.0
SPAN = timedelta(seconds=120)


class _Clock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


def _signal(
    gaze: float | None = None,
    face: bool | None = None,
    speaking: bool | None = None,
    seconds: float = 5.0,
) -> AttentionSignalPayload:
    return AttentionSignalPayload(
        gaze_on_screen_ratio=gaze, face_present=face, speaking=speaking, window_seconds=seconds
    )


def _window(*samples: tuple[float, AttentionSignalPayload]) -> SignalWindow:
    """A window holding each signal, received that many seconds after T0."""
    window = SignalWindow()
    for offset, signal in samples:
        window.add(signal, T0 + timedelta(seconds=offset), LONG)
    return window


# -- the throttle -------------------------------------------------------------------


def test_a_burst_is_allowed_and_then_one_frame_per_interval() -> None:
    clock = _Clock()
    throttle = Throttle(every=2.0, burst=3, clock=clock)

    assert [throttle.allow() for _ in range(4)] == [True, True, True, False]

    clock.now += 1.9
    assert not throttle.allow()
    clock.now += 0.1
    assert throttle.allow()
    assert not throttle.allow()


def test_the_allowance_refills_with_time_but_never_past_the_burst() -> None:
    clock = _Clock()
    throttle = Throttle(every=2.0, burst=3, clock=clock)
    assert [throttle.allow() for _ in range(3)] == [True, True, True]

    # Four intervals earn four tokens, but the bucket holds three.
    clock.now += 8.0

    assert [throttle.allow() for _ in range(4)] == [True, True, True, False]


def test_an_interval_of_zero_never_refuses() -> None:
    throttle = Throttle(every=0.0, burst=1, clock=_Clock())

    assert all(throttle.allow() for _ in range(500))


def test_a_burst_below_one_still_allows_one_frame() -> None:
    throttle = Throttle(every=5.0, burst=0, clock=_Clock())

    assert [throttle.allow() for _ in range(2)] == [True, False]


def test_a_refused_sender_is_told_once_per_quiet_period() -> None:
    clock = _Clock()
    throttle = Throttle(every=2.0, burst=1, clock=clock)

    assert throttle.should_tell(10.0)
    clock.now += 9.9
    assert not throttle.should_tell(10.0)
    clock.now += 0.1
    assert throttle.should_tell(10.0)
    assert not throttle.should_tell(10.0)


# -- the window ---------------------------------------------------------------------


def test_an_empty_window_summarises_to_nothing() -> None:
    assert SignalWindow().summary(T0, SPAN) is None


def test_the_summary_weights_each_reading_by_the_time_it_covers() -> None:
    window = _window((0, _signal(gaze=1.0, seconds=5.0)), (5, _signal(gaze=0.0, seconds=25.0)))

    summary = window.summary(T0 + timedelta(seconds=30), SPAN)

    assert summary is not None
    assert summary.gaze_on_screen_ratio == 5.0 / 30.0
    assert summary.window_seconds == 30.0


def test_one_summary_cannot_claim_more_than_the_longest_it_is_allowed() -> None:
    window = SignalWindow()
    window.add(_signal(gaze=1.0, seconds=3600.0), T0, longest=30.0)
    window.add(_signal(gaze=0.0, seconds=30.0), T0, longest=30.0)

    summary = window.summary(T0, SPAN)

    # Uncapped, the hour of gaze 1.0 would drown the half minute of gaze 0.0.
    assert summary is not None
    assert summary.gaze_on_screen_ratio == 0.5
    assert summary.window_seconds == 60.0


def test_the_window_a_summary_claims_never_exceeds_the_span() -> None:
    window = _window(*[(i * 30, _signal(gaze=0.5, seconds=30.0)) for i in range(4)])

    summary = window.summary(T0 + timedelta(seconds=90), timedelta(seconds=100))

    # Four summaries of 30 seconds are 120 seconds, in a span of 100.
    assert summary is not None
    assert summary.window_seconds == 100.0


def test_summaries_older_than_the_span_are_left_out() -> None:
    window = _window((0, _signal(gaze=0.0)), (200, _signal(gaze=1.0)))

    summary = window.summary(T0 + timedelta(seconds=210), SPAN)

    assert summary is not None
    assert summary.gaze_on_screen_ratio == 1.0
    assert summary.window_seconds == 5.0


def test_a_window_whose_summaries_are_all_too_old_says_nothing() -> None:
    window = _window((0, _signal(gaze=0.2)))

    assert window.summary(T0 + timedelta(seconds=121), SPAN) is None


def test_a_summary_exactly_as_old_as_the_span_still_counts() -> None:
    window = _window((0, _signal(gaze=0.2)))

    summary = window.summary(T0 + SPAN, SPAN)

    assert summary is not None and summary.gaze_on_screen_ratio == 0.2


def test_a_reading_nobody_reported_stays_none_and_is_not_zero() -> None:
    window = _window((0, _signal(speaking=True)))

    summary = window.summary(T0, SPAN)

    assert summary is not None
    assert (summary.gaze_on_screen_ratio, summary.face_present, summary.speaking) == (
        None,
        None,
        True,
    )


def test_a_summary_without_gaze_does_not_dilute_the_ones_that_have_it() -> None:
    window = _window((0, _signal(gaze=0.8, seconds=5.0)), (5, _signal(face=True, seconds=25.0)))

    summary = window.summary(T0 + timedelta(seconds=30), SPAN)

    assert summary is not None
    assert summary.gaze_on_screen_ratio == 0.8
    # The time still counts towards how much of the span the window covers.
    assert summary.window_seconds == 30.0


def test_a_face_is_present_when_it_was_for_most_of_the_time_reported_on() -> None:
    mostly_there = _window(
        (0, _signal(face=True, seconds=20.0)), (20, _signal(face=False, seconds=10.0))
    )
    mostly_away = _window(
        (0, _signal(face=True, seconds=10.0)), (10, _signal(face=False, seconds=20.0))
    )
    half_and_half = _window(
        (0, _signal(face=True, seconds=15.0)), (15, _signal(face=False, seconds=15.0))
    )
    now = T0 + timedelta(seconds=30)

    assert mostly_there.summary(now, SPAN).face_present is True  # type: ignore[union-attr]
    assert mostly_away.summary(now, SPAN).face_present is False  # type: ignore[union-attr]
    assert half_and_half.summary(now, SPAN).face_present is True  # type: ignore[union-attr]


def test_speaking_is_true_if_any_summary_heard_a_voice() -> None:
    now = T0 + timedelta(seconds=15)
    heard_once = _window(
        (0, _signal(speaking=False)), (5, _signal(speaking=True)), (10, _signal(speaking=False))
    )
    never_heard = _window((0, _signal(speaking=False)), (5, _signal(speaking=False)))
    not_reported = _window((0, _signal(speaking=False)), (5, _signal(gaze=0.5)))

    assert heard_once.summary(now, SPAN).speaking is True  # type: ignore[union-attr]
    assert never_heard.summary(now, SPAN).speaking is False  # type: ignore[union-attr]
    assert not_reported.summary(now, SPAN).speaking is False  # type: ignore[union-attr]


def test_the_window_keeps_no_more_than_its_ceiling_and_drops_the_oldest() -> None:
    window = SignalWindow()
    for i in range(MAX_SAMPLES + 10):
        # The first ten look away; everything after looks at the screen.
        window.add(
            _signal(gaze=0.0 if i < 10 else 1.0, seconds=1.0), T0 + timedelta(seconds=i), LONG
        )

    summary = window.summary(T0 + timedelta(seconds=MAX_SAMPLES + 10), SPAN)

    assert len(window) == MAX_SAMPLES
    assert summary is not None
    assert summary.gaze_on_screen_ratio == 1.0
    assert summary.window_seconds == float(MAX_SAMPLES)


def test_the_gaze_of_a_summary_stays_between_zero_and_one() -> None:
    window = SignalWindow()
    # Awkward weights, so the weighted mean carries rounding error.
    for i, (gaze, seconds) in enumerate(
        [(1.0, 0.1), (1.0, 0.2), (1.0, 0.7), (0.0, 1e-9), (1.0, 3.3)]
    ):
        window.add(_signal(gaze=gaze, seconds=seconds), T0 + timedelta(seconds=i), LONG)
    all_away = _window(*[(i, _signal(gaze=0.0, seconds=0.1)) for i in range(7)])

    summary = window.summary(T0 + timedelta(seconds=5), SPAN)
    away = all_away.summary(T0 + timedelta(seconds=7), SPAN)

    assert summary is not None and 0.0 <= summary.gaze_on_screen_ratio <= 1.0  # type: ignore[operator]
    assert away is not None and away.gaze_on_screen_ratio == 0.0


# -- narrowing what is held ---------------------------------------------------------


def test_restricting_drops_the_camera_fields_from_every_summary_held() -> None:
    window = _window(
        (0, _signal(gaze=0.1, face=False, speaking=True)),
        (5, _signal(gaze=0.2, face=False, speaking=False)),
    )

    window.restrict(
        lambda signal: signal.model_copy(
            update={"gaze_on_screen_ratio": None, "face_present": None}
        )
    )
    summary = window.summary(T0 + timedelta(seconds=10), SPAN)

    assert len(window) == 2
    assert summary is not None
    assert (summary.gaze_on_screen_ratio, summary.face_present) == (None, None)
    assert summary.speaking is True
    assert summary.window_seconds == 10.0


def test_restricting_drops_a_summary_wholly_when_nothing_of_it_may_be_kept() -> None:
    window = _window((0, _signal(gaze=0.1, speaking=True)), (5, _signal(gaze=0.9)))

    window.restrict(lambda signal: signal if signal.speaking is None else None)
    summary = window.summary(T0 + timedelta(seconds=10), SPAN)

    assert len(window) == 1
    assert summary is not None and summary.gaze_on_screen_ratio == 0.9
    assert summary.window_seconds == 5.0


def test_restricting_everything_leaves_a_window_that_says_nothing() -> None:
    window = _window((0, _signal(gaze=0.1)), (5, _signal(gaze=0.9)))

    window.restrict(lambda signal: None)

    assert len(window) == 0
    assert window.summary(T0 + timedelta(seconds=10), SPAN) is None
