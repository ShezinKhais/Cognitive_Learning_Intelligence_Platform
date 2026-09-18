"""What a material records when a deploy stops the process around it.

Owner: General CS, Phase 2.

Shutdown can land anywhere in a run. These pin each place that matters: mid
stage, mid terminal write, and after a terminal state was already announced.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from uuid import uuid4

from app.realtime.hub import Connection, SessionHub
from app.schemas.events import MaterialStage
from app.services.jobs import (
    INTERNAL_ERROR,
    INTERRUPTED_ERROR,
    INTERRUPTED_MESSAGE,
    BackgroundProcessor,
    JobStatus,
)
from app.services.material_seams import CompletedMaterial, EmbeddingBatch

from .pipeline_support import (
    EVENT_TIMEOUT_SECONDS,
    Embedder,
    Socket,
    Store,
    build,
    exists,
    stages,
    stored_text,
    watching,
)


async def test_an_upload_interrupted_by_shutdown_is_reported_and_recorded(
    tmp_path: Path,
) -> None:
    """Without this the process exits with the lecturer still watching the
    bar move and the database still saying the material is processing."""

    class StallingEmbedder:
        def __init__(self) -> None:
            self.embedding = asyncio.Event()

        async def embed(self, chunks) -> EmbeddingBatch:
            self.embedding.set()
            await asyncio.sleep(3600)
            raise AssertionError("unreachable")

    hub = SessionHub()
    owner = uuid4()
    socket = await watching(hub, owner)
    store = Store()
    embedder = StallingEmbedder()
    pipeline, storage, _ = build(tmp_path, hub=hub, embedder=embedder, store=store)
    processor = BackgroundProcessor(max_concurrent=1)
    stored = await stored_text(storage)

    processor.submit(pipeline.job(stored, owner))
    # Stopped partway through, rather than before it began.
    await asyncio.wait_for(embedder.embedding.wait(), EVENT_TIMEOUT_SECONDS)

    await processor.drain(grace_seconds=0.01)

    assert stages(socket)[-1] == MaterialStage.FAILED
    assert socket.sent[-1]["data"]["message"] == INTERRUPTED_MESSAGE
    assert [outcome.stage for outcome in store.outcomes] == [MaterialStage.FAILED]
    assert store.outcomes[0].error == INTERRUPTED_ERROR
    # Nothing was wrong with the file, so it survives for a retry.
    assert exists(stored.key)


async def test_shutdown_during_a_failure_write_keeps_the_real_failure(tmp_path: Path) -> None:
    """A failure is announced before it is written, so shutdown used to take
    the job as finished, and the database never learned it had failed."""

    class SlowToRecord(Store):
        def __init__(self) -> None:
            super().__init__()
            self.writing = asyncio.Event()

        async def record_failed(self, status: JobStatus) -> None:
            self.writing.set()
            await asyncio.sleep(0.05)
            await super().record_failed(status)

    store = SlowToRecord()
    pipeline, storage, _ = build(tmp_path, embedder=Embedder(per_chunk=2), store=store)
    processor = BackgroundProcessor(max_concurrent=1)
    stored = await stored_text(storage)
    owner = uuid4()

    processor.submit(pipeline.job(stored, owner))
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
    pipeline, storage, _ = build(tmp_path, hub=hub, embedder=Embedder(per_chunk=2), store=store)
    processor = BackgroundProcessor(max_concurrent=1)
    stored = await stored_text(storage)

    processor.submit(pipeline.job(stored, owner))
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

        async def record_completed(self, material: CompletedMaterial) -> None:
            await super().record_completed(material)
            self.committed.set()
            await asyncio.sleep(0.05)

    hub = SessionHub()
    owner = uuid4()
    socket = await watching(hub, owner)
    store = CommitsThenStalls()
    pipeline, storage, _ = build(tmp_path, hub=hub, store=store)
    processor = BackgroundProcessor(max_concurrent=1)
    stored = await stored_text(storage)

    processor.submit(pipeline.job(stored, owner))
    await asyncio.wait_for(store.committed.wait(), EVENT_TIMEOUT_SECONDS)
    await processor.drain(grace_seconds=0.0)

    assert [outcome.stage for outcome in store.outcomes] == [MaterialStage.DONE]
    assert stages(socket)[-1] == MaterialStage.DONE


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
    pipeline, storage, _ = build(tmp_path, hub=hub)
    processor = BackgroundProcessor(max_concurrent=1)
    stored = await stored_text(storage)

    processor.submit(pipeline.job(stored, owner))
    await asyncio.wait_for(socket.finishing.wait(), EVENT_TIMEOUT_SECONDS)
    await processor.drain(grace_seconds=0.0)

    assert stages(socket)[-1] == MaterialStage.DONE
    assert MaterialStage.FAILED not in stages(socket)


async def test_shutdown_while_questions_generate_records_the_interruption(
    tmp_path: Path,
) -> None:
    """Generation failures are absorbed, but cancellation is not a failure:
    it must still reach abandon() rather than completing the material."""

    class StallingGenerator:
        def __init__(self) -> None:
            self.generating = asyncio.Event()

        async def generate(self, material_id, chunks):
            self.generating.set()
            await asyncio.sleep(3600)
            return []

    store = Store()
    generator = StallingGenerator()
    pipeline, storage, _ = build(tmp_path, generator=generator, store=store)
    processor = BackgroundProcessor(max_concurrent=1)
    stored = await stored_text(storage)
    owner = uuid4()

    processor.submit(pipeline.job(stored, owner))
    await asyncio.wait_for(generator.generating.wait(), EVENT_TIMEOUT_SECONDS)
    await processor.drain(grace_seconds=0.0)

    assert [outcome.error for outcome in store.outcomes] == [INTERRUPTED_ERROR]
    assert store.completed == []
