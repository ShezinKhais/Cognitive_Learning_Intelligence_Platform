"""Turns an uploaded file into indexed chunks and draft questions.

Owner: General CS, Phase 2.

This is the work that `POST /api/v1/materials` promises when it answers 202.
It runs under the background processor in app.services.jobs, so nothing here
is on a request path and nothing here may block the event loop.

The lecturer is watching while it runs, which shapes the design more than the
processing does. Every stage is announced before it starts, as a
`material.progress` event on the uploader's own channel, so a forty second
parse reads as progress rather than as a hang. The stages and their percentages
are the frozen contract in events.schema.json; the pipeline picks none of them.

Three collaborators are Protocols rather than imports. Embedding and question
generation belong to AI 1 (issue #37) and persistence to BBIS (issue #36), and
all three land after this file. Leaving them as seams means the pipeline is
finished and testable now, and that plugging in the real implementations is a
constructor argument rather than a rewrite. A seam that is not supplied is
skipped, not faked: the stage is never announced, so the lecturer is not shown
an embedding step that did not happen.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Protocol
from uuid import UUID

from app.core.config import Settings
from app.core.errors import ValidationError
from app.realtime.hub import SessionHub
from app.realtime.hub import hub as default_hub
from app.schemas.events import MaterialProgressPayload, MaterialStage, ServerEventType
from app.services.extraction import ContentChunk, ProcessingResult, process_material
from app.services.jobs import JobRegistry, JobStatus
from app.services.storage import MaterialStorage, StoredFile

log = logging.getLogger("clip.pipeline")

Embedding = Sequence[float]


class ChunkEmbedder(Protocol):
    """Owner: AI 1, issue #37."""

    async def embed(self, chunks: Sequence[ContentChunk]) -> Sequence[Embedding]:
        """One vector per chunk, in the order the chunks were given."""
        ...


class QuestionGenerator(Protocol):
    """Owner: AI 1, issue #37."""

    async def generate(self, material_id: UUID, chunks: Sequence[ContentChunk]) -> int:
        """Draft questions from the chunks. Returns how many were produced."""
        ...


