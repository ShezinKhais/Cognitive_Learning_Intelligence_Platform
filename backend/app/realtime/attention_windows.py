"""Each student's attention signals, gathered into one-minute windows.

Owner: General CS, Phase 6 (#59). A student's device sends signal.attention
about every five seconds, derived indicators only (gaze ratio, face present,
speaking, how long they cover). The classroom keeps the latest one for
engagement scoring; this keeps every one a student sent within a clock
minute, so the minute can be summarised and stored for the analytics layer
(BBIS's attention_signal_summary, through the AttentionRecorder seam).

Two things the client says are not taken on trust:

- How often it sends. A signal arriving less than MIN_SIGNAL_INTERVAL after
  the student's last kept one is dropped, so a client in a loop cannot flood
  the session or outweigh everyone else's evidence.
- How long a signal covers. Its window_seconds weighs it in the minute's
  summary, and the contract allows up to an hour. It is held to the time since
  the student's previous signal, and to one window, so one signal cannot speak
  for more time than really passed.

A minute is handed over once it is over: when any student's next signal
arrives after it, and when the session ends. A paused session keeps its
windows, so the minute a pause falls in is still stored once.

Consent is applied before a signal arrives here, and withdrawing it reaches
the windows too: monitoring withdrawn drops the student's unsent minute,
camera or microphone withdrawn narrows it (see Attention.forget and
Attention.restrict_signal).
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from uuid import UUID

from app.realtime.recorders import AttentionWindow
from app.schemas.events import AttentionSignalPayload

WINDOW = timedelta(minutes=1)
# The client sends every five seconds. Faster than every two is a bug or
# abuse, and also bounds a minute to 30 signals.
MIN_SIGNAL_INTERVAL = timedelta(seconds=2)


def window_start(at: datetime) -> datetime:
    """The start of the clock minute `at` falls in."""
    return at.replace(second=0, microsecond=0)


@dataclass(slots=True)
class _Window:
    start: datetime
    signals: list[AttentionSignalPayload] = field(default_factory=list)


class AttentionWindows:
    """One session's unsent minutes, one per student."""

    def __init__(self, session_id: UUID) -> None:
        self.session_id = session_id
        self._open: dict[UUID, _Window] = {}
        # When each student's last kept signal arrived. Kept across windows,
        # and across a withdrawal, so neither resets the rate limit.
        self._last_at: dict[UUID, datetime] = {}

    def add(
        self, user_id: UUID, signal: AttentionSignalPayload, now: datetime
    ) -> tuple[AttentionSignalPayload | None, list[AttentionWindow]]:
        """Keep a signal in the student's current minute.

        Returns the signal as kept, with its window_seconds held to what
        really passed, or None when it came too soon after the last one; and
        every minute, of any student, that is now over and ready to store.
        """
        last = self._last_at.get(user_id)
        if last is not None and now - last < MIN_SIGNAL_INTERVAL:
            return None, []
        covered = min(WINDOW, now - last) if last is not None else WINDOW
        kept = signal.model_copy(
            update={"window_seconds": min(signal.window_seconds, covered.total_seconds())}
        )
        self._last_at[user_id] = now

        start = window_start(now)
        finished = self._take(lambda window: window.start < start)
        self._open.setdefault(user_id, _Window(start)).signals.append(kept)
        return kept, finished

    def drain(self) -> list[AttentionWindow]:
        """Every unsent minute, finished or not, as the session ends."""
        return self._take(lambda window: True)

    def forget(self, user_id: UUID) -> None:
        """Drop the student's unsent minute: monitoring consent was withdrawn,
        so nothing gathered under it is stored."""
        self._open.pop(user_id, None)

    def restrict(
        self,
        user_id: UUID,
        keep: Callable[[AttentionSignalPayload], AttentionSignalPayload | None],
    ) -> None:
        """Narrow the student's unsent minute to what keep allows, as when
        camera or microphone consent is withdrawn."""
        window = self._open.get(user_id)
        if window is None:
            return
        window.signals = [s for s in map(keep, window.signals) if s is not None]
        if not window.signals:
            del self._open[user_id]

    def _take(self, due: Callable[[_Window], bool]) -> list[AttentionWindow]:
        taken = [
            AttentionWindow(
                session_id=self.session_id,
                user_id=user_id,
                window_start=window.start,
                signals=tuple(window.signals),
            )
            for user_id, window in self._open.items()
            if due(window) and window.signals
        ]
        for finished in taken:
            del self._open[finished.user_id]
        return taken
