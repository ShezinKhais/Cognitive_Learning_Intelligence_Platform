"""Logging setup.

configure_logging runs at import in app.main, so anything it raises stops the
process before a single line has been logged. That makes the level setting the
one place where being strict costs more than it saves.
"""

import logging
from collections.abc import Iterator

import pytest

from app.core.logging import DEFAULT_LEVEL, configure_logging, resolve_level


@pytest.fixture(autouse=True)
def _restore_root_logger() -> Iterator[None]:
    """configure_logging replaces the root handlers, so put them back."""
    root = logging.getLogger()
    handlers = root.handlers[:]
    level = root.level
    yield
    root.handlers[:] = handlers
    root.setLevel(level)


@pytest.mark.parametrize(
    ("configured", "expected"),
    [
        ("INFO", logging.INFO),
        ("DEBUG", logging.DEBUG),
        ("WARNING", logging.WARNING),
        # A .env is hand-edited and lowercase is the natural way to write these.
        ("debug", logging.DEBUG),
        ("info", logging.INFO),
        ("Warning", logging.WARNING),
        ("  error  ", logging.ERROR),
    ],
)
def test_a_readable_level_is_applied(configured: str, expected: int) -> None:
    configure_logging(configured)
    assert logging.getLogger().level == expected


@pytest.mark.parametrize("configured", ["", "verbose", "20", "loud"])
def test_an_unusable_level_falls_back_instead_of_refusing_to_start(configured: str) -> None:
    """Previously this raised ValueError out of the logging module at import,
    which stopped the app without ever naming CLIP_LOG_LEVEL."""
    configure_logging(configured)
    assert logging.getLogger().level == logging.getLevelNamesMapping()[DEFAULT_LEVEL]


def test_an_unusable_level_says_what_was_wrong() -> None:
    _, problem = resolve_level("verbose")
    assert problem is not None
    assert "CLIP_LOG_LEVEL" in problem
    assert "verbose" in problem
    assert DEFAULT_LEVEL in problem


def test_a_usable_level_reports_no_problem() -> None:
    resolved, problem = resolve_level("debug")
    assert resolved == logging.DEBUG
    assert problem is None


def test_the_fallback_is_logged_through_the_handler_it_just_installed(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """The complaint is useless if it goes out before logging is configured.

    caplog cannot see this one: configure_logging clears the root handlers,
    which removes the handler caplog captures through. Reading stderr checks
    the thing that matters anyway, that the line went out through the handler
    and formatter the function had just installed.
    """
    configure_logging("nonsense")
    written = capsys.readouterr().err

    assert "CLIP_LOG_LEVEL" in written
    assert "nonsense" in written
    assert "WARNING" in written
    # the request-id field the formatter adds, unset outside a request
    assert "[-]" in written
