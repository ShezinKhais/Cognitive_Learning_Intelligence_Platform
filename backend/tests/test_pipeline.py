"""Stage orchestration for material processing.

Owner: General CS, Phase 2.

These run against real storage and the real extraction service, so what is
asserted is what a lecturer would actually see. Shutdown behaviour is in
test_pipeline_shutdown.py and draft validation in test_material_seams.py.
"""

from __future__ import annotations

import contextvars
import threading
from pathlib import Path
from uuid import UUID, uuid4

import pytest

from app.realtime.hub import SessionHub
from app.schemas.content import Difficulty, MaterialStatus, QuestionType
from app.schemas.events import MaterialProgressPayload, MaterialStage, ServerEventType
from app.services.extraction import ProcessingResult
from app.services.jobs import INTERNAL_ERROR, JobStatus
from app.services.material_seams import CompletedMaterial, DraftQuestion, EmbeddingBatch

from .pipeline_support import (
    SAMPLES,
    TEST_EMBEDDING_DIM,
    Embedder,
    Generator,
    Store,
    build,
    exists,
    feed,
    mcq,
    read,
    stages,
    stored_text,
    watching,
)

REQUEST: contextvars.ContextVar[str] = contextvars.ContextVar("request", default="none")


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


async def test_the_raw_file_is_discarded_once_the_material_is_recorded(tmp_path: Path) -> None:
    """Chunks and metadata are kept; the uploaded bytes are not (Design 4.1)."""
    store = Store()
    pipeline, storage, registry = build(tmp_path, store=store)
    stored = await stored_text(storage)

    result = await pipeline.run(stored, uuid4())

    assert result is not None
    assert store.completed
    assert not exists(stored.key)
    assert registry.get(stored.material_id).stage is MaterialStage.DONE


async def test_a_store_that_fails_keeps_the_raw_file(tmp_path: Path) -> None:
    """Nothing was recorded, so the upload is still the only copy."""

    class FailingStore(Store):
        async def record_completed(self, material: CompletedMaterial) -> None:
            raise ConnectionError("database unavailable")

    pipeline, storage, _ = build(tmp_path, store=FailingStore())
    stored = await stored_text(storage)

    with pytest.raises(ConnectionError):
        await pipeline.run(stored, uuid4())

    assert exists(stored.key)


async def test_without_a_store_the_raw_file_is_kept(tmp_path: Path) -> None:
    """Nothing was persisted, so the upload is still the only durable copy."""
    pipeline, storage, registry = build(tmp_path)
    stored = await stored_text(storage)

    result = await pipeline.run(stored, uuid4())

    assert result is not None
    assert exists(stored.key)
    assert registry.get(stored.material_id).stage is MaterialStage.DONE


