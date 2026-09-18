"""Turns an uploaded file into indexed chunks and draft questions.

Owner: General CS, Phase 2.

This is the work that `POST /api/v1/materials` promises when it answers 202.
It runs under the background processor in app.services.jobs, so nothing here
is on a request path and nothing here may block the event loop.

The lecturer is watching while it runs, which shapes the design more than the
processing does. Every stage is announced before it starts, as a
`material.progress` event on the uploader's own channel, so a forty second
parse reads as progress rather than as a hang. The stages are the frozen
contract in events.schema.json, which bounds percent to 0-100; the value for
each stage is STAGE_PERCENT in app.services.jobs, so the pipeline picks none.

`MaterialPipeline` is the set of collaborators, built once per process.
`MaterialJob` is one upload going through them. Everything that belongs to a
single material, the uploader, the stored file and the terminal step in
flight, lives on the job, so a shutdown that interrupts it is handed back the
same object that was running rather than having to look it up.

Persistence is the store seam in app.services.material_seams. Every stage is
added to the material's history as it is announced, and the outcome is written
in one transaction before it is announced. A pipeline built without a store,
as some tests build it, writes nothing, offers no drafts for review, and keeps
the raw upload as the only durable copy.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Coroutine, Sequence
from dataclasses import dataclass, field
from typing import Any
from uuid import UUID

from app.core.config import Settings
from app.core.errors import ValidationError
from app.core.threads import run_in_daemon_thread
from app.realtime.hub import SessionHub
from app.realtime.hub import hub as default_hub
from app.schemas.events import MaterialProgressPayload, MaterialStage, ServerEventType
from app.services.extraction import ContentChunk, process_material
from app.services.jobs import (
    INTERNAL_ERROR,
    INTERRUPTED_ERROR,
    INTERRUPTED_MESSAGE,
    UNEXPECTED_FAILURE_MESSAGE,
    JobStatus,
)
from app.services.material_seams import (
    ChunkEmbedder,
    CompletedMaterial,
    DraftQuestion,
    EmbeddingBatch,
    MaterialStore,
    ModelRun,
    QuestionGenerator,
)
from app.services.processing_security import validate_processing_result
from app.services.storage import MaterialStorage, StoredFile

log = logging.getLogger("clip.pipeline")

UNSTORED_NOTE = "persistence is not wired up in this build and was skipped"


@dataclass(frozen=True)
class PipelineResult:
    material_id: UUID
    page_count: int
    chunk_count: int
    question_count: int
    parser_used: str
    warnings: tuple[str, ...] = ()


@dataclass(frozen=True)
class MaterialPipeline:
    """What processing a material needs, assembled once per process."""

    storage: MaterialStorage
    settings: Settings
    embedder: ChunkEmbedder
    generator: QuestionGenerator
    store: MaterialStore | None = None
    hub: SessionHub = field(default=default_hub)

    def job(self, stored: StoredFile, owner_id: UUID) -> MaterialJob:
        return MaterialJob(self, stored, owner_id)

    async def admit(self, stored: StoredFile, owner_id: UUID) -> MaterialJob:
        """Record an accepted upload and return the job that will process it.

        Called while the upload request is still open, so the material's row
        exists, under the id the lecturer is given, before any work is queued
        and before GET /materials/{id} can be asked about it.
        """
        if self.store is not None:
            await self.store.record_accepted(stored, owner_id)
        return self.job(stored, owner_id)


class MaterialJob:
    """One material, from stored bytes to reviewable questions."""

    def __init__(self, pipeline: MaterialPipeline, stored: StoredFile, owner_id: UUID) -> None:
        self._pipeline = pipeline
        self._stored = stored
        self._owner_id = owner_id
        self.material_id = stored.material_id
        # The terminal step, once it has started. See _settle for why it exists
        # and abandon() for why it matters.
        self._settling: asyncio.Future[None] | None = None

    async def run(self) -> PipelineResult | None:
        """Process the material. Returns None when the file itself was unusable.

        A document that cannot be read is an answer, not a crash: the failure is
        recorded, reported and returned as None. Anything else is a bug in this
        process, so it is recorded and then re-raised, which is what puts a
        traceback in the log.

        Cancellation is deliberately not handled here; the processor hands a
        cancelled job to abandon() instead.
        """
        storage = self._pipeline.storage
        try:
            outcome = await self._process()
        except ValidationError as exc:
            log.info("material %s rejected: %s", self.material_id, exc.message)
            await self._fail(exc.message, exc.code)
            # The file is not readable, so keeping it costs disk for something
            # no retry can use. A failure from any other cause may be transient,
            # and those files are left in place.
            await storage.delete(self.material_id)
            return None
        except Exception as exc:
            log.info("material %s failed with %s", self.material_id, type(exc).__name__)
            await self._fail(UNEXPECTED_FAILURE_MESSAGE, INTERNAL_ERROR)
            raise

        await self._discard_raw_file()
        return outcome

    async def abandon(self) -> None:
        """Make sure a material stopped by shutdown ends in a recorded state.

        The processor calls this for a job still waiting for a slot as well as
        one halfway through; a queued job never entered run() at all. The stored
        file is kept, since nothing was wrong with it.

        If the material had already reached its terminal step, that step is
        what the outcome is: it is finished rather than overwritten. Marking the
        material interrupted on top of it used to replace a committed success,
        or a failure the lecturer had already been told about.
        """
        if self._settling is not None:
            try:
                await asyncio.shield(self._settling)
                return
            except Exception:
                log.warning("material %s did not reach a recorded end state", self.material_id)

        await self._fail(INTERRUPTED_MESSAGE, INTERRUPTED_ERROR)

    async def _process(self) -> PipelineResult:
        pipeline = self._pipeline

        await self._report(MaterialStage.VALIDATING, "Checking the file.")

        await self._report(MaterialStage.EXTRACTING, "Reading the document.")
        async with pipeline.storage.materialise(self._stored) as path:
            # process_material is synchronous and CPU-bound: fifteen seconds on
            # a normal deck, eighteen when it upgrades to docling. Calling it
            # inline would freeze every live session on this process for that
            # long, which is the exact failure the 202 exists to avoid.
            # Extraction only reads the stored file, so a daemon thread is safe.
            result = await run_in_daemon_thread(
                process_material,
                str(path),
                self.material_id,
                pipeline.settings.max_upload_bytes,
                name="material-extraction",
            )

        # Validation, extraction and chunking are one call in AI 1's module, so
        # this event marks chunking finished rather than started. Splitting it
        # would mean reimplementing the entry point they own, and the bar sits
        # in the right place either way.
        await self._report(
            MaterialStage.CHUNKING,
            f"Split into {len(result.chunks)} chunk(s) across {result.page_count} page(s).",
        )

        # Cyber 1: reject excessive extraction results before embedding,
        # persistence or question generation use additional resources.
        validate_processing_result(result, pipeline.settings)

        embeddings = await self._embed(result.chunks)
        # For the lecturer, and stored. The build notes below are for whoever
        # reads the log, and a lecturer has no use for them.
        warnings = list(result.warnings)
        questions, generation = await self._generate(result.chunks, warnings)

        build_notes: list[str] = []
        if pipeline.store is None:
            build_notes.append(UNSTORED_NOTE)
            if questions:
                # Only stored drafts are ready for review. Counting these told
                # the lecturer questions were waiting that no screen could show.
                build_notes.append(
                    f"{len(questions)} draft question(s) were generated but not stored"
                )
                questions = []

        done = JobStatus.for_stage(
            self.material_id,
            MaterialStage.DONE,
            message=(
                f"{len(questions)} question(s) ready for review."
                if questions
                else f"Processed {len(result.chunks)} chunk(s)."
            ),
        )
        await self._succeed(
            CompletedMaterial(
                status=done,
                result=result,
                embeddings=embeddings,
                questions=tuple(questions),
                warnings=tuple(warnings),
                model_runs=(
                    ModelRun(operation="embedding", model=embeddings.model, succeeded=True),
                    generation,
                ),
            )
        )

        log.info(
            "material %s done: parser=%s pages=%d chunks=%d questions=%d warnings=%s",
            self.material_id,
            result.parser_used,
            result.page_count,
            len(result.chunks),
            len(questions),
            warnings + build_notes or "none",
        )

        return PipelineResult(
            material_id=self.material_id,
            page_count=result.page_count,
            chunk_count=len(result.chunks),
            question_count=len(questions),
            parser_used=result.parser_used,
            warnings=tuple(warnings + build_notes),
        )

    async def _embed(self, chunks: Sequence[ContentChunk]) -> EmbeddingBatch:
        await self._report(MaterialStage.EMBEDDING, "Indexing the content for retrieval.")
        batch = await self._pipeline.embedder.embed(chunks)

        # zip would drop the surplus silently, storing chunks against the wrong
        # vectors and leaving retrieval to return confidently wrong slides.
        if len(batch.vectors) != len(chunks):
            raise RuntimeError(
                f"embedder returned {len(batch.vectors)} vectors for {len(chunks)} chunks"
            )
        # The column is a fixed-width vector sized from settings, so a model
        # with another width fails at the insert with a pgvector error that
        # names neither the model nor the setting. Refused here, it says both.
        expected = self._pipeline.settings.embedding_dim
        if batch.dim != expected or any(len(vector) != expected for vector in batch.vectors):
            raise RuntimeError(
                f"embedding model {batch.model!r} produced vectors that do not match "
                f"embedding_dim={expected}"
            )
        return batch

    async def _generate(
        self, chunks: Sequence[ContentChunk], warnings: list[str]
    ) -> tuple[list[DraftQuestion], ModelRun]:
        """The usable drafts, and the record of the model call that wrote them."""
        generator = self._pipeline.generator
        await self._report(MaterialStage.GENERATING, "Drafting questions.")
        try:
            drafts = await generator.generate(self.material_id, chunks)
        except Exception as exc:
            # Questions are the one stage a material is still useful without:
            # the chunks are extracted and indexed, and the lecturer can retry
            # generation. A model reply that would not parse used to fail the
            # whole material, after everything before it had succeeded.
            log.exception("question generation failed for material %s", self.material_id)
            warnings.append("Questions could not be generated for this material.")
            failed = ModelRun(
                operation="question_generation",
                model=generator.model,
                succeeded=False,
                detail=type(exc).__name__,
            )
            return [], failed

        # A model will sometimes return an answer key that points past the
        # options. Storing it would mark every student wrong on that question,
        # so it is dropped, and one bad draft does not cost the lecturer the rest.
        usable: list[DraftQuestion] = []
        for index, draft in enumerate(drafts):
            problem = _problem_with(draft)
            if problem is None:
                usable.append(draft)
            else:
                log.warning(
                    "material %s: dropped draft %d, which %s", self.material_id, index, problem
                )
                warnings.append(f"draft question {index} {problem} and was dropped")
        return usable, ModelRun(
            operation="question_generation", model=generator.model, succeeded=True
        )

    async def _succeed(self, material: CompletedMaterial) -> None:
        store = self._pipeline.store

        async def written_then_announced() -> None:
            # Written down before it is announced. The other order told the
            # lecturer "done" and then, when the database write failed,
            # "failed", about a material whose success was never recorded.
            if store is not None:
                await store.record_completed(material)
            await self._announce(material.status)

        await self._settle(written_then_announced())

    async def _fail(self, message: str, error: str) -> None:
        store = self._pipeline.store
        status = JobStatus.for_stage(
            self.material_id, MaterialStage.FAILED, message=message, error=error
        )

        async def announced_then_written() -> None:
            # The reverse of success. A lecturer should hear about a failure
            # even when the database is the thing that failed.
            await self._announce(status)
            if store is None:
                return
            try:
                await store.record_failed(status)
            except Exception:
                # Already failing. A second error here would replace a message
                # that names the real problem with one about the database.
                log.exception("could not record the failure of material %s", self.material_id)

        await self._settle(announced_then_written())

    async def _settle(self, step: Coroutine[Any, Any, None]) -> None:
        """Run the material's terminal step to completion, even if cancelled.

        A shutdown can land anywhere, including between a terminal write and
        its announcement, or after the database committed but before the driver
        returned. Cut there, nobody could say whether the material had ended.
        Shielded, the step always finishes, and abandon() waits for it instead
        of guessing.
        """
        settling = asyncio.ensure_future(step)
        # Read here so an exception nobody awaits is not logged as unretrieved.
        settling.add_done_callback(lambda done: done.cancelled() or done.exception())
        self._settling = settling
        await asyncio.shield(settling)

    async def _discard_raw_file(self) -> None:
        """Delete the uploaded bytes once the extracted material is stored.

        The design keeps a lecture file's metadata, filename and extracted
        chunks, and discards the raw content once processing has used it
        (Design Document 4.1). Reached only after the completed material is
        written, so a store that fails leaves the file for a retry.

        With no store wired, nothing was persisted and the upload is the only
        durable copy, so it is kept until a store can record what it produced.

        A file that will not delete does not undo a finished material, so the
        error is logged rather than raised.
        """
        if self._pipeline.store is None:
            return
        try:
            await self._pipeline.storage.delete(self.material_id)
        except Exception:
            log.warning("could not discard the raw file for material %s", self.material_id)

    async def _report(self, stage: MaterialStage, message: str) -> None:
        """Announce a stage, then add it to the material's stored history.

        The history is for tracing a material afterwards, so a write that
        fails is logged rather than allowed to stop the processing it records.
        """
        status = JobStatus.for_stage(self.material_id, stage, message=message)
        await self._announce(status)
        store = self._pipeline.store
        if store is None:
            return
        try:
            await store.record_progress(status)
        except Exception:
            log.warning("could not record the %s stage of material %s", stage, self.material_id)

    async def _announce(self, status: JobStatus) -> None:
        """Tell the uploader where their material has got to.

        The payload is built through the contract model rather than as a plain
        dict, so an event that no longer matches events.schema.json fails here
        instead of reaching a client that cannot read it.
        """
        payload = MaterialProgressPayload(
            material_id=status.material_id,
            stage=status.stage,
            percent=status.percent,
            message=status.message,
        )
        try:
            await self._pipeline.hub.send_to_user_channel(
                self._owner_id,
                ServerEventType.MATERIAL_PROGRESS,
                payload.model_dump(mode="json"),
            )
        except Exception:
            # A closed tab is not a reason to abandon a parse, and neither is a
            # broken socket.
            log.warning("could not deliver progress for material %s", status.material_id)


def _problem_with(draft: DraftQuestion) -> str | None:
    """Why a draft cannot be stored, treating a check that breaks as a reason.

    A draft malformed enough to break its own check is dropped like any other,
    rather than failing every question with it.
    """
    try:
        return draft.problem()
    except Exception:
        return "could not be checked"