class MaterialStore(Protocol):
    """Owner: BBIS, issue #36.

    The material row itself is created by the upload route, which knows the
    filename and the size. This seam only records what processing found.
    """

    async def save_chunks(
        self, result: ProcessingResult, embeddings: Sequence[Embedding]
    ) -> None: ...

    async def record_outcome(
        self,
        status: JobStatus,
        page_count: int | None = None,
        chunk_count: int | None = None,
    ) -> None: ...


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

    async def run(self, stored: StoredFile, owner_id: UUID) -> PipelineResult | None:
        """Process one material. Returns None when the file itself was unusable.

        A document that cannot be read is an answer, not a crash: the failure is
        recorded, reported and returned as None. Anything else is a bug in this
        process, so it is recorded and then re-raised, which is what puts a
        traceback in the log.
        """
        material_id = stored.material_id
        try:
            return await self._process(stored, owner_id)
        except ValidationError as exc:
            log.info("material %s rejected: %s", material_id, exc.message)
            await self._fail(material_id, owner_id, exc.message, exc.code)
            # The file is not readable, so keeping it costs disk for something
            # no retry can use. A failure from any other cause may be transient,
            # and those files are left in place.
            await self._storage.delete(material_id)
            return None
        except asyncio.CancelledError:
            # Shutdown. The processor records this one, because only it knows
            # the difference between a deploy and a bad file.
            raise
        except Exception as exc:
            await self._fail(
                material_id,
                owner_id,
                "Processing failed unexpectedly.",
                type(exc).__name__,
            )
            raise

    async def _process(self, stored: StoredFile, owner_id: UUID) -> PipelineResult:
        material_id = stored.material_id

        await self._report(material_id, owner_id, MaterialStage.VALIDATING, "Checking the file.")

        await self._report(material_id, owner_id, MaterialStage.EXTRACTING, "Reading the document.")
        async with self._storage.materialise(stored) as path:
            # process_material is synchronous and CPU-bound: fifteen seconds on
            # a normal deck, eighteen when it upgrades to docling. Calling it
            # inline would freeze every live session on this process for that
            # long, which is the exact failure the 202 exists to avoid.
            result = await asyncio.to_thread(
                process_material,
                str(path),
                material_id,
                self._settings.max_upload_bytes,
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

        embeddings = await self._embed(material_id, owner_id, result.chunks)

        if self._store is not None:
            await self._store.save_chunks(result, embeddings)

        question_count = await self._generate(material_id, owner_id, result.chunks)

        warnings = list(result.warnings)
        for missing, what in (
            (self._embedder is None, "embedding"),
            (self._generator is None, "question generation"),
            (self._store is None, "persistence"),
        ):
            if missing:
                warnings.append(f"{what} is not wired up in this build and was skipped")

        status = await self._report(
            material_id,
            owner_id,
            MaterialStage.DONE,
            f"{question_count} question(s) ready for review."
            if question_count
            else f"Processed {len(result.chunks)} chunk(s).",
        )

        if self._store is not None:
            await self._store.record_outcome(
                status,
                page_count=result.page_count,
                chunk_count=len(result.chunks),
            )

        log.info(
            "material %s done: parser=%s pages=%d chunks=%d questions=%d warnings=%s",
            material_id,
            result.parser_used,
            result.page_count,
            len(result.chunks),
            question_count,
            warnings or "none",
        )

        return PipelineResult(
            material_id=material_id,
            page_count=result.page_count,
            chunk_count=len(result.chunks),
            question_count=question_count,
            parser_used=result.parser_used,
            warnings=tuple(warnings),
        )

    async def _embed(
        self, material_id: UUID, owner_id: UUID, chunks: Sequence[ContentChunk]
    ) -> list[Embedding]:
        if self._embedder is None:
            return []

        await self._report(
            material_id, owner_id, MaterialStage.EMBEDDING, "Indexing the content for retrieval."
        )
        embeddings = list(await self._embedder.embed(chunks))

        # zip would drop the surplus silently, storing chunks against the wrong
        # vectors and leaving retrieval to return confidently wrong slides.
        if len(embeddings) != len(chunks):
            raise RuntimeError(
                f"embedder returned {len(embeddings)} vectors for {len(chunks)} chunks"
            )
        return embeddings

    async def _generate(
        self, material_id: UUID, owner_id: UUID, chunks: Sequence[ContentChunk]
    ) -> int:
        if self._generator is None:
            return 0

        await self._report(material_id, owner_id, MaterialStage.GENERATING, "Drafting questions.")
        return await self._generator.generate(material_id, chunks)

    async def _fail(self, material_id: UUID, owner_id: UUID, message: str, error: str) -> None:
        status = await self._report(
            material_id, owner_id, MaterialStage.FAILED, message, error=error
        )
        if self._store is None:
            return
        try:
            await self._store.record_outcome(status)
        except Exception:
            # Already failing. A second error here would replace a message that
            # names the real problem with one about the database.
            log.exception("could not record the failure of material %s", material_id)

    async def _report(
        self,
        material_id: UUID,
        owner_id: UUID,
        stage: MaterialStage,
        message: str | None = None,
        error: str | None = None,
    ) -> JobStatus:
        """Record a stage and tell the uploader about it.

        The payload is built through the contract model rather than as a plain
        dict, so an event that no longer matches events.schema.json fails here
        instead of reaching a client that cannot read it.

        Only terminal states are written through to the store. A row update per
        stage would be six writes per upload to record something the websocket
        has already delivered.
        """
        status = self._registry.advance(material_id, stage, message=message, error=error)
        payload = MaterialProgressPayload(
            material_id=material_id,
            stage=stage,
            percent=status.percent,
            message=message,
        )

        try:
            await self._hub.send_to_user_channel(
                owner_id,
                ServerEventType.MATERIAL_PROGRESS,
                payload.model_dump(mode="json"),
            )
        except Exception:
            # A closed tab is not a reason to abandon a parse, and neither is a
            # broken socket. The status stays readable over REST regardless.
            log.warning("could not deliver progress for material %s", material_id)

        return status
