"""Stage orchestration for material processing.

Owner: General CS, Phase 2.

These run against real storage and the real extraction service, so what is
asserted is what a lecturer would actually see. The only stand-ins are the
three seams that belong to other workstreams, and each one is a handful of
lines that records what it was handed.
"""

from __future__ import annotations

import threading
from collections.abc import AsyncIterator, Sequence
from pathlib import Path
from uuid import UUID, uuid4

import pytest

from app.core.config import Settings
from app.realtime.hub import Connection, SessionHub
from app.schemas.content import MaterialStatus
from app.schemas.events import MaterialProgressPayload, MaterialStage, ServerEventType
from app.services.extraction import ContentChunk, ProcessingResult
from app.services.jobs import JobRegistry, JobStatus
from app.services.pipeline import MaterialPipeline
from app.services.storage import LocalDiskStorage, StoredFile

SAMPLES = Path(__file__).resolve().parent / "samples"

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

    def __init__(self, per_chunk: int = 1) -> None:
        self.per_chunk = per_chunk
        self.seen: list[ContentChunk] = []

    async def embed(self, chunks: Sequence[ContentChunk]) -> list[list[float]]:
        self.seen = list(chunks)
        return [[0.0, 1.0] for _ in range(len(chunks) * self.per_chunk)]


class Generator:
    """Seam owned by AI 1."""

    def __init__(self, count: int = 3) -> None:
        self.count = count
        self.called = False

    async def generate(self, material_id: UUID, chunks: Sequence[ContentChunk]) -> int:
        self.called = True
        return self.count


class Store:
    """Seam owned by BBIS."""

    def __init__(self) -> None:
        self.saved: list[ProcessingResult] = []
        self.outcomes: list[JobStatus] = []

    async def save_chunks(self, result: ProcessingResult, embeddings: Sequence) -> None:
        self.saved.append(result)

    async def record_outcome(
        self,
        status: JobStatus,
        page_count: int | None = None,
        chunk_count: int | None = None,
    ) -> None:
        self.outcomes.append(status)


def settings_for(tmp_path: Path) -> Settings:
    return Settings(upload_storage_dir=str(tmp_path))


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


async def test_a_lecture_file_runs_through_every_stage(tmp_path: Path) -> None:
    hub = SessionHub()
    owner = uuid4()
    socket = await watching(hub, owner)
    pipeline, storage, registry = build(
        tmp_path,
        hub=hub,
        embedder=Embedder(),
        generator=Generator(count=4),
        store=Store(),
    )
    stored = await storage.save(uuid4(), "Week 3.pdf", feed(read(SAMPLES / "lecture.pdf")))

    result = await pipeline.run(stored, owner)

    assert result is not None
    assert result.chunk_count > 0
    assert result.question_count == 4
    assert stages(socket) == [
        MaterialStage.VALIDATING,
        MaterialStage.EXTRACTING,
        MaterialStage.CHUNKING,
        MaterialStage.EMBEDDING,
        MaterialStage.GENERATING,
        MaterialStage.DONE,
    ]
    assert registry.get(stored.material_id).status is MaterialStatus.COMPLETED


async def test_progress_never_goes_backwards_and_finishes_at_one_hundred(
    tmp_path: Path,
) -> None:
    """A bar that jumps back reads as a bug even when nothing is wrong."""
    hub = SessionHub()
    owner = uuid4()
    socket = await watching(hub, owner)
    pipeline, storage, _ = build(
        tmp_path, hub=hub, embedder=Embedder(), generator=Generator(), store=Store()
    )

    await pipeline.run(await stored_text(storage), owner)

    percents = [frame["data"]["percent"] for frame in socket.sent]
    assert percents == sorted(percents)
    assert percents[-1] == 100


async def test_every_frame_matches_the_frozen_event_contract(tmp_path: Path) -> None:
    """The payload is what a client parses, so it is validated, not eyeballed."""
    hub = SessionHub()
    owner = uuid4()
    socket = await watching(hub, owner)
    pipeline, storage, _ = build(tmp_path, hub=hub)

    await pipeline.run(await stored_text(storage), owner)

    assert socket.sent
    for frame in socket.sent:
        assert frame["type"] == ServerEventType.MATERIAL_PROGRESS
        MaterialProgressPayload.model_validate(frame["data"])

    seqs = [frame["seq"] for frame in socket.sent]
    assert seqs == list(range(1, len(seqs) + 1))


async def test_progress_reaches_a_lecturer_who_is_in_no_session(tmp_path: Path) -> None:
    """Uploading happens while preparing, so there is no class to broadcast to."""
    hub = SessionHub()
    owner = uuid4()
    socket = await watching(hub, owner)
    pipeline, storage, _ = build(tmp_path, hub=hub)

    await pipeline.run(await stored_text(storage), owner)

    assert socket.sent
    assert all(frame["data"]["material_id"] for frame in socket.sent)


async def test_another_lecturer_is_not_told_about_this_upload(tmp_path: Path) -> None:
    hub = SessionHub()
    owner = uuid4()
    mine = await watching(hub, owner)
    theirs = await watching(hub, uuid4())
    pipeline, storage, _ = build(tmp_path, hub=hub)

    await pipeline.run(await stored_text(storage), owner)

    assert mine.sent
    assert theirs.sent == []


async def test_a_closed_tab_does_not_stop_the_work(tmp_path: Path) -> None:
    """Nobody is listening, so the events go nowhere and the parse continues."""
    pipeline, storage, registry = build(tmp_path)
    stored = await stored_text(storage)

    result = await pipeline.run(stored, uuid4())

    assert result is not None
    assert registry.get(stored.material_id).status is MaterialStatus.COMPLETED


