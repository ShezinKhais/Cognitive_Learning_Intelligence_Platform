"""Stage orchestration for material processing.

Owner: General CS, Phase 2.

These run against real storage and the real extraction service, so what is
asserted is what a lecturer would actually see. The only stand-ins are the
three seams that belong to other workstreams, and each one is a handful of
lines that records what it was handed.
"""

from __future__ import annotations

import asyncio
import contextlib
import contextvars
import threading
import time
from collections.abc import AsyncIterator, Sequence
from pathlib import Path
from uuid import UUID, uuid4

import pytest

from app.core.config import Settings
from app.realtime.hub import Connection, SessionHub
from app.schemas.content import Difficulty, MaterialStatus, QuestionType
from app.schemas.events import MaterialProgressPayload, MaterialStage, ServerEventType
from app.services.extraction import ContentChunk, ProcessingResult
from app.services.jobs import (
    INTERNAL_ERROR,
    INTERRUPTED_ERROR,
    INTERRUPTED_MESSAGE,
    BackgroundProcessor,
    JobRegistry,
    JobStatus,
)
from app.services.pipeline import (
    DraftQuestion,
    EmbeddingBatch,
    MaterialPipeline,
    run_in_daemon_thread,
)
from app.services.storage import LocalDiskStorage, StoredFile

SAMPLES = Path(__file__).resolve().parent / "samples"

EVENT_TIMEOUT_SECONDS = 5.0

# Small, so the fake embedder does not build 768 floats per chunk.
TEST_EMBEDDING_DIM = 8

# Long enough to chunk into more than one piece, so an off-by-one in the
# embedding guard has something to catch.
REQUEST: contextvars.ContextVar[str] = contextvars.ContextVar("request", default="none")

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
    """Seam owned by BBIS."""

    def __init__(self) -> None:
        self.saved: list[ProcessingResult] = []
        self.embeddings: list[EmbeddingBatch | None] = []
        self.questions: list[DraftQuestion] = []
        self.outcomes: list[JobStatus] = []

    async def save_chunks(
        self, result: ProcessingResult, embeddings: EmbeddingBatch | None
    ) -> None:
        self.saved.append(result)
        self.embeddings.append(embeddings)

    async def save_questions(self, material_id: UUID, questions: Sequence[DraftQuestion]) -> None:
        self.questions.extend(questions)

    async def record_outcome(
        self,
        status: JobStatus,
        page_count: int | None = None,
        chunk_count: int | None = None,
        warnings: Sequence[str] = (),
    ) -> None:
        self.outcomes.append(status)
        self.warnings = list(warnings)


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
    stored = await stored_text(storage)

    await pipeline.run(stored, owner)

    assert socket.sent
    stored_id = str(stored.material_id)
    assert all(frame["data"]["material_id"] == stored_id for frame in socket.sent)


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
    for seam in ("embedding", "question generation", "persistence"):
        assert any(f"{seam} is not wired up" in w for w in result.warnings)


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
        async def record_outcome(
            self, status, page_count=None, chunk_count=None, warnings=()
        ) -> None:
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
    thread: list[threading.Thread] = []
    seen_request: list[str] = []
    REQUEST.set("upload-42")

    def record(path: str, material_id: UUID, max_bytes: int) -> ProcessingResult:
        ran_on.append(threading.get_ident())
        thread.append(threading.current_thread())
        seen_request.append(REQUEST.get())
        return ProcessingResult(material_id=material_id, parser_used="stub")

    monkeypatch.setattr("app.services.pipeline.process_material", record)
    pipeline, storage, _ = build(tmp_path)

    await pipeline.run(await stored_text(storage), uuid4())

    assert ran_on and ran_on[0] != loop_thread
    # The daemon runner, not asyncio.to_thread, whose thread holds shutdown open.
    assert thread[0].name == "material-extraction"
    assert thread[0].daemon
    # Log lines from inside the parse keep the upload's request id.
    assert seen_request == ["upload-42"]


