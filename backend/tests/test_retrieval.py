"""Retrieval tests. These need a real Postgres because the distance maths
happens in pgvector, not in Python — faking it would prove nothing."""

import uuid

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.core.config import get_settings
from app.models.material import Material
from app.models.rag_chunk import RagChunk
from app.services.retrieval import ChunkRetriever

DIM = get_settings().embedding_dim


def axis_vector(position: int) -> list[float]:
    """A vector pointing along one axis, so distances are predictable."""
    vector = [0.0] * DIM
    vector[position] = 1.0
    return vector


class FixedVectorClient:
    """Returns a vector we chose, so the expected winner is known up front."""

    def __init__(self, vector):
        self._vector = vector

    async def embed(self, texts):
        return [self._vector for _ in texts]


@pytest.fixture
async def db():
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


async def test_closest_chunk_comes_first(db: AsyncSession) -> None:
    material = Material(
        id=uuid.uuid4(),
        filename="lecture.pdf",
        content_type="application/pdf",
        size_bytes=1000,
    )
    db.add(material)
    await db.flush()

    for index, position in enumerate([5, 0, 9]):
        db.add(
            RagChunk(
                chunk_id=uuid.uuid4(),
                source_material_id=material.id,
                chunk_index=index,
                source_page=index + 1,
                chunk_text=f"chunk on axis {position}",
                embedding_vector=axis_vector(position),
            )
        )
    await db.flush()

    retriever = ChunkRetriever(db, FixedVectorClient(axis_vector(0)))
    results = await retriever.search("anything", material.id, k=3)

    assert len(results) == 3
    assert results[0].chunk_text == "chunk on axis 0"
    assert results[0].source_page == 2
