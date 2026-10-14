"""How fast one socket may talk to the server.

Owner: Cyber 1, Phase 8. The real clients send a handful of events a minute:
a ping, an attention reading every few seconds, an answer when a question is
open. A socket sending hundreds a second is a bug or an attack, and every event
takes the session's lock, so one student could slow the whole class. The socket
is closed, not slowed: a client that ignores its own limit is not one to keep
talking to, and it reconnects normally if it was merely buggy.
"""

from __future__ import annotations

import time
from collections import deque
from collections.abc import Callable

# Ten events a second, sustained over a ten second window.
MAX_EVENTS = 100
WINDOW_SECONDS = 10.0

# Tabs one user may have open in one class.
MAX_SOCKETS_PER_USER = 10


class EventLimit:
    def __init__(
        self,
        max_events: int = MAX_EVENTS,
        window: float = WINDOW_SECONDS,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._max = max_events
        self._window = window
        self._clock = clock
        self._seen: deque[float] = deque()

    def allow(self) -> bool:
        """Count one event. False once more than the limit arrived in the window."""
        now = self._clock()
        while self._seen and now - self._seen[0] > self._window:
            self._seen.popleft()
        if len(self._seen) >= self._max:
            return False
        self._seen.append(now)
        return True