async def test_success_is_not_announced_until_it_is_recorded(tmp_path: Path) -> None:
    """Announcing first sent the lecturer "done" and then "failed" when the
    database write that should have preceded it went wrong."""

    class RefusesToRecordSuccess(Store):
        async def record_outcome(
            self, status, page_count=None, chunk_count=None, warnings=()
        ) -> None:
            if status.stage is MaterialStage.DONE:
                raise ConnectionError("database is gone")
            await super().record_outcome(status, page_count, chunk_count, warnings)

    hub = SessionHub()
    owner = uuid4()
    socket = await watching(hub, owner)
    pipeline, storage, registry = build(tmp_path, hub=hub, store=RefusesToRecordSuccess())
    stored = await stored_text(storage)

    with pytest.raises(ConnectionError):
        await pipeline.run(stored, owner)

    assert MaterialStage.DONE not in stages(socket)
    assert stages(socket)[-1] == MaterialStage.FAILED
    assert registry.get(stored.material_id).stage is MaterialStage.FAILED


async def test_an_upload_interrupted_by_shutdown_is_reported_and_recorded(
    tmp_path: Path,
) -> None:
    """Without this the process exits with the lecturer still watching the
    bar move and the database still saying the material is processing."""

    class SlowStore(Store):
        def __init__(self) -> None:
            super().__init__()
            self.writing = asyncio.Event()

        async def save_chunks(self, result, embeddings) -> None:
            self.writing.set()
            await asyncio.sleep(3600)

    hub = SessionHub()
    owner = uuid4()
    socket = await watching(hub, owner)
    store = SlowStore()
    pipeline, storage, registry = build(tmp_path, hub=hub, store=store)
    processor = BackgroundProcessor(registry, max_concurrent=1)
    stored = await stored_text(storage)

    async def work() -> None:
        await pipeline.run(stored, owner)

    async def interrupted() -> None:
        await pipeline.abandon(stored.material_id, owner)

    processor.submit(stored.material_id, work, on_cancel=interrupted)
    # Stopped partway through, mid database write, rather than before it began.
    await asyncio.wait_for(store.writing.wait(), EVENT_TIMEOUT_SECONDS)

    await processor.drain(grace_seconds=0.01)

    assert stages(socket)[-1] == MaterialStage.FAILED
    assert socket.sent[-1]["data"]["message"] == INTERRUPTED_MESSAGE
    assert [outcome.stage for outcome in store.outcomes] == [MaterialStage.FAILED]
    assert store.outcomes[0].error == INTERRUPTED_ERROR
    # Nothing was wrong with the file, so it survives for a retry.
    assert exists(stored.key)


def test_shutdown_does_not_wait_for_a_parse_it_has_abandoned() -> None:
    """Cancelling cannot stop a thread. With the default executor the process
    then waited for the whole parse before it could exit, for a result it had
    already discarded."""

    def slow_parse() -> str:
        time.sleep(2)
        return "too late"

    async def deploy() -> None:
        parse = asyncio.create_task(run_in_daemon_thread(slow_parse))
        await asyncio.sleep(0.05)
        parse.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await parse

    started = time.monotonic()
    asyncio.run(deploy())

    assert time.monotonic() - started < 1.0


async def test_daemon_thread_returns_results_and_raises_errors_unchanged() -> None:
    """A bad document has to arrive as the ValidationError the pipeline treats
    as the lecturer's problem, not as something wrapped or swallowed."""

    def parses() -> int:
        return 42

    def rejects() -> None:
        raise ValueError("not a real document")

    assert await run_in_daemon_thread(parses) == 42
    with pytest.raises(ValueError, match="not a real document"):
        await run_in_daemon_thread(rejects)


async def test_the_store_is_told_which_model_embedded_the_chunks(tmp_path: Path) -> None:
    """rag_chunk.embedding_model is how retrieval tells old vectors from new
    ones after a model change. Taken from settings it would mislabel them."""
    store = Store()
    pipeline, storage, _ = build(tmp_path, embedder=Embedder(), store=store)

    await pipeline.run(await stored_text(storage), uuid4())

    assert store.embeddings[0] is not None
    assert store.embeddings[0].model == "test-embed"


