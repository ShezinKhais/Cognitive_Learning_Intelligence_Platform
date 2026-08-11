"""Logging setup with request correlation.

A user reporting a problem can quote the request ID shown in the error body.
This makes that ID appear on every log line produced while handling their
request, so it can actually be found.
"""

from __future__ import annotations

import logging
from contextvars import ContextVar

request_id_var: ContextVar[str] = ContextVar("request_id", default="-")

DEFAULT_LEVEL = "INFO"


class RequestIdFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        record.request_id = request_id_var.get()
        return True


def resolve_level(level: str) -> tuple[int, str | None]:
    """Turn a configured level name into a logging constant.

    Returns the level and, when the setting could not be used, a line
    describing what was wrong so the caller can report it once logging works.

    `Logger.setLevel` only accepts the exact uppercase names, so
    CLIP_LOG_LEVEL=debug raised ValueError inside configure_logging, which
    main.py calls at import. A lowercase level in a .env file stopped the
    process with a traceback out of the logging module that never named the
    setting responsible. A level nobody can read is not worth refusing to
    start over, so an unusable value falls back and says so.
    """
    name = (level or "").strip().upper()
    resolved = logging.getLevelNamesMapping().get(name)
    if resolved is not None:
        return resolved, None

    return logging.getLevelNamesMapping()[DEFAULT_LEVEL], (
        f"CLIP_LOG_LEVEL={level!r} is not a level name, using {DEFAULT_LEVEL}. "
        f"Valid names: {', '.join(sorted(logging.getLevelNamesMapping()))}"
    )


def configure_logging(level: str) -> None:
    handler = logging.StreamHandler()
    handler.setFormatter(
        logging.Formatter("%(asctime)s %(levelname)-8s [%(request_id)s] %(name)s  %(message)s")
    )
    handler.addFilter(RequestIdFilter())

    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)

    resolved, problem = resolve_level(level)
    root.setLevel(resolved)

    # Reported after the handler is attached, so the complaint about the
    # logging setting actually goes through the logging setup.
    if problem:
        logging.getLogger("clip").warning(problem)

    # Uvicorn installs its own handlers; route them through ours so every line
    # carries the request ID.
    for name in ("uvicorn", "uvicorn.error", "uvicorn.access"):
        logger = logging.getLogger(name)
        logger.handlers.clear()
        logger.propagate = True