async def test_an_unreadable_file_is_reported_rather_than_raised(tmp_path: Path) -> None:
    """A bad upload is an answer for the lecturer, not a crash for the log."""
    hub = SessionHub()
    owner = uuid4()
    socket = await watching(hub, owner)
    pipeline, storage, registry = build(tmp_path, hub=hub)
    stored = await storage.save(uuid4(), "broken.pdf", feed(b"this is not a PDF at all"))

    result = await pipeline.run(stored, owner)

    assert result is None
    status = registry.get(stored.material_id)
    assert status.stage is MaterialStage.FAILED
    assert status.status is MaterialStatus.FAILED
    assert status.is_finished
    assert stages(socket)[-1] == MaterialStage.FAILED


async def test_the_failure_message_says_what_was_wrong_with_the_file(tmp_path: Path) -> None:
    """ "Processing failed" sends the lecturer to us; naming the fault does not."""
    pipeline, storage, registry = build(tmp_path)
    stored = await storage.save(uuid4(), "blank.txt", feed(b"   \n  \n"))

    await pipeline.run(stored, uuid4())

    assert "No readable text" in registry.get(stored.material_id).message


async def test_an_unreadable_file_is_not_left_on_disk(tmp_path: Path) -> None:
    """No retry can use it, so keeping it is disk spent on nothing."""
    pipeline, storage, _ = build(tmp_path)
    stored = await storage.save(uuid4(), "broken.pdf", feed(b"this is not a PDF at all"))

    await pipeline.run(stored, uuid4())

    assert not exists(stored.key)


async def test_a_failure_that_may_be_transient_keeps_the_file(tmp_path: Path) -> None:
    """The embedding model being down is not a reason to make the lecturer
    upload the deck again."""
    pipeline, storage, registry = build(tmp_path, embedder=Embedder(per_chunk=2))
    stored = await stored_text(storage)

    with pytest.raises(RuntimeError):
        await pipeline.run(stored, uuid4())

    assert exists(stored.key)
    assert registry.get(stored.material_id).stage is MaterialStage.FAILED


async def test_a_miscounting_embedder_is_refused_rather_than_zipped(tmp_path: Path) -> None:
    """zip would pair chunks with the wrong vectors, and retrieval would then
    return the wrong slide with full confidence."""
    pipeline, storage, _ = build(tmp_path, embedder=Embedder(per_chunk=2), store=Store())
    stored = await stored_text(storage)

    with pytest.raises(RuntimeError, match="vectors for"):
        await pipeline.run(stored, uuid4())


async def test_a_stage_that_is_not_wired_up_is_not_announced(tmp_path: Path) -> None:
    """Showing an embedding step that never ran would be a lie to the lecturer."""
    hub = SessionHub()
    owner = uuid4()
    socket = await watching(hub, owner)
    pipeline, storage, _ = build(tmp_path, hub=hub)

    result = await pipeline.run(await stored_text(storage), owner)

    assert MaterialStage.EMBEDDING not in stages(socket)
    assert MaterialStage.GENERATING not in stages(socket)
    assert stages(socket)[-1] == MaterialStage.DONE
    assert any("embedding is not wired up" in w for w in result.warnings)


async def test_the_store_is_written_once_at_the_end_not_once_per_stage(tmp_path: Path) -> None:
    """Six row updates per upload to record what the socket already delivered."""
    store = Store()
    pipeline, storage, _ = build(tmp_path, embedder=Embedder(), generator=Generator(), store=store)

    await pipeline.run(await stored_text(storage), uuid4())

    assert len(store.outcomes) == 1
    assert store.outcomes[0].stage is MaterialStage.DONE
    assert len(store.saved) == 1


async def test_a_failed_material_is_recorded_in_the_store_too(tmp_path: Path) -> None:
    """The registry is memory only, so a restart would forget the failure."""
    store = Store()
    pipeline, storage, _ = build(tmp_path, store=store)
    stored = await storage.save(uuid4(), "broken.pdf", feed(b"not a PDF"))

    await pipeline.run(stored, uuid4())

    assert [outcome.stage for outcome in store.outcomes] == [MaterialStage.FAILED]


async def test_a_store_that_is_down_does_not_replace_the_real_error(tmp_path: Path) -> None:
    class Broken(Store):
        async def record_outcome(self, status, page_count=None, chunk_count=None) -> None:
            raise ConnectionError("database is gone")

    pipeline, storage, registry = build(tmp_path, store=Broken())
    stored = await storage.save(uuid4(), "broken.pdf", feed(b"not a PDF"))

    result = await pipeline.run(stored, uuid4())

    assert result is None
    assert "could not be read" in registry.get(stored.material_id).message


async def test_extraction_does_not_run_on_the_event_loop(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Fifteen seconds of parsing inline would freeze every live session on the
    process, which is the failure the 202 exists to avoid."""
    loop_thread = threading.get_ident()
    ran_on: list[int] = []

    def record(path: str, material_id: UUID, max_bytes: int) -> ProcessingResult:
        ran_on.append(threading.get_ident())
        return ProcessingResult(material_id=material_id, parser_used="stub")

    monkeypatch.setattr("app.services.pipeline.process_material", record)
    pipeline, storage, _ = build(tmp_path)

    await pipeline.run(await stored_text(storage), uuid4())

    assert ran_on and ran_on[0] != loop_thread
