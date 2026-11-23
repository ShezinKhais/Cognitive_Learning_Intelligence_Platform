"""Running blocking work without holding up shutdown."""

from __future__ import annotations

import asyncio
import contextvars
import threading
from collections.abc import Callable
from typing import TypeVar

T = TypeVar("T")


async def run_in_daemon_thread(fn: Callable[..., T], *args: object, name: str) -> T:
    """Run blocking work off the event loop, in a thread shutdown will not wait for.

    asyncio.to_thread uses the default executor, and cancelling the await does
    not stop the thread, because Python cannot interrupt one. The work ran on
    to the end regardless, and the process could not exit until it had, so a
    deploy that cancelled an eighteen second parse still waited eighteen
    seconds for a result it had already thrown away.

    A daemon thread keeps the event loop just as free and is abandoned when the
    process exits, so it is only safe for work that writes nothing. A result
    that arrives after its awaiter has gone is dropped rather than handed to a
    loop that may already be closed.
    """
    loop = asyncio.get_running_loop()
    future: asyncio.Future[T] = loop.create_future()
    # Carried across, as asyncio.to_thread does, so log lines from inside the
    # work keep the request id of the call that started it.
    context = contextvars.copy_context()

    def settle_result(result: T) -> None:
        if not future.done():
            future.set_result(result)

    def settle_exception(exc: BaseException) -> None:
        if not future.done():
            future.set_exception(exc)

    def target() -> None:
        try:
            result = context.run(fn, *args)
        except BaseException as exc:
            callback, value = settle_exception, exc
        else:
            callback, value = settle_result, result
        try:
            loop.call_soon_threadsafe(callback, value)
        except RuntimeError:
            # The loop closed while this thread was still working, which is
            # what a shutdown looks like from in here. Nobody is waiting.
            pass

    threading.Thread(target=target, name=name, daemon=True).start()
    return await future
