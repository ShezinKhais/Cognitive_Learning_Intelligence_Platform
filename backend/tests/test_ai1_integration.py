"""AI 1's real embedder and generator wired into the real MaterialPipeline.

The unit tests prove each piece in isolation. This proves they fit the seams
General CS defined: that an uploaded file reaches the store as chunks with
vectors and as validated draft questions, with only the model calls faked.
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from pathlib import Path
from uuid import uuid4

from app.core.config import Settings, get_settings
from app.realtime.hub import SessionHub
from app.services.embeddings import OllamaEmbedder
from app.services.generation import QuestionGenerator
from app.services.jobs import JobRegistry
from app.services.material_seams import CompletedMaterial
from app.services.pipeline import MaterialPipeline
from app.services.storage import LocalDiskStorage

LECTURE_TEXT = (
    "Normalisation removes redundancy from a relational schema. "
    "Each table should describe one kind of thing. " * 20
).encode()

DIM = get_settings().embedding_dim


async def feed(data: bytes) -> AsyncIterator[bytes]:
    yield data


class FakeEmbeddingClient:
    """Stands in for Ollama. Real shape, no server."""

    async def embed(self, texts):
        return [[0.1] * DIM for _ in texts]


class FakeChatClient:
    """Returns one question that should pass validation, and one that should not."""

    def __init__(self) -> None:
        self.chat = self

    @property
    def completions(self):
        return self

    async def create(self, model, messages):
        grounded = {
            "prompt": "What does normalisation remove?",
            "options": ["Redundancy", "Indexes", "Constraints", "Rows"],
            "correct_option": 0,
            "topic": "Normalisation",
            "source_slide": 1,
            "source_excerpt": "Normalisation removes redundancy from a relational schema",
        }
        invented = {
            "prompt": "Which optimiser converges fastest?",
            "options": ["Adam", "SGD", "RMSProp", "Adagrad"],
            "correct_option": 0,
            "topic": "Optimisers",
            "source_slide": 1,
            "source_excerpt": "Adam combines momentum with adaptive learning rates",
        }

        class M:
            content = json.dumps([grounded, invented])

        class C:
            message = M()

        class R:
            choices = [C()]

        return R()


class CapturingStore:
    """BBIS's seam. Records what the pipeline handed it."""

    def __init__(self) -> None:
        self.completed: CompletedMaterial | None = None
        self.failures: list = []

    async def record_completed(self, material: CompletedMaterial) -> None:
        self.completed = material

    async def record_failed(self, status) -> None:
        self.failures.append(status)


async def test_a_lecture_reaches_the_store_as_vectors_and_grounded_questions(
    tmp_path: Path,
) -> None:
    settings = Settings(upload_storage_dir=str(tmp_path))
    storage = LocalDiskStorage(settings)
    store = CapturingStore()

    pipeline = MaterialPipeline(
        storage=storage,
        registry=JobRegistry(),
        settings=settings,
        hub=SessionHub(),
        embedder=OllamaEmbedder(FakeEmbeddingClient(), "nomic-embed-text"),
        generator=QuestionGenerator(FakeChatClient(), "qwen2.5:3b"),
        store=store,
    )

    stored = await storage.save(uuid4(), "week3.txt", feed(LECTURE_TEXT))
    result = await pipeline.run(stored, uuid4())

    assert result is not None

    assert store.completed is not None
    batch = store.completed.embeddings
    assert batch is not None
    assert len(batch.vectors) == len(store.completed.result.chunks)
    assert batch.model == "nomic-embed-text"
    assert batch.dim == DIM

    # The invented question cites a real page but quotes text that is not in
    # the material, so only the grounded one survives.
    assert len(store.completed.questions) == 1
    assert store.completed.questions[0].topic == "Normalisation"
