"""Blocking work run in a thread shutdown does not wait for.

Owner: General CS, Phase 2.
"""

from __future__ import annotations

import asyncio
import contextlib
import time

import pytest

from app.core.threads import run_in_daemon_thread


def test_shutdown_does_not_wait_for_a_parse_it_has_abandoned() -> None:
    """Cancelling cannot stop a thread. With the default executor the process
    then waited for the whole parse before it could exit, for a result it had
    already discarded."""

    def slow_parse() -> str:
        time.sleep(2)
        return "too late"

    async def deploy() -> None:
        parse = asyncio.create_task(run_in_daemon_thread(slow_parse, name="parse"))
        await asyncio.sleep(0.05)
        parse.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await parse

    started = time.monotonic()
    asyncio.run(deploy())

    assert time.monotonic() - started < 1.0


async def test_daemon_thread_returns_results_and_raises_errors_unchanged() -> None:
    """A bad document has to arrive as the ValidationError the pipeline treats
    as the lecturer's problem, not as something wrapped or swallowed."""

    def parses() -> int:
        return 42

    def rejects() -> None:
        raise ValueError("not a real document")

    assert await run_in_daemon_thread(parses, name="parse") == 42
    with pytest.raises(ValueError, match="not a real document"):
        await run_in_daemon_thread(rejects, name="parse")