async def test_chunks_are_still_stored_when_no_embedder_is_wired_up(tmp_path: Path) -> None:
    store = Store()
    pipeline, storage, _ = build(tmp_path, store=store)

    await pipeline.run(await stored_text(storage), uuid4())

    assert len(store.saved) == 1
    assert store.embeddings == [None]


async def test_vectors_of_the_wrong_width_are_refused_before_the_insert(tmp_path: Path) -> None:
    """The column is sized from settings. A model with another width would
    otherwise fail inside pgvector with an error naming neither."""
    store = Store()
    pipeline, storage, _ = build(
        tmp_path, embedder=Embedder(dim=TEST_EMBEDDING_DIM + 1), store=store
    )

    with pytest.raises(RuntimeError, match="test-embed"):
        await pipeline.run(await stored_text(storage), uuid4())

    assert store.saved == []


async def test_generated_questions_reach_the_store(tmp_path: Path) -> None:
    store = Store()
    drafts = [mcq("First?"), mcq("Second?")]
    pipeline, storage, _ = build(tmp_path, generator=Generator(drafts=drafts), store=store)

    result = await pipeline.run(await stored_text(storage), uuid4())

    assert result.question_count == 2
    assert [q.prompt for q in store.questions] == ["First?", "Second?"]


async def test_questions_are_stored_before_success_is_recorded(tmp_path: Path) -> None:
    order: list[str] = []

    class Ordered(Store):
        async def save_questions(self, material_id, questions) -> None:
            order.append("questions")

        async def record_outcome(
            self, status, page_count=None, chunk_count=None, warnings=()
        ) -> None:
            order.append(status.stage)

    pipeline, storage, _ = build(tmp_path, generator=Generator(), store=Ordered())

    await pipeline.run(await stored_text(storage), uuid4())

    assert order == ["questions", MaterialStage.DONE]


async def test_a_malformed_draft_is_dropped_and_the_rest_are_kept(tmp_path: Path) -> None:
    """An answer key past the end of the options marks every student wrong."""
    store = Store()
    broken = DraftQuestion(
        type=QuestionType.MCQ,
        difficulty=Difficulty.EASY,
        prompt="Which is it?",
        options=("A", "B"),
        correct_option=7,
    )
    pipeline, storage, _ = build(
        tmp_path, generator=Generator(drafts=[mcq(), broken, mcq("Third?")]), store=store
    )

    result = await pipeline.run(await stored_text(storage), uuid4())

    assert result.question_count == 2
    assert broken not in store.questions
    assert any("answer key" in w for w in result.warnings)


@pytest.mark.parametrize(
    ("draft", "problem"),
    [
        (DraftQuestion(QuestionType.MCQ, Difficulty.EASY, "   ", ("A", "B"), 0), "no prompt"),
        (DraftQuestion(QuestionType.MCQ, Difficulty.EASY, "Q?", ("A",), 0), "fewer than two"),
        (DraftQuestion(QuestionType.MCQ, Difficulty.EASY, "Q?", ("A", "B"), -1), "answer key"),
        (DraftQuestion(QuestionType.MCQ, Difficulty.EASY, "Q?", ("A", "B"), None), "answer key"),
        (DraftQuestion(QuestionType.FREE_TEXT, Difficulty.EASY, "Q?", (), 0), "free text"),
        (DraftQuestion(QuestionType.FREE_TEXT, Difficulty.EASY, "Explain."), None),
    ],
)
def test_draft_problems(draft: DraftQuestion, problem: str | None) -> None:
    found = draft.problem()
    if problem is None:
        assert found is None
    else:
        assert found is not None and problem in found


