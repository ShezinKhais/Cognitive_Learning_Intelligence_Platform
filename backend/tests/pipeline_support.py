"""Fakes and builders shared by the material pipeline tests.

The only stand-ins are the three seams that belong to other workstreams, and
each one is a handful of lines that records what it was handed. Storage and
extraction are real, so what the tests assert is what a lecturer would see.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Sequence
from pathlib import Path
from uuid import UUID, uuid4

from app.core.config import Settings
from app.realtime.hub import Connection, SessionHub
from app.schemas.content import Difficulty, QuestionType
from app.services.extraction import ContentChunk
from app.services.jobs import JobRegistry, JobStatus
from app.services.material_seams import CompletedMaterial, DraftQuestion, EmbeddingBatch
from app.services.pipeline import MaterialPipeline
from app.services.storage import LocalDiskStorage, StoredFile

SAMPLES = Path(__file__).resolve().parent / "samples"

EVENT_TIMEOUT_SECONDS = 5.0

# Small, so the fake embedder does not build 768 floats per chunk.
TEST_EMBEDDING_DIM = 8

# Long enough to chunk into more than one piece, so an off-by-one in the
# embedding guard has something to catch.
LECTURE_TEXT = ("Normalisation removes redundancy from a relational schema. " * 40).encode()


def read(path_like: str | Path) -> bytes:
    return Path(path_like).read_bytes()


def exists(path_like: str | Path) -> bool:
    return Path(path_like).is_file()


async def feed(data: bytes) -> AsyncIterator[bytes]:
    yield data


class Socket:
    """Stands in for a connected client. Records what was sent to it."""

    def __init__(self) -> None:
        self.sent: list[dict] = []

    async def send_json(self, payload: dict) -> None:
        self.sent.append(payload)


class Embedder:
    """Seam owned by AI 1. Returns one vector per chunk, or a wrong count."""

    def __init__(self, per_chunk: int = 1, dim: int = TEST_EMBEDDING_DIM) -> None:
        self.per_chunk = per_chunk
        self.dim = dim
        self.seen: list[ContentChunk] = []

    async def embed(self, chunks: Sequence[ContentChunk]) -> EmbeddingBatch:
        self.seen = list(chunks)
        vectors = [[0.0] * self.dim for _ in range(len(chunks) * self.per_chunk)]
        return EmbeddingBatch(vectors=vectors, model="test-embed", dim=self.dim)


def mcq(prompt: str = "Which layer routes packets?") -> DraftQuestion:
    return DraftQuestion(
        type=QuestionType.MCQ,
        difficulty=Difficulty.MEDIUM,
        prompt=prompt,
        options=("Transport", "Network"),
        correct_option=1,
        source_slide=1,
    )


class Generator:
    """Seam owned by AI 1."""

    def __init__(self, count: int = 3, drafts: Sequence[DraftQuestion] | None = None) -> None:
        self.drafts = list(drafts) if drafts is not None else [mcq() for _ in range(count)]
        self.called = False

    async def generate(
        self, material_id: UUID, chunks: Sequence[ContentChunk]
    ) -> list[DraftQuestion]:
        self.called = True
        return self.drafts


class Store:
    """Seam owned by BBIS. Records what it was handed."""

    def __init__(self) -> None:
        self.completed: list[CompletedMaterial] = []
        self.outcomes: list[JobStatus] = []

    async def record_completed(self, material: CompletedMaterial) -> None:
        self.completed.append(material)
        self.outcomes.append(material.status)

    async def record_failed(self, status: JobStatus) -> None:
        self.outcomes.append(status)


def settings_for(tmp_path: Path) -> Settings:
    return Settings(
        _env_file=None, upload_storage_dir=str(tmp_path), embedding_dim=TEST_EMBEDDING_DIM
    )


def build(
    tmp_path: Path,
    hub: SessionHub | None = None,
    registry: JobRegistry | None = None,
    **seams,
) -> tuple[MaterialPipeline, LocalDiskStorage, JobRegistry]:
    settings = settings_for(tmp_path)
    storage = LocalDiskStorage(settings)
    registry = registry if registry is not None else JobRegistry()
    pipeline = MaterialPipeline(
        storage=storage,
        registry=registry,
        settings=settings,
        hub=hub if hub is not None else SessionHub(),
        **seams,
    )
    return pipeline, storage, registry


def stages(socket: Socket) -> list[str]:
    return [frame["data"]["stage"] for frame in socket.sent]


async def watching(hub: SessionHub, user_id: UUID) -> Socket:
    """A lecturer with the upload page open, and no class in progress."""
    socket = Socket()
    await hub.join(Connection(socket, user_id, None))
    return socket


async def stored_text(storage: LocalDiskStorage, name: str = "notes.txt") -> StoredFile:
    return await storage.save(uuid4(), name, feed(LECTURE_TEXT))
