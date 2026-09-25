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
            return
        self.due = None if wait is None else datetime.now(UTC) + wait
        self.changed.set()

    def pause(self) -> None:
        self.left = None if self.due is None else max(self.due - datetime.now(UTC), timedelta(0))
        self.due = None
        self.paused = True

    def resume(self) -> timedelta | None:
        """Run again. Returns the wait that was left for the caller to start,
        or None if there was none."""
        left, self.left = self.left, None
        self.paused = False
        return left

    async def elapsed(self) -> bool:
        """Wait until the next question is due, or until due changes. True
        when it is due now; the caller then measures again either way."""
        due = self.due
        if due is None:
            # A question is open, or the cycle is off: its close starts it.
            self.changed.clear()
            await self.changed.wait()
            return False
        wait = (due - datetime.now(UTC)).total_seconds()
        if wait <= 0:
            self.due = None
            return True
        self.changed.clear()
        try:
            async with asyncio.timeout(wait):
                await self.changed.wait()
        except TimeoutError:
            pass
        return False
