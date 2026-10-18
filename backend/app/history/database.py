"""The history database: a second Postgres database for derived summaries.

Owner: BBIS, Phase 7. Session data is deleted after DATA_RETENTION_DAYS. What
is kept longer, until the student graduates, is a summary per student, course
and semester: counts and averages, never answers, free text, names or emails.
It lives in its own database so it can be backed up, restricted and erased on
its own. HISTORY_DATABASE_URL empty means history is off.
"""

from __future__ import annotations

from collections.abc import Callable
from functools import lru_cache

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase

from app.core.config import get_settings


class HistoryBase(DeclarativeBase):
    """Declarative base for the history database only."""


def history_enabled() -> bool:
    return bool(get_settings().history_database_url)


@lru_cache
def get_history_engine() -> AsyncEngine:
    url = get_settings().history_database_url
    if not url:
        raise RuntimeError("HISTORY_DATABASE_URL is not set")
    return create_async_engine(url, pool_pre_ping=True)


@lru_cache
def get_history_session_factory() -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(get_history_engine(), class_=AsyncSession, expire_on_commit=False)


async def create_history_tables(engine: AsyncEngine | None = None) -> None:
    """Create the history tables if they are missing. Safe to repeat."""
    from app.history import models  # noqa: F401  (registers the tables)

    async with (engine or get_history_engine()).begin() as connection:
        await connection.run_sync(HistoryBase.metadata.create_all)


def resolve_history_factory(
    override: Callable[[], async_sessionmaker[AsyncSession]] | None = None,
) -> async_sessionmaker[AsyncSession] | None:
    """The history database's session factory, or None when history is off.
    `override` is for tests."""
    if override is not None:
        return override()
    return get_history_session_factory() if history_enabled() else None