async def test_a_file_that_will_not_delete_does_not_fail_the_material(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    pipeline, storage, registry = build(tmp_path, store=Store())
    stored = await stored_text(storage)

    async def refuse(material_id: UUID) -> None:
        raise PermissionError("file in use")

    monkeypatch.setattr(storage, "delete", refuse)

    result = await pipeline.run(stored, uuid4())

    assert result is not None
    assert registry.get(stored.material_id).stage is MaterialStage.DONE


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
    assert len(store.completed) == 1


async def test_a_failed_material_is_recorded_in_the_store_too(tmp_path: Path) -> None:
    """The registry is memory only, so a restart would forget the failure."""
    store = Store()
    pipeline, storage, _ = build(tmp_path, store=store)
    stored = await storage.save(uuid4(), "broken.pdf", feed(b"not a PDF"))

    await pipeline.run(stored, uuid4())

    assert [outcome.stage for outcome in store.outcomes] == [MaterialStage.FAILED]


async def test_a_store_that_is_down_does_not_replace_the_real_error(tmp_path: Path) -> None:
    class Broken(Store):
        async def record_failed(self, status: JobStatus) -> None:
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
        async def record_completed(self, material: CompletedMaterial) -> None:
            raise ConnectionError("database is gone")

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


async def test_the_store_is_told_which_model_embedded_the_chunks(tmp_path: Path) -> None:
    """rag_chunk.embedding_model is how retrieval tells old vectors from new
    ones after a model change. Taken from settings it would mislabel them."""
    store = Store()
    pipeline, storage, _ = build(tmp_path, embedder=Embedder(), store=store)

    await pipeline.run(await stored_text(storage), uuid4())

    embeddings = store.completed[0].embeddings
    assert embeddings is not None
    assert embeddings.model == "test-embed"


async def test_chunks_are_still_stored_when_no_embedder_is_wired_up(tmp_path: Path) -> None:
    store = Store()
    pipeline, storage, _ = build(tmp_path, store=store)

    await pipeline.run(await stored_text(storage), uuid4())

    assert len(store.completed) == 1
    assert store.completed[0].result.chunks
    assert store.completed[0].embeddings is None


async def test_vectors_of_the_wrong_width_are_refused_before_the_insert(tmp_path: Path) -> None:
    """The column is sized from settings. A model with another width would
    otherwise fail inside pgvector with an error naming neither."""
    store = Store()
    pipeline, storage, _ = build(
        tmp_path, embedder=Embedder(dim=TEST_EMBEDDING_DIM + 1), store=store
    )

    with pytest.raises(RuntimeError, match="test-embed"):
        await pipeline.run(await stored_text(storage), uuid4())

    assert store.completed == []


async def test_generated_questions_reach_the_store(tmp_path: Path) -> None:
    store = Store()
    drafts = [mcq("First?"), mcq("Second?")]
    pipeline, storage, _ = build(tmp_path, generator=Generator(drafts=drafts), store=store)

    result = await pipeline.run(await stored_text(storage), uuid4())

    assert result.question_count == 2
    assert [q.prompt for q in store.completed[0].questions] == ["First?", "Second?"]


async def test_chunks_questions_and_success_are_written_in_one_call(tmp_path: Path) -> None:
    """Written separately, a failure part way left chunks stored and retrievable
    against a material the database said had failed."""
    store = Store()
    pipeline, storage, _ = build(
        tmp_path, embedder=Embedder(), generator=Generator(count=2), store=store
    )

    await pipeline.run(await stored_text(storage), uuid4())

    [written] = store.completed
    assert written.result.chunks
    assert written.embeddings is not None
    assert len(written.questions) == 2
    assert written.status.stage is MaterialStage.DONE


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
    assert broken not in store.completed[0].questions
    assert any("answer key" in w for w in result.warnings)


async def test_only_lecturer_warnings_reach_the_store(tmp_path: Path) -> None:
    """Build notes about unwired seams are for the log, not a lecturer."""
    store = Store()
    broken = DraftQuestion(QuestionType.MCQ, Difficulty.EASY, "Q?", ("A", "B"), 5)
    pipeline, storage, _ = build(tmp_path, generator=Generator(drafts=[broken]), store=store)

    result = await pipeline.run(await stored_text(storage), uuid4())

    stored_warnings = store.completed[0].warnings
    assert any("answer key" in w for w in stored_warnings)
    assert not any("not wired up" in w for w in stored_warnings)
    assert any("not wired up" in w for w in result.warnings)


async def test_an_unexpected_failure_is_recorded_as_a_code(tmp_path: Path) -> None:
    store = Store()
    pipeline, storage, _ = build(tmp_path, embedder=Embedder(per_chunk=2), store=store)

    with pytest.raises(RuntimeError):
        await pipeline.run(await stored_text(storage), uuid4())

    assert store.outcomes[0].error == INTERNAL_ERROR


async def test_a_draft_that_breaks_the_check_is_dropped_not_fatal(tmp_path: Path) -> None:
    store = Store()
    # A slide number that arrived as text makes the range check raise.
    odd = DraftQuestion(QuestionType.MCQ, Difficulty.EASY, "Q?", ("A", "B"), 0, source_slide="3")
    pipeline, storage, _ = build(
        tmp_path, generator=Generator(drafts=[odd, mcq("Kept?")]), store=store
    )

    result = await pipeline.run(await stored_text(storage), uuid4())

    assert result is not None
    assert [q.prompt for q in store.completed[0].questions] == ["Kept?"]
    assert any("could not be checked" in w for w in result.warnings)


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
    assert store.completed == []


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
        async def record_failed(self, status: JobStatus) -> None:
            announced_first.append(stages(socket)[-1] == MaterialStage.FAILED)
            await super().record_failed(status)

    pipeline, storage, _ = build(tmp_path, hub=hub, embedder=Embedder(per_chunk=2), store=Checks())

    with pytest.raises(RuntimeError):
        await pipeline.run(await stored_text(storage), owner)

    assert announced_first == [True]


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


async def test_a_generator_that_fails_leaves_the_material_usable(tmp_path: Path) -> None:
    """A model reply that would not parse used to fail the whole material,
    after extraction and embedding had already succeeded."""

    class Unparseable:
        async def generate(self, material_id, chunks):
            raise ValueError("model did not return valid JSON")

    hub = SessionHub()
    owner = uuid4()
    socket = await watching(hub, owner)
    store = Store()
    pipeline, storage, registry = build(
        tmp_path, hub=hub, embedder=Embedder(), generator=Unparseable(), store=store
    )
    stored = await stored_text(storage)

    result = await pipeline.run(stored, owner)

    assert result is not None
    assert result.question_count == 0
    assert stages(socket)[-1] == MaterialStage.DONE
    assert registry.get(stored.material_id).status is MaterialStatus.COMPLETED
    [written] = store.completed
    assert written.embeddings is not None
    assert written.questions == ()
    assert "Questions could not be generated for this material." in written.warnings