async def test_shutdown_during_a_failure_write_keeps_the_real_failure(tmp_path: Path) -> None:
    """The registry shows a failure as soon as it is announced, so shutdown
    used to skip the job, and the database never learned it had failed."""

    class SlowToRecord(Store):
        def __init__(self) -> None:
            super().__init__()
            self.writing = asyncio.Event()

        async def record_outcome(self, status, page_count=None, chunk_count=None, warnings=()):
            self.writing.set()
            await asyncio.sleep(0.05)
            await super().record_outcome(status, page_count, chunk_count, warnings)

    store = SlowToRecord()
    pipeline, storage, registry = build(tmp_path, embedder=Embedder(per_chunk=2), store=store)
    processor = BackgroundProcessor(registry, max_concurrent=1)
    stored = await stored_text(storage)
    owner = uuid4()

    async def work() -> None:
        await pipeline.run(stored, owner)

    async def interrupted() -> None:
        await pipeline.abandon(stored.material_id, owner)

    processor.submit(stored.material_id, work, on_cancel=interrupted)
    await asyncio.wait_for(store.writing.wait(), EVENT_TIMEOUT_SECONDS)
    await processor.drain(grace_seconds=0.0)

    assert [outcome.error for outcome in store.outcomes] == [INTERNAL_ERROR]


async def test_shutdown_after_a_failure_is_announced_still_records_it(tmp_path: Path) -> None:
    """Cancelled while telling the lecturer, before the write had started."""

    class HangsOnFailure(Socket):
        def __init__(self) -> None:
            super().__init__()
            self.failing = asyncio.Event()

        async def send_json(self, payload: dict) -> None:
            if payload["data"]["stage"] == MaterialStage.FAILED:
                self.failing.set()
                await asyncio.sleep(3600)
            await super().send_json(payload)

    hub = SessionHub()
    owner = uuid4()
    socket = HangsOnFailure()
    await hub.join(Connection(socket, owner, None))
    store = Store()
    pipeline, storage, registry = build(
        tmp_path, hub=hub, embedder=Embedder(per_chunk=2), store=store
    )
    processor = BackgroundProcessor(registry, max_concurrent=1)
    stored = await stored_text(storage)

    async def work() -> None:
        await pipeline.run(stored, owner)

    async def interrupted() -> None:
        await pipeline.abandon(stored.material_id, owner)

    processor.submit(stored.material_id, work, on_cancel=interrupted)
    await asyncio.wait_for(socket.failing.wait(), EVENT_TIMEOUT_SECONDS)
    await processor.drain(grace_seconds=0.0)

    assert [outcome.error for outcome in store.outcomes] == [INTERNAL_ERROR]


async def test_shutdown_during_the_success_write_does_not_overwrite_it(tmp_path: Path) -> None:
    """The database committed, the driver had not returned, and shutdown then
    marked a material whose chunks and questions were stored as failed."""

    class CommitsThenStalls(Store):
        def __init__(self) -> None:
            super().__init__()
            self.committed = asyncio.Event()

        async def record_outcome(self, status, page_count=None, chunk_count=None, warnings=()):
            await super().record_outcome(status, page_count, chunk_count, warnings)
            self.committed.set()
            await asyncio.sleep(0.05)

    hub = SessionHub()
    owner = uuid4()
    socket = await watching(hub, owner)
    store = CommitsThenStalls()
    pipeline, storage, registry = build(tmp_path, hub=hub, store=store)
    processor = BackgroundProcessor(registry, max_concurrent=1)
    stored = await stored_text(storage)

    async def work() -> None:
        await pipeline.run(stored, owner)

    async def interrupted() -> None:
        await pipeline.abandon(stored.material_id, owner)

    processor.submit(stored.material_id, work, on_cancel=interrupted)
    await asyncio.wait_for(store.committed.wait(), EVENT_TIMEOUT_SECONDS)
    await processor.drain(grace_seconds=0.0)

    assert [outcome.stage for outcome in store.outcomes] == [MaterialStage.DONE]
    assert stages(socket)[-1] == MaterialStage.DONE
    assert registry.get(stored.material_id).stage is MaterialStage.DONE


