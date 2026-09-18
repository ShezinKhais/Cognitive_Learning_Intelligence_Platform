"""One reachability check for every test that needs the database.

Each database fixture used to try its own connection and skip on failure. On
Windows a refused localhost connection takes about four seconds to come back,
so a machine with no database spent three minutes just finding that out, once
per test. The answer does not change during a run, so it is asked once.
"""

import asyncio
from concurrent.futures import ThreadPoolExecutor
from functools import cache

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import NullPool

from app.core.config import get_settings

CONNECT_TIMEOUT_SECONDS = 3


async def _probe() -> str | None:
    engine = create_async_engine(
        get_settings().database_url,
        poolclass=NullPool,
        connect_args={"timeout": CONNECT_TIMEOUT_SECONDS},
    )
    try:
        async with engine.connect() as connection:
            await connection.execute(text("select 1"))
    except Exception as exc:
        return f"no database reachable ({type(exc).__name__})"
    finally:
        await engine.dispose()
    return None


@cache
def _unreachable_reason() -> str | None:
    # Fixtures calling this are already inside an event loop, so the probe
    # gets a loop of its own on a worker thread.
    with ThreadPoolExecutor(max_workers=1) as pool:
        return pool.submit(asyncio.run, _probe()).result()


def require_database() -> None:
    """Skip the calling test when the database is not reachable."""
    reason = _unreachable_reason()
    if reason is not None:
        pytest.skip(reason)
