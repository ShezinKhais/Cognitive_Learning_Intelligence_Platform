"""What has gone wrong lately, for the admin status page.

Owner: General CS. Operational error monitoring for a one-laptop demo
deployment, where nobody is watching the console.

Server errors are caught from logging: every ERROR or worse, and every
"security_event=" warning, which is how refusals worth noticing are logged.
Browser crashes are reported by the frontend to POST /client-errors. Repeats
of the same problem are grouped and counted, so a crash in a loop is one line
with a count, not a page of them.

Kept in memory and bounded. It is a view of the last hours, not an archive:
the container's log keeps the full record, and each entry carries the request
id to find it there. Messages are cut short, and nothing from a request body
is ever added here.
"""

from __future__ import annotations

import logging
import threading
from collections import OrderedDict
from dataclasses import dataclass
from datetime import UTC, datetime

MAX_GROUPS = 200
MAX_MESSAGE = 300


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
    def __init__(self, max_groups: int = MAX_GROUPS) -> None:
        self._groups: OrderedDict[tuple[str, str, str], ErrorGroup] = OrderedDict()
        self._lock = threading.Lock()
        self._max = max_groups
        self.started_at = datetime.now(UTC)
        self.total = 0

    def add(
        self, *, source: str, level: str, where: str, message: str, request_id: str | None = None
    ) -> None:
        message = " ".join(message.split())[:MAX_MESSAGE] or "(no message)"
        where = where[:200]
        key = (source, where, message[:120])
        now = datetime.now(UTC)
        with self._lock:
            self.total += 1
            group = self._groups.pop(key, None)
            if group is None:
                group = ErrorGroup(source, level, where, message, 0, now, now, request_id)
            group.count += 1
            group.last_at = now
            group.level = level
            if request_id and request_id != "-":
                group.request_id = request_id
            self._groups[key] = group
            while len(self._groups) > self._max:
                self._groups.popitem(last=False)

    def recent(self) -> list[ErrorGroup]:
        """Newest first."""
        with self._lock:
            return list(reversed(self._groups.values()))

    def clear(self) -> None:
        with self._lock:
            self._groups.clear()
            self.total = 0


error_log = ErrorLog()


class ErrorLogHandler(logging.Handler):
    """Copies the log lines an admin should see into error_log."""

    def __init__(self, log: ErrorLog = error_log) -> None:
        super().__init__(level=logging.WARNING)
        self._log = log

    def emit(self, record: logging.LogRecord) -> None:
        try:
            message = record.getMessage()
            if record.levelno < logging.ERROR and not message.startswith("security_event="):
                return
            if record.exc_info and record.exc_info[0] is not None:
                message = f"{message} ({record.exc_info[0].__name__})"
            self._log.add(
                source="server",
                level=record.levelname,
                where=record.name,
                message=message,
                request_id=getattr(record, "request_id", None),
            )
        except Exception:  # pragma: no cover - logging must never raise
            self.handleError(record)
