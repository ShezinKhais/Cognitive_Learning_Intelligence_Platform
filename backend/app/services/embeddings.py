"""Turns content chunks into embedding vectors using Ollama.

Chunks go in, lists of numbers come out. The numbers are what make
similarity search possible later.

Chunks are sent in batches rather than one at a time, because one HTTP
call per chunk would mean hundreds of round trips for a single lecture.

Order matters: the pipeline pairs each vector back to its chunk by
position, so vectors must come back in the same order they went in.
"""

from collections.abc import Sequence

from app.services.extraction import ContentChunk

BATCH_SIZE = 32


class OllamaEmbeddingClient:
    """Adapts the OpenAI-compatible Ollama endpoint to a plain embed(texts) call."""

    def __init__(self, client, model: str):
        self._client = client
        self._model = model

    async def embed(self, texts: Sequence[str]) -> list[list[float]]:
        response = await self._client.embeddings.create(model=self._model, input=list(texts))
        # Sort by index rather than trusting array order: the response carries
        # its own ordering, and relying on it costs nothing.
        items = sorted(response.data, key=lambda d: d.index)
        return [item.embedding for item in items]


class OllamaEmbedder:
    def __init__(self, client, batch_size: int = BATCH_SIZE):
        self._client = client
        self._batch_size = batch_size

    async def embed(self, chunks: Sequence[ContentChunk]) -> Sequence[Sequence[float]]:
        vectors: list[Sequence[float]] = []
        for start in range(0, len(chunks), self._batch_size):
            batch = chunks[start : start + self._batch_size]
            texts = [c.chunk_text for c in batch]
            vectors.extend(await self._client.embed(texts))
        return vectors