async def test_only_lecturer_warnings_reach_the_store(tmp_path: Path) -> None:
    """Build notes about unwired seams are for the log, not a lecturer."""
    store = Store()
    broken = DraftQuestion(QuestionType.MCQ, Difficulty.EASY, "Q?", ("A", "B"), 5)
    pipeline, storage, _ = build(tmp_path, generator=Generator(drafts=[broken]), store=store)

    result = await pipeline.run(await stored_text(storage), uuid4())

    assert any("answer key" in w for w in store.warnings)
    assert not any("not wired up" in w for w in store.warnings)
    assert any("not wired up" in w for w in result.warnings)


async def test_an_unexpected_failure_is_recorded_as_a_code(tmp_path: Path) -> None:
    store = Store()
    pipeline, storage, _ = build(tmp_path, embedder=Embedder(per_chunk=2), store=store)

    with pytest.raises(RuntimeError):
        await pipeline.run(await stored_text(storage), uuid4())

    assert store.outcomes[0].error == INTERNAL_ERROR


def test_a_draft_built_from_model_json_is_not_mistaken_for_free_text() -> None:
    """A generator parsing JSON passes "mcq", not QuestionType.MCQ."""
    draft = DraftQuestion("mcq", "easy", "Which?", ["A", "B"], 0)

    assert draft.type is QuestionType.MCQ
    assert draft.options == ("A", "B")
    assert draft.problem() is None


@pytest.mark.parametrize(
    ("draft", "problem"),
    [
        (DraftQuestion(QuestionType.MCQ, Difficulty.EASY, "Q?", ("A", "B"), True), "answer key"),
        (DraftQuestion(QuestionType.MCQ, Difficulty.EASY, "Q?", ("A", " "), 0), "blank option"),
        (DraftQuestion(QuestionType.MCQ, Difficulty.EASY, "Q?", ("A", "A"), 0), "repeats"),
        (DraftQuestion(QuestionType.MCQ, Difficulty.EASY, None, ("A", "B"), 0), "no prompt"),
        (
            DraftQuestion(QuestionType.FREE_TEXT, Difficulty.EASY, "Explain.", source_slide=0),
            "slide",
        ),
    ],
)
def test_more_draft_problems(draft: DraftQuestion, problem: str) -> None:
    found = draft.problem()
    assert found is not None and problem in found


async def test_a_draft_that_breaks_the_check_is_dropped_not_fatal(tmp_path: Path) -> None:
    store = Store()
    # A slide number that arrived as text makes the range check raise.
    odd = DraftQuestion(QuestionType.MCQ, Difficulty.EASY, "Q?", ("A", "B"), 0, source_slide="3")
    pipeline, storage, _ = build(
        tmp_path, generator=Generator(drafts=[odd, mcq("Kept?")]), store=store
    )

    result = await pipeline.run(await stored_text(storage), uuid4())

    assert result is not None
    assert [q.prompt for q in store.questions] == ["Kept?"]
    assert any("could not be checked" in w for w in result.warnings)


@pytest.mark.parametrize(
    "draft",
    [
        DraftQuestion(QuestionType.FREE_TEXT, Difficulty.EASY, "Explain.", options=()),
        DraftQuestion(QuestionType.FREE_TEXT, Difficulty.EASY, "Explain.", correct_option=0),
    ],
)
def test_free_text_with_either_multiple_choice_field_is_refused(draft: DraftQuestion) -> None:
    assert "free text" in (draft.problem() or "")


async def test_too_few_vectors_are_refused_as_well_as_too_many(tmp_path: Path) -> None:
    pipeline, storage, _ = build(tmp_path, embedder=Embedder(per_chunk=0), store=Store())

    with pytest.raises(RuntimeError, match="vectors for"):
        await pipeline.run(await stored_text(storage), uuid4())


async def test_vectors_narrower_than_the_declared_width_are_refused(tmp_path: Path) -> None:
    """A batch can declare the right width and still carry the wrong vectors."""

    class Misdeclares:
        async def embed(self, chunks):
            return EmbeddingBatch(
                vectors=[[0.0] * 3 for _ in chunks], model="test-embed", dim=TEST_EMBEDDING_DIM
            )

    store = Store()
    pipeline, storage, _ = build(tmp_path, embedder=Misdeclares(), store=store)

    with pytest.raises(RuntimeError, match="test-embed"):
        await pipeline.run(await stored_text(storage), uuid4())
    assert store.saved == []


