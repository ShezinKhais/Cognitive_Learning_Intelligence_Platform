"""Tests that need a real Postgres.

They skip when no database is reachable so the suite still runs on a machine
without Docker started. CI always has one, so these always execute there.

This is the pattern for anything touching the schema: take the `db` fixture,
and let it skip rather than fail when the database is absent.
"""

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.core.config import get_settings

REQUIRED_EXTENSIONS = {"vector", "pg_trgm", "uuid-ossp"}


@pytest.fixture
async def db():
    """A session on an engine built for this test only.

    The application engine is module-level and binds to whichever event loop
    first uses it. pytest-asyncio gives each test a fresh loop, so sharing it
    hands the second test a connection from a pool tied to a dead loop. NullPool
    and a per-test engine avoid that entirely.
    """
    engine = create_async_engine(get_settings().database_url, poolclass=NullPool)
    try:
        async with engine.connect() as conn:
            await conn.execute(text("select 1"))
    except Exception as exc:
        await engine.dispose()
        pytest.skip(f"no database reachable ({type(exc).__name__})")

    session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with session_factory() as session:
        yield session
        await session.rollback()

    await engine.dispose()


async def test_extensions_are_installed(db: AsyncSession) -> None:
    """A database without pgvector looks fine until the first embedding insert."""
    installed = (await db.execute(text("select extname from pg_extension"))).scalars().all()
    missing = REQUIRED_EXTENSIONS - set(installed)
    assert not missing, f"missing extensions: {sorted(missing)}"


async def test_vector_column_round_trips(db: AsyncSession) -> None:
    """Proves pgvector is usable, not merely present."""
    await db.execute(text("create temporary table _probe (id int primary key, v vector(3))"))
    await db.execute(text("insert into _probe values (1, '[1,2,3]')"))

    distance = (
        await db.execute(text("select v <-> '[1,2,4]' from _probe where id = 1"))
    ).scalar_one()

    assert distance == pytest.approx(1.0)


async def test_trigram_similarity_works(db: AsyncSession) -> None:
    """pg_trgm backs matching Teams display names against the admin roster."""
    score = (await db.execute(text("select similarity('Mike Chen', 'Michael Chen')"))).scalar_one()
    assert 0.0 < score < 1.0


async def test_readiness_passes_when_the_database_is_up(db: AsyncSession, client) -> None:
    """The 503 path is covered elsewhere; this covers the healthy one."""
    response = client.get("/api/v1/ready")
    assert response.status_code == 200

    body = response.json()
    postgres = next(d for d in body["dependencies"] if d["name"] == "postgres")
    assert postgres["ok"] is True
    assert postgres["latency_ms"] is not None
