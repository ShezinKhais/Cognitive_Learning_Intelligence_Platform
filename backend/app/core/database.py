"""Async SQLAlchemy engine, session factory and declarative base.

The engine is created lazily so authentication and WebSocket tests can run
before the BBIS/PostgreSQL workstream is available.
"""

import asyncio
from collections.abc import AsyncGenerator

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase

from app.core.config import get_settings

# asyncpg connections belong to the event loop that opened them, but a plain
# @lru_cache'd engine is a single process-wide object. In production there is
# only ever one loop, so that difference never shows up. In the test suite,
# where every test function gets its own loop and Phase 3's session cycle and
# auto-close timers (app.services.session_lifecycle) reach the database from
# background tasks outside any single request's loop, a later test could be
# handed a pooled connection tied to a loop that has already been closed.
# BackgroundProcessor._slot() hit the identical problem with a Semaphore and
# fixed it the same way: key the cached object by the running loop instead of
# caching it for the process.
_engine: AsyncEngine | None = None
_engine_loop: asyncio.AbstractEventLoop | None = None
_session_factory: async_sessionmaker[AsyncSession] | None = None


def get_engine() -> AsyncEngine:
    global _engine, _engine_loop, _session_factory

    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None

    if _engine is None or _engine_loop is not loop:
        settings = get_settings()
        _engine = create_async_engine(
            settings.database_url,
            echo=settings.clip_env == "development",
            pool_pre_ping=True,
        )
        _engine_loop = loop
        # The old engine's pooled connections belong to a different loop and
        # cannot be closed on this one; dropping the reference and letting
        # them be garbage-collected is the same trade-off _slot() makes.
        _session_factory = None

    return _engine


def get_session_factory() -> async_sessionmaker[AsyncSession]:
    global _session_factory
    engine = get_engine()  # may replace the engine for a new loop
    if _session_factory is None:
        _session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    return _session_factory


class Base(DeclarativeBase):
    """Declarative base for all ORM models."""


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """FastAPI dependency yielding a request-scoped session."""
    async with get_session_factory()() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