async def test_a_hub_that_raises_does_not_stop_processing(tmp_path: Path) -> None:
    class Broken(SessionHub):
        async def send_to_user_channel(self, user_id, event_type, data) -> int:
            raise RuntimeError("socket layer down")

    pipeline, storage, registry = build(tmp_path, hub=Broken())
    stored = await stored_text(storage)

    result = await pipeline.run(stored, uuid4())

    assert result is not None
    assert registry.get(stored.material_id).stage is MaterialStage.DONE


async def test_a_failure_is_announced_before_it_is_written(tmp_path: Path) -> None:
    """The lecturer should hear about a failure even when the database is what failed."""
    hub = SessionHub()
    owner = uuid4()
    socket = await watching(hub, owner)
    announced_first: list[bool] = []

    class Checks(Store):
        async def record_outcome(self, status, page_count=None, chunk_count=None, warnings=()):
            announced_first.append(stages(socket)[-1] == MaterialStage.FAILED)
            await super().record_outcome(status, page_count, chunk_count, warnings)

    pipeline, storage, _ = build(tmp_path, hub=hub, embedder=Embedder(per_chunk=2), store=Checks())

    with pytest.raises(RuntimeError):
        await pipeline.run(await stored_text(storage), owner)

    assert announced_first == [True]


async def test_a_run_leaves_no_bookkeeping_behind(tmp_path: Path) -> None:
    """One entry per upload, forever, if run() did not clear it."""
    store = Store()
    pipeline, storage, _ = build(tmp_path, store=store)
    await pipeline.run(await stored_text(storage), uuid4())

    failing, storage_two, _ = build(tmp_path, embedder=Embedder(per_chunk=2), store=store)
    with pytest.raises(RuntimeError):
        await failing.run(await stored_text(storage_two), uuid4())

    assert pipeline._outcomes == {}
    assert failing._outcomes == {}


async def test_shutdown_after_done_is_announced_does_not_mark_it_interrupted(
    tmp_path: Path,
) -> None:
    """With no store wired, abandon() skipped the finished check and sent the
    lecturer failed straight after done."""

    class HangsOnDone(Socket):
        def __init__(self) -> None:
            super().__init__()
            self.finishing = asyncio.Event()

        async def send_json(self, payload: dict) -> None:
            await super().send_json(payload)
            if payload["data"]["stage"] == MaterialStage.DONE:
                self.finishing.set()
                await asyncio.sleep(3600)

    hub = SessionHub()
    owner = uuid4()
    socket = HangsOnDone()
    await hub.join(Connection(socket, owner, None))
    pipeline, storage, registry = build(tmp_path, hub=hub)
    processor = BackgroundProcessor(registry, max_concurrent=1)
    stored = await stored_text(storage)

    async def work() -> None:
        await pipeline.run(stored, owner)

    async def interrupted() -> None:
        await pipeline.abandon(stored.material_id, owner)

    processor.submit(stored.material_id, work, on_cancel=interrupted)
    await asyncio.wait_for(socket.finishing.wait(), EVENT_TIMEOUT_SECONDS)
    await processor.drain(grace_seconds=0.0)

    assert registry.get(stored.material_id).stage is MaterialStage.DONE
    assert MaterialStage.FAILED not in stages(socket)


async def test_drafts_with_nowhere_to_be_stored_are_not_announced_as_ready(
    tmp_path: Path,
) -> None:
    """Without a store the lecturer was told questions were ready for review
    that no screen could ever show."""
    hub = SessionHub()
    owner = uuid4()
    socket = await watching(hub, owner)
    pipeline, storage, _ = build(tmp_path, hub=hub, generator=Generator(count=3))

    result = await pipeline.run(await stored_text(storage), owner)

    assert result.question_count == 0
    assert "ready for review" not in (socket.sent[-1]["data"]["message"] or "")
    assert any("3 draft question(s) were generated but not stored" in w for w in result.warnings)
