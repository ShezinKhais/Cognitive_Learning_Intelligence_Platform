"""The search text is embedded with the same model the chunks were embedded
with, otherwise the numbers aren't comparable.

Postgres does the sorting with the <=> operator, so the vectors never get
loaded into Python.
"""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.rag_chunk import RagChunk


@dataclass(frozen=True)
class RetrievedChunk:
    """A chunk that matched a search, with its page for citation."""

    chunk_id: UUID
    chunk_index: int
    chunk_text: str
    source_page: int | None
    distance: float


class ChunkRetriever:
    def __init__(self, session: AsyncSession, client, model: str) -> None:
        self._session = session
        self._client = client
        # Vectors from two models are not comparable. Without this filter a
        # query embedded with the new model would be scored against rows
        # embedded with the old one, and the nearest neighbours would be
        # arbitrary rather than wrong in any detectable way.
        self._model = model

    async def search(self, query: str, material_id: UUID, k: int = 5) -> list[RetrievedChunk]:
        vectors = await self._client.embed([query])
        query_vector = vectors[0]

        distance = RagChunk.embedding_vector.cosine_distance(query_vector)

        # Rows with no vector can never match; excluding them keeps them out
        # of the k results rather than filling slots with nulls.
        statement = (
            select(RagChunk, distance.label("distance"))
            .where(
                RagChunk.source_material_id == material_id,
                RagChunk.embedding_vector.isnot(None),
                RagChunk.embedding_model == self._model,
            )
            .order_by(distance)
            .limit(k)
        )

        result = await self._session.execute(statement)
        return [
            RetrievedChunk(
                chunk_id=row.RagChunk.chunk_id,
                chunk_index=row.RagChunk.chunk_index,
                chunk_text=row.RagChunk.chunk_text,
                source_page=row.RagChunk.source_page,
                distance=row.distance,
            )
            for row in result
        ]
