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

Embedding, question generation and persistence are the seams in
app.services.material_seams, supplied by the workstreams that own them. A seam
that is not supplied is skipped, not faked: the stage is never announced, so
the lecturer is not shown an embedding step that did not happen.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Coroutine, Sequence
from dataclasses import dataclass
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
    JobRegistry,
    JobStatus,
)
from app.services.material_seams import (
    ChunkEmbedder,
    CompletedMaterial,
    DraftQuestion,
    EmbeddingBatch,
    MaterialStore,
    QuestionGenerator,
)
from app.services.processing_security import validate_processing_result
from app.services.storage import MaterialStorage, StoredFile

log = logging.getLogger("clip.pipeline")


@dataclass(frozen=True)
class PipelineResult:
    material_id: UUID
    page_count: int
    chunk_count: int
    question_count: int
    parser_used: str
    warnings: tuple[str, ...] = ()


class MaterialPipeline:
    """Runs one material from stored bytes to reviewable questions."""

    def __init__(
        self,
        *,
        storage: MaterialStorage,
        registry: JobRegistry,
        settings: Settings,
        hub: SessionHub | None = None,
        embedder: ChunkEmbedder | None = None,
        generator: QuestionGenerator | None = None,
        store: MaterialStore | None = None,
    ) -> None:
        self._storage = storage
        self._registry = registry
        self._settings = settings
        self._hub = hub if hub is not None else default_hub
        self._embedder = embedder
        self._generator = generator
        self._store = store
        # The terminal step of each material, while its run() is live. See
        # _settle for why it exists and abandon() for why it outlives a
        # cancelled run.
        self._settling: dict[UUID, asyncio.Future[None]] = {}

    async def run(self, stored: StoredFile, owner_id: UUID) -> PipelineResult | None:
        """Process one material. Returns None when the file itself was unusable.

        A document that cannot be read is an answer, not a crash: the failure is
        recorded, reported and returned as None. Anything else is a bug in this
        process, so it is recorded and then re-raised, which is what puts a
        traceback in the log.

        Cancellation is deliberately not handled here. It skips the cleanup at
        the bottom, so the terminal step stays in _settling for abandon(), which
        the processor calls next.
        """
        material_id = stored.material_id
        try:
            outcome = await self._process(stored, owner_id)
            await self._discard_raw_file(material_id)
        except ValidationError as exc:
            log.info("material %s rejected: %s", material_id, exc.message)
            await self._fail(material_id, owner_id, exc.message, exc.code)
            # The file is not readable, so keeping it costs disk for something
            # no retry can use. A failure from any other cause may be transient,
            # and those files are left in place.
            await self._storage.delete(material_id)
            outcome = None
        except Exception as exc:
            log.info("material %s failed with %s", material_id, type(exc).__name__)
            await self._fail(material_id, owner_id, UNEXPECTED_FAILURE_MESSAGE, INTERNAL_ERROR)
            self._settling.pop(material_id, None)
            raise
        self._settling.pop(material_id, None)
        return outcome

    async def _discard_raw_file(self, material_id: UUID) -> None:
        """Delete the uploaded bytes once the extracted material is stored.

        The design keeps a lecture file's metadata, filename and extracted
        chunks, and discards the raw content once processing has used it
        (Design Document 4.1). Reached only after the completed material is
        written, so a store that fails leaves the file for a retry.

        With no store wired, nothing was persisted and the upload is the only
        durable copy, so it is kept until #36 can record what it produced.

        A file that will not delete does not undo a finished material, so the
        error is logged rather than raised.
        """
        if self._store is None:
            return
        try:
            await self._storage.delete(material_id)
        except Exception:
            log.warning("could not discard the raw file for material %s", material_id)

    async def abandon(self, material_id: UUID, owner_id: UUID) -> None:
        """Make sure a material stopped by shutdown ends in a recorded state.

        Handed to the processor as on_cancel, so it covers a job still waiting
        for a slot as well as one halfway through; a queued job never entered
        run() at all, which is why this cannot live there. The stored file is
        kept, since nothing was wrong with it.

        If the material had already reached its terminal step, that step is
        what the outcome is: it is finished rather than overwritten. Marking the
        material interrupted on top of it used to replace a committed success,
        or a failure the lecturer had already been told about.
        """
        settling = self._settling.pop(material_id, None)
        if settling is not None:
            try:
                await asyncio.shield(settling)
                return
            except Exception:
                log.warning("material %s did not reach a recorded end state", material_id)

        await self._fail(material_id, owner_id, INTERRUPTED_MESSAGE, INTERRUPTED_ERROR)
        self._settling.pop(material_id, None)

    async def _process(self, stored: StoredFile, owner_id: UUID) -> PipelineResult:
        material_id = stored.material_id

        await self._report(material_id, owner_id, MaterialStage.VALIDATING, "Checking the file.")

        await self._report(material_id, owner_id, MaterialStage.EXTRACTING, "Reading the document.")
        async with self._storage.materialise(stored) as path:
            # process_material is synchronous and CPU-bound: fifteen seconds on
            # a normal deck, eighteen when it upgrades to docling. Calling it
            # inline would freeze every live session on this process for that
            # long, which is the exact failure the 202 exists to avoid.
            # Extraction only reads the stored file, so a daemon thread is safe.
            result = await run_in_daemon_thread(
                process_material,
                str(path),
                material_id,
                self._settings.max_upload_bytes,
                name="material-extraction",
            )

        # Validation, extraction and chunking are one call in AI 1's module, so
        # this event marks chunking finished rather than started. Splitting it
        # would mean reimplementing the entry point they own, and the bar sits
        # in the right place either way.
        await self._report(
            material_id,
            owner_id,
            MaterialStage.CHUNKING,
            f"Split into {len(result.chunks)} chunk(s) across {result.page_count} page(s).",
        )

        # Cyber 1: reject excessive extraction results before embedding,
        # persistence or question generation use additional resources.
        validate_processing_result(result, self._settings)

        embeddings = await self._embed(material_id, owner_id, result.chunks)
        # For the lecturer, and stored. The build notes below are for whoever
        # reads the log, and a lecturer has no use for them.
        warnings = list(result.warnings)
        questions = await self._generate(material_id, owner_id, result.chunks, warnings)

        build_notes = [
            f"{seam} is not wired up in this build and was skipped"
            for seam, supplied in (
                ("embedding", self._embedder),
                ("question generation", self._generator),
                ("persistence", self._store),
            )
            if supplied is None
        ]
        if questions and self._store is None:
            # Only stored drafts are ready for review. Counting these told the
            # lecturer questions were waiting that no screen could ever show.
            build_notes.append(f"{len(questions)} draft question(s) were generated but not stored")
            questions = []

        done = JobStatus.for_stage(
            material_id,
            MaterialStage.DONE,
            message=(
                f"{len(questions)} question(s) ready for review."
                if questions
                else f"Processed {len(result.chunks)} chunk(s)."
            ),
        )
        await self._succeed(
            owner_id,
            CompletedMaterial(
                status=done,
                result=result,
                embeddings=embeddings,
                questions=tuple(questions),
                warnings=tuple(warnings),
            ),
        )

        log.info(
            "material %s done: parser=%s pages=%d chunks=%d questions=%d warnings=%s",
            material_id,
            result.parser_used,
            result.page_count,
            len(result.chunks),
            len(questions),
            warnings + build_notes or "none",
        )

        return PipelineResult(
            material_id=material_id,
            page_count=result.page_count,
            chunk_count=len(result.chunks),
            question_count=len(questions),
            parser_used=result.parser_used,
            warnings=tuple(warnings + build_notes),
        )

    async def _embed(
        self, material_id: UUID, owner_id: UUID, chunks: Sequence[ContentChunk]
    ) -> EmbeddingBatch | None:
        if self._embedder is None:
            return None

        await self._report(
            material_id, owner_id, MaterialStage.EMBEDDING, "Indexing the content for retrieval."
        )
        batch = await self._embedder.embed(chunks)

        # zip would drop the surplus silently, storing chunks against the wrong
        # vectors and leaving retrieval to return confidently wrong slides.
        if len(batch.vectors) != len(chunks):
            raise RuntimeError(
                f"embedder returned {len(batch.vectors)} vectors for {len(chunks)} chunks"
            )
        # The column is a fixed-width vector sized from settings, so a model
        # with another width fails at the insert with a pgvector error that
        # names neither the model nor the setting. Refused here, it says both.
        expected = self._settings.embedding_dim
        if batch.dim != expected or any(len(vector) != expected for vector in batch.vectors):
            raise RuntimeError(
                f"embedding model {batch.model!r} produced vectors that do not match "
                f"embedding_dim={expected}"
            )
        return batch

    async def _generate(
        self,
        material_id: UUID,
        owner_id: UUID,
        chunks: Sequence[ContentChunk],
        warnings: list[str],
    ) -> list[DraftQuestion]:
        if self._generator is None:
            return []

        await self._report(material_id, owner_id, MaterialStage.GENERATING, "Drafting questions.")
        try:
            drafts = await self._generator.generate(material_id, chunks)
        except Exception:
            # Questions are the one stage a material is still useful without:
            # the chunks are extracted and indexed, and the lecturer can retry
            # generation. A model reply that would not parse used to fail the
            # whole material, after everything before it had succeeded.
            log.exception("question generation failed for material %s", material_id)
            warnings.append("Questions could not be generated for this material.")
            return []

        # A model will sometimes return an answer key that points past the
        # options. Storing it would mark every student wrong on that question,
        # so it is dropped, and one bad draft does not cost the lecturer the rest.
        usable: list[DraftQuestion] = []
        for index, draft in enumerate(drafts):
            try:
                problem = draft.problem()
            except Exception:
                # A draft malformed enough to break the check is dropped like
                # any other, rather than failing every question with it.
                problem = "could not be checked"
            if problem is None:
                usable.append(draft)
            else:
                log.warning("material %s: dropped draft %d, which %s", material_id, index, problem)
                warnings.append(f"draft question {index} {problem} and was dropped")
        return usable

    async def _succeed(self, owner_id: UUID, material: CompletedMaterial) -> None:
        async def written_then_announced() -> None:
            # Written down before it is announced. The other order told the
            # lecturer "done" and then, when the database write failed,
            # "failed", about a material whose success was never recorded.
            if self._store is not None:
                await self._store.record_completed(material)
            await self._announce(owner_id, material.status)

        await self._settle(material.status.material_id, written_then_announced())

    async def _fail(self, material_id: UUID, owner_id: UUID, message: str, error: str) -> None:
        status = JobStatus.for_stage(
            material_id, MaterialStage.FAILED, message=message, error=error
        )

        async def announced_then_written() -> None:
            # The reverse of success. A lecturer should hear about a failure
            # even when the database is the thing that failed.
            await self._announce(owner_id, status)
            if self._store is None:
                return
            try:
                await self._store.record_failed(status)
            except Exception:
                # Already failing. A second error here would replace a message
                # that names the real problem with one about the database.
                log.exception("could not record the failure of material %s", material_id)

        await self._settle(material_id, announced_then_written())

    async def _settle(self, material_id: UUID, step: Coroutine[Any, Any, None]) -> None:
        """Run a material's terminal step to completion, even if cancelled.

        A shutdown can land anywhere, including between a terminal write and
        its announcement, or after the database committed but before the driver
        returned. Cut there, nobody could say whether the material had ended.
        Shielded, the step always finishes, and abandon() waits for it instead
        of guessing.
        """
        settling = asyncio.ensure_future(step)
        # Read here so an exception nobody awaits is not logged as unretrieved.
        settling.add_done_callback(lambda done: done.cancelled() or done.exception())
        self._settling[material_id] = settling
        await asyncio.shield(settling)

    async def _report(
        self, material_id: UUID, owner_id: UUID, stage: MaterialStage, message: str
    ) -> None:
        await self._announce(owner_id, JobStatus.for_stage(material_id, stage, message=message))

    async def _announce(self, owner_id: UUID, status: JobStatus) -> None:
        """Record a status and tell the uploader about it.

        The payload is built through the contract model rather than as a plain
        dict, so an event that no longer matches events.schema.json fails here
        instead of reaching a client that cannot read it.
        """
        self._registry.record(status)
        payload = MaterialProgressPayload(
            material_id=status.material_id,
            stage=status.stage,
            percent=status.percent,
            message=status.message,
        )

        try:
            await self._hub.send_to_user_channel(
                owner_id,
                ServerEventType.MATERIAL_PROGRESS,
                payload.model_dump(mode="json"),
            )
        except Exception:
            # A closed tab is not a reason to abandon a parse, and neither is a
            # broken socket. The registry keeps the latest status either way;
            # serving it over GET /materials/{id} is BBIS's #36.
            log.warning("could not deliver progress for material %s", status.material_id)
