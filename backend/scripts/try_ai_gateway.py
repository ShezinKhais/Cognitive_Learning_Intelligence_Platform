"""Manual check: the AI gateway against the real model.

Not a test. Needs Ollama running with the configured model, and exists to see
the behaviour the unit tests only script: how long a cold load takes, that a
cancelled stream really stops the model, and that a class asking at once is
served in priority order.

Run from backend/:  python scripts/try_ai_gateway.py
"""

import asyncio
import time

from app.services.ai_gateway import (
    AiRequest,
    AiUnavailableError,
    Priority,
    get_ai_gateway,
)


def ask(content: str, **fields) -> AiRequest:
    return AiRequest(
        messages=[{"role": "user", "content": content}], purpose="manual-check", **fields
    )


async def main() -> None:
    gateway = get_ai_gateway()

    print(f"model: {gateway.model}   status: {gateway.status}")
    started = time.monotonic()
    await gateway.warm_up()
    print(f"warm-up took {time.monotonic() - started:.1f}s   status: {gateway.status}")

    started = time.monotonic()
    result = await gateway.complete(ask("In one sentence, what is photosynthesis?"))
    print(f"\ncomplete ({time.monotonic() - started:.1f}s, {result.attempts} attempt):")
    print(f"  {result.text.strip()}")

    print("\nstream:")
    started = time.monotonic()
    async with gateway.stream(ask("Count from 1 to 10, one number per line.")) as reply:
        first = None
        async for _ in reply:
            first = first or time.monotonic() - started
    print(f"  first piece after {first:.2f}s, all of it after {time.monotonic() - started:.2f}s")
    print(f"  {reply.text.strip()!r}")

    print("\ncancel a long stream after five pieces:")
    started = time.monotonic()
    async with gateway.stream(ask("Write a 600 word essay on the water cycle.")) as reply:
        pieces = 0
        async for _ in reply:
            pieces += 1
            if pieces == 5:
                reply.cancel()
    print(f"  stopped after {time.monotonic() - started:.2f}s with {len(reply.text)} characters")
    started = time.monotonic()
    await gateway.complete(ask("Reply with OK.", max_tokens=3))
    print(f"  the next call was answered {time.monotonic() - started:.2f}s later")

    print("\nsix calls at once, the upload first in line:")
    order: list[str] = []

    async def call(name: str, priority: Priority) -> None:
        await gateway.complete(ask("Reply with OK.", priority=priority, max_tokens=3))
        order.append(name)

    calls = [asyncio.create_task(call("upload", Priority.BACKGROUND))]
    calls += [asyncio.create_task(call(f"lecturer {n}", Priority.INTERACTIVE)) for n in (1, 2)]
    calls += [asyncio.create_task(call(f"student {n}", Priority.LIVE)) for n in (1, 2, 3)]
    await asyncio.gather(*calls)
    print(f"  finished in this order: {', '.join(order)}")

    print("\na model that is not installed:")
    missing = ask("Reply with OK.", model="no-such-model")
    try:
        await gateway.complete(missing)
    except AiUnavailableError as exc:
        print(f"  refused with {exc.code}: {exc.message}")
    fallback = "The assistant is unavailable."
    result = await gateway.complete(ask("Reply with OK.", model="no-such-model", fallback=fallback))
    print(f"  with a fallback: {result.text!r} (fallback={result.fallback})")

    await gateway.shutdown()


if __name__ == "__main__":
    asyncio.run(main())
