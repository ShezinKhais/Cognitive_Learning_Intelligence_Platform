"""The wait before a live session's question cycle delivers again.

Owner: General CS, Phase 3.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta


class Countdown:
    """When the next scheduled question is due, and whether the session is
    paused.

    While the session runs, a wait becomes a deadline, due. While it is
    paused, the wait is kept as the time left, left, and becomes a deadline
    again on resume, so a pause is never taken out of the wait. Neither is set
    while a question is open, since the next wait only starts at its close, or
    when the cycle is off and the lecturer sends every question.
    """

    def __init__(self, wait: timedelta | None, *, paused: bool) -> None:
        self.paused = paused
        self.due: datetime | None = None
        self.left: timedelta | None = None
        # Set whenever due changes, so the cycle measures again.
        self.changed = asyncio.Event()
        self.start(wait)

    def start(self, wait: timedelta | None) -> None:
        """Count down from wait, or stop counting for None."""
        if self.paused:
            self.left = wait
        else:
            self.due = None if wait is None else datetime.now(UTC) + wait
            self.changed.set()

    def pause(self) -> None:
        if self.due is not None:
            self.left = max(self.due - datetime.now(UTC), timedelta(0))
        else:
            self.left = None
        self.due = None
        self.paused = True

    def resume(self) -> timedelta | None:
        """Run again. Returns the wait that was left, for the caller to start,
        or None if none was."""
        left, self.left = self.left, None
        self.paused = False
        return left
