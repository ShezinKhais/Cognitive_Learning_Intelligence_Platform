"""Attention signals on their way from a student's device to engagement scoring.

Owner: General CS, Phase 6.

A student's device sends `signal.attention` every few seconds: a gaze ratio,
whether a face was in view and whether there was voice activity, each a
number or a flag worked out on the device. Nothing else can travel on that
event, so no frame or audio ever leaves the device.

Two things happen to a signal here before anything reads it.

It is throttled. The client sends one every five seconds; a socket sending
many times that is broken or hostile, and each frame would otherwise take the
session's lock.

It is aggregated. One five-second summary says where a student happened to be
looking at that moment. Scoring reads a rolling window instead, each summary
weighted by the time it covers, so a glance away is a small part of a minute
and not the whole of the evidence. A window that covers too little of that
minute says nothing: a student who has just turned the camera on is not
judged on the first frame.

What consent covers is decided before a signal reaches this module, by
realtime/consent.py, and applied again to everything already held when a
consent is withdrawn.
"""

from __future__ import annotations

from collections import deque
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta

from app.schemas.events import AttentionSignalPayload
from app.services.engagement import ENGAGED_THRESHOLD

# Summaries kept per student. A minute of five-second summaries is twelve;
# this is the ceiling whatever the client sends.
MAX_SAMPLES = 64


class Throttle:
    """A token bucket for one kind of frame on one socket.

    `burst` frames may arrive together, as they do when a tab wakes up, and
    one more is allowed every `every` seconds after that.
    """

    def __init__(self, every: float, burst: int, clock: Callable[[], float]) -> None:
        self._every = max(every, 0.0)
        self._burst = max(burst, 1)
        self._clock = clock
        self._tokens = float(self._burst)
        self._at = clock()
        self._told_at: float | None = None

    def allow(self) -> bool:
        if self._every == 0.0:
            return True
        now = self._clock()
        self._tokens = min(float(self._burst), self._tokens + (now - self._at) / self._every)
        self._at = now
        if self._tokens < 1.0:
            return False
        self._tokens -= 1.0
        return True

    def should_tell(self, quiet_for: float) -> bool:
        """Whether a refused sender is owed an error now. One is enough for a
        burst: answering every dropped frame would double the traffic the
        throttle exists to limit."""
        now = self._clock()
        if self._told_at is not None and now - self._told_at < quiet_for:
            return False
        self._told_at = now
        return True


@dataclass(frozen=True, slots=True)
class _Sample:
    at: datetime
    seconds: float
    gaze: float | None
    face: bool | None
    speaking: bool | None


class SignalWindow:
    """One student's recent attention summaries."""

    def __init__(self) -> None:
        self._samples: deque[_Sample] = deque(maxlen=MAX_SAMPLES)

    def __len__(self) -> int:
        return len(self._samples)

    def newest_at(self) -> datetime | None:
        """When the newest summary held was received, or None with none."""
        return self._samples[-1].at if self._samples else None

    def add(self, signal: AttentionSignalPayload, at: datetime, longest: float) -> None:
        """Keep a summary. `longest` caps the time one summary may claim to
        cover, so a client cannot outweigh a minute of honest summaries by
        saying one of its own describes an hour."""
        self._samples.append(
            _Sample(
                at=at,
                seconds=min(signal.window_seconds, longest),
                gaze=signal.gaze_on_screen_ratio,
                face=signal.face_present,
                speaking=signal.speaking,
            )
        )

    def restrict(
        self, keep: Callable[[AttentionSignalPayload], AttentionSignalPayload | None]
    ) -> None:
        """Narrow every summary held to what `keep` allows, as when camera or
        microphone consent is withdrawn."""
        kept: list[_Sample] = []
        for sample in self._samples:
            allowed = keep(
                AttentionSignalPayload(
                    gaze_on_screen_ratio=sample.gaze,
                    face_present=sample.face,
                    speaking=sample.speaking,
                    window_seconds=sample.seconds,
                )
            )
            if allowed is None:
                continue
            kept.append(
                _Sample(
                    at=sample.at,
                    seconds=sample.seconds,
                    gaze=allowed.gaze_on_screen_ratio,
                    face=allowed.face_present,
                    speaking=allowed.speaking,
                )
            )
        self._samples = deque(kept, maxlen=MAX_SAMPLES)

    def summary(self, now: datetime, span: timedelta) -> AttentionSignalPayload | None:
        """The window as one signal, or None when nothing in the last `span`
        was received.

        Gaze is the time-weighted average of the summaries that reported it.
        A face counts as present when it was for at least half the time that
        reported on it. Speaking is whether any summary heard a voice. A
        reading no summary reported stays None: absence is not a low value.
        """
        recent = [s for s in self._samples if now - s.at <= span]
        if not recent:
            return None
        gaze_time = sum(s.seconds for s in recent if s.gaze is not None)
        face_time = sum(s.seconds for s in recent if s.face is not None)
        heard = [s.speaking for s in recent if s.speaking is not None]
        gaze = (
            sum(s.gaze * s.seconds for s in recent if s.gaze is not None) / gaze_time
            if gaze_time > 0
            else None
        )
        face = (
            sum(s.seconds for s in recent if s.face) / face_time >= 0.5 if face_time > 0 else None
        )
        covered = min(sum(s.seconds for s in recent), span.total_seconds())
        if covered <= 0:
            return None
        return AttentionSignalPayload(
            # Rounding in the weighted mean can leave it a hair outside 0 to 1.
            gaze_on_screen_ratio=None if gaze is None else max(0.0, min(1.0, gaze)),
            face_present=face,
            speaking=any(heard) if heard else None,
            window_seconds=covered,
        )


def signals_low(signal: AttentionSignalPayload) -> bool:
    """Whether a student's own signals, taken alone, fall short of engaged:
    the mean of the gaze ratio and face presence, the two weighed equally as
    engagement scoring weighs them, against its threshold. Scoring itself
    will not score the camera alone, so this is worked out here; it only ever
    narrows what scoring already asks for. A window that reported neither
    gaze nor a face is not low: it says nothing."""
    face = signal.face_present
    readings = [
        value
        for value in (signal.gaze_on_screen_ratio, None if face is None else float(face))
        if value is not None
    ]
    return bool(readings) and sum(readings) / len(readings) < ENGAGED_THRESHOLD
