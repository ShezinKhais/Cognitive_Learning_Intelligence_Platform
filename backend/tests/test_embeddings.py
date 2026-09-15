"""Tests for the embedding service."""

import uuid

import pytest

from app.services.embeddings import OllamaEmbedder
from app.services.extraction import ContentChunk


class FakeEmbeddingClient:
    """Stands in for Ollama so tests run without a server."""

    def __init__(self):
        self.calls = []

    async def embed(self, texts):
        self.calls.append(texts)
        return [[float(len(t))] * 768 for t in texts]


def make_chunks(n):
    material_id = uuid.uuid4()
    return [
        ContentChunk(
            chunk_id=uuid.uuid4(),
            chunk_index=i,
            material_id=material_id,
            chunk_text=f"chunk number {i}",
            source_page=1,
        )
        for i in range(n)
    ]


async def test_batches_instead_of_one_call_per_chunk():
    client = FakeEmbeddingClient()
    embedder = OllamaEmbedder(client, batch_size=32)

    vectors = await embedder.embed(make_chunks(70))

    assert len(vectors) == 70
    assert len(client.calls) == 3


class WrongSizeClient:
    async def embed(self, texts):
        return [[0.1] * 1536 for _ in texts]


async def test_rejects_vectors_of_the_wrong_dimension():
    embedder = OllamaEmbedder(WrongSizeClient(), batch_size=32)

    with pytest.raises(ValueError):
        await embedder.embed(make_chunks(3))


async def test_no_chunks_means_no_calls():
    client = FakeEmbeddingClient()
    embedder = OllamaEmbedder(client, batch_size=32)

    vectors = await embedder.embed([])

    assert vectors == []
    assert client.calls == []
