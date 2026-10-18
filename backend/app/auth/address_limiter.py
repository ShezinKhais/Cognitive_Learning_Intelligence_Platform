"""Failed sign-ins counted per client address.

The per-account lockout (store.py, login_security.py) stops anyone guessing
one account's password. It does nothing about one address trying a common
password against every account, and it hands that address a way to lock any
user out by failing five times. This counts failures per address and refuses
the address for the rest of the window once it has too many.

Only failures are counted, and the limit is set well above a room's typos,
because a campus puts a whole class behind one address and every student
signs in at the start of the lecture.

Held in memory. The backend runs one worker (backend/Dockerfile), so this is
the whole picture; with several, each would count its own share.
"""

from __future__ import annotations

import time
from collections import deque
from collections.abc import Callable
from functools import lru_cache

from app.core.config import get_settings
from app.core.errors import RateLimitedError

# Addresses tracked at once. Past this the address seen least recently is
# forgotten, so a spray from many addresses cannot grow the table without end.
MAX_TRACKED_ADDRESSES = 10_000


class LoginAddressLimiter:
    def __init__(
        self,
        max_failures: int,
        window_seconds: float,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._max_failures = max_failures
        self._window = window_seconds
        self._clock = clock
        self._failures: dict[str, deque[float]] = {}
        # Attempts checked but not yet decided. They count against the
        # address, so a burst sent at once cannot all pass the check before
        # the first of them has failed.
        self._in_flight: dict[str, int] = {}

    def _recent(self, address: str, now: float) -> deque[float] | None:
        failures = self._failures.get(address)
        if failures is None:
            return None
        while failures and now - failures[0] >= self._window:
            failures.popleft()
        if not failures:
            del self._failures[address]
            return None
        return failures

    def check(self, address: str) -> None:
        """Refuse an address that has failed too often in the window.

        Called before the password is checked, so a refused address learns
        nothing about whether its guess was right.
        """
        now = self._clock()
        failures = self._recent(address, now)
        failed = len(failures) if failures is not None else 0
        if failed + self._in_flight.get(address, 0) >= self._max_failures:
            oldest = failures[0] if failures else now
            retry_after = max(1, round(self._window - (now - oldest)))
            raise RateLimitedError(
                "Too many sign-in attempts from this network. Try again in a few minutes.",
                {"retry_after_seconds": retry_after},
            )

    def begin(self, address: str) -> None:
        """check(), then hold a place for this attempt until end()."""
        self.check(address)
        self._in_flight[address] = self._in_flight.get(address, 0) + 1

    def end(self, address: str) -> None:
        held = self._in_flight.get(address, 0) - 1
        if held > 0:
            self._in_flight[address] = held
        else:
            self._in_flight.pop(address, None)

    def record_failure(self, address: str) -> None:
        now = self._clock()
        failures = self._recent(address, now)
        if failures is None:
            if len(self._failures) >= MAX_TRACKED_ADDRESSES:
                # Dicts keep insertion order and a fresh failure re-inserts
                # its address below, so the first key is the stalest.
                del self._failures[next(iter(self._failures))]
            failures = deque()
        else:
            del self._failures[address]
        failures.append(now)
        self._failures[address] = failures

    def reset(self) -> None:
        self._failures.clear()
        self._in_flight.clear()


@lru_cache
def get_login_address_limiter() -> LoginAddressLimiter:
    settings = get_settings()
    return LoginAddressLimiter(
        settings.login_failures_per_address,
        settings.login_failure_window_minutes * 60,
    )
