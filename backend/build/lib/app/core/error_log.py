"""Bounded, in-memory diagnostics for the administrator status page.

Only diagnostic metadata enters this store. Application log messages, exception
values, and browser payloads can contain student content or credentials.
"""

from __future__ import annotations

import logging
import threading
from collections import OrderedDict
from collections.abc import Callable
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from pathlib import Path

from app.core.logging import monitoring_request_id_var

MAX_GROUPS = 200
GROUP_RETENTION = timedelta(hours=24)
SPIKE_THRESHOLD = 10
MINUTE_SECONDS = 60


@dataclass
class ErrorGroup:
    source: str
    level: str
    where: str
    message: str
    count: int
    first_at: datetime
    last_at: datetime
    request_id: str | None


class ErrorLog:
    def __init__(
        self,
        max_groups: int = MAX_GROUPS,
        *,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self._groups: OrderedDict[tuple[str, str, str, str], ErrorGroup] = OrderedDict()
        self._lock = threading.Lock()
        self._max = max_groups
        self._clock = clock
        self._server_errors: dict[int, int] = {}
        self.started_at = clock()
        self.total = 0

    def _expire(self, now: datetime) -> None:
        cutoff = now - GROUP_RETENTION
        while self._groups and next(iter(self._groups.values())).last_at <= cutoff:
            self._groups.popitem(last=False)
        minute = int(now.timestamp()) // MINUTE_SECONDS
        self._server_errors = {
            bucket: count
            for bucket, count in self._server_errors.items()
            if minute - 2 <= bucket <= minute
        }

    def add(
        self, *, source: str, level: str, where: str, message: str, request_id: str | None = None
    ) -> None:
        key = (source, level, where, message)
        with self._lock:
            now = self._clock()
            self._expire(now)
            self.total += 1
            if source == "server" and level in {"ERROR", "CRITICAL"}:
                minute = int(now.timestamp()) // MINUTE_SECONDS
                self._server_errors[minute] = min(
                    SPIKE_THRESHOLD, self._server_errors.get(minute, 0) + 1
                )
            group = self._groups.pop(key, None)
            if group is None:
                group = ErrorGroup(source, level, where, message, 0, now, now, None)
            group.count += 1
            group.last_at = now
            group.request_id = request_id
            self._groups[key] = group
            while len(self._groups) > self._max:
                self._groups.popitem(last=False)

    def recent(self) -> list[ErrorGroup]:
        with self._lock:
            self._expire(self._clock())
            return [replace(group) for group in reversed(self._groups.values())]

    def server_error_spike(self) -> bool:
        with self._lock:
            now = self._clock()
            self._expire(now)
            minute = int(now.timestamp()) // MINUTE_SECONDS
            return all(
                self._server_errors.get(bucket, 0) >= SPIKE_THRESHOLD
                for bucket in (minute - 2, minute - 1)
            )

    def clear(self) -> None:
        with self._lock:
            self._groups.clear()
            self._server_errors.clear()
            self.total = 0


error_log = ErrorLog()


class ErrorLogHandler(logging.Handler):
    """Collect code location and exception type without formatting raw logs."""

    def __init__(self, log: ErrorLog = error_log) -> None:
        super().__init__(level=logging.WARNING)
        self._log = log

    def emit(self, record: logging.LogRecord) -> None:
        if record.levelno >= logging.ERROR:
            level = "CRITICAL" if record.levelno >= logging.CRITICAL else "ERROR"
            kind = record.exc_info[0] if record.exc_info else None
            message = f"Server exception ({kind.__name__})" if kind else "Server error"
        elif isinstance(record.msg, str) and record.msg.startswith("security_event="):
            level, message = "WARNING", "Security check refused a request"
        else:
            return

        self._log.add(
            source="server",
            level=level,
            where=f"{record.name} ({Path(record.pathname).name}:{record.lineno})",
            message=message,
            request_id=monitoring_request_id_var.get(),
        )
