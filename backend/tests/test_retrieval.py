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
                embedding_model="nomic-embed-text",
            )
        )
    await db.flush()

    retriever = ChunkRetriever(db, FixedVectorClient(axis_vector(0)), "nomic-embed-text")
    results = await retriever.search("anything", material.id, k=3)

    assert len(results) == 3
    assert results[0].chunk_text == "chunk on axis 0"
    assert results[0].source_page == 2


async def test_search_never_returns_another_materials_chunks(db: AsyncSession) -> None:
    """A lecturer's questions must not be grounded in someone else's upload."""
    mine = Material(
        id=uuid.uuid4(),
        filename="mine.pdf",
        content_type="application/pdf",
        size_bytes=1000,
    )
    theirs = Material(
        id=uuid.uuid4(),
        filename="theirs.pdf",
        content_type="application/pdf",
        size_bytes=1000,
    )
    db.add_all([mine, theirs])
    await db.flush()

    # My chunk is a poor match; theirs is a perfect one. If the filter were
    # missing, theirs would rank first — so a pass here can't be luck.
    db.add(
        RagChunk(
            chunk_id=uuid.uuid4(),
            source_material_id=mine.id,
            chunk_index=0,
            source_page=1,
            chunk_text="my distant chunk",
            embedding_vector=axis_vector(7),
            embedding_model="nomic-embed-text",
        )
    )
    db.add(
        RagChunk(
            chunk_id=uuid.uuid4(),
            source_material_id=theirs.id,
            chunk_index=0,
            source_page=1,
            chunk_text="their perfect match",
            embedding_vector=axis_vector(0),
            embedding_model="nomic-embed-text",
        )
    )
    await db.flush()

    retriever = ChunkRetriever(db, FixedVectorClient(axis_vector(0)), "nomic-embed-text")
    results = await retriever.search("anything", mine.id, k=5)

    assert [r.chunk_text for r in results] == ["my distant chunk"]


async def test_search_ignores_chunks_from_another_embedding_model(db: AsyncSession) -> None:
    """A model change leaves old vectors in place. Comparing across models
    gives neighbours that are arbitrary rather than detectably wrong."""
    material = Material(
        id=uuid.uuid4(),
        filename="lecture.pdf",
        content_type="application/pdf",
        size_bytes=1000,
    )
    db.add(material)
    await db.flush()

    # The old-model chunk is a perfect match, so it would rank first if the
    # filter were missing.
    db.add(
        RagChunk(
            chunk_id=uuid.uuid4(),
            source_material_id=material.id,
            chunk_index=0,
            source_page=1,
            chunk_text="old model chunk",
            embedding_vector=axis_vector(0),
            embedding_model="some-old-model",
        )
    )
    db.add(
        RagChunk(
            chunk_id=uuid.uuid4(),
            source_material_id=material.id,
            chunk_index=1,
            source_page=2,
            chunk_text="current model chunk",
            embedding_vector=axis_vector(7),
            embedding_model="nomic-embed-text",
        )
    )
    await db.flush()

    retriever = ChunkRetriever(db, FixedVectorClient(axis_vector(0)), "nomic-embed-text")
    results = await retriever.search("anything", material.id, k=5)

    assert [r.chunk_text for r in results] == ["current model chunk"]
