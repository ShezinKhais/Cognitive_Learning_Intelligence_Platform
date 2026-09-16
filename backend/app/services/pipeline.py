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
import contextvars
import logging
import threading
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Protocol, TypeVar
from uuid import UUID

from app.core.config import Settings
from app.core.errors import ValidationError
from app.realtime.hub import SessionHub
from app.realtime.hub import hub as default_hub
from app.schemas.content import Difficulty, QuestionType
from app.schemas.events import MaterialProgressPayload, MaterialStage, ServerEventType
from app.services.extraction import ContentChunk, ProcessingResult, process_material
from app.services.jobs import (
    INTERNAL_ERROR,
    INTERRUPTED_ERROR,
    INTERRUPTED_MESSAGE,
    JobRegistry,
    JobStatus,
)
from app.services.processing_security import validate_processing_result
from app.services.storage import MaterialStorage, StoredFile

log = logging.getLogger("clip.pipeline")

Embedding = Sequence[float]
T = TypeVar("T")


async def run_in_daemon_thread(fn: Callable[..., T], *args: object) -> T:
    """Run blocking work off the event loop, in a thread shutdown will not wait for.

    asyncio.to_thread uses the default executor, and cancelling the await does
    not stop the thread, because Python cannot interrupt one. The parse ran on
    to the end regardless, and the process could not exit until it had, so a
    deploy that cancelled an eighteen second parse still waited eighteen
    seconds for a result it had already thrown away.

    A daemon thread keeps the event loop just as free and is abandoned when the
    process exits. That is safe for extraction specifically, which reads the
    stored file and writes nothing. A result that arrives after its awaiter has
    gone is dropped rather than handed to a loop that may already be closed.
    """
    loop = asyncio.get_running_loop()
    future: asyncio.Future[T] = loop.create_future()
    # Carried across, as asyncio.to_thread does, so log lines from inside the
    # parse keep the request id of the upload that started it.
    context = contextvars.copy_context()

    def settle_result(result: T) -> None:
        if not future.done():
            future.set_result(result)

    def settle_exception(exc: BaseException) -> None:
        if not future.done():
            future.set_exception(exc)

    def target() -> None:
        try:
            result = context.run(fn, *args)
        except BaseException as exc:
            callback, value = settle_exception, exc
        else:
            callback, value = settle_result, result
        try:
            loop.call_soon_threadsafe(callback, value)
        except RuntimeError:
            # The loop closed while this thread was still working, which is
            # what a shutdown looks like from in here. Nobody is waiting.
            pass

    threading.Thread(target=target, name="material-extraction", daemon=True).start()
    return await future


@dataclass(frozen=True)
class EmbeddingBatch:
    """The vectors for one material, and the model that produced them.

    rag_chunk records embedding_model on every row. Vectors from two models are
    not comparable, so a store that took the name from settings instead would
    mislabel every chunk embedded before a model change, and retrieval could
    not tell the old rows from the new ones.
    """

    vectors: Sequence[Embedding]
    model: str
    dim: int


@dataclass(frozen=True)
class DraftQuestion:
    """One generated question, before a lecturer has seen it.

    The fields are QuestionOut's, less the two the store assigns: the id, and
    the status, which is always draft. Nothing the generator returns can reach
    a class without a lecturer approving it.
    """

    type: QuestionType
    difficulty: Difficulty
    prompt: str
    options: tuple[str, ...] | None = None
    correct_option: int | None = None
    topic: str | None = None
    source_slide: int | None = None
    source_excerpt: str | None = None

    def __post_init__(self) -> None:
        # A generator building drafts from model JSON passes "mcq", not the
        # enum. Compared by identity, every such MCQ was dropped as free text.
        # An unknown value raises here, in the generator, where the bug is.
        object.__setattr__(self, "type", QuestionType(self.type))
        object.__setattr__(self, "difficulty", Difficulty(self.difficulty))
        if self.options is not None and not isinstance(self.options, tuple):
            object.__setattr__(self, "options", tuple(self.options))

    def problem(self) -> str | None:
        """Why this draft cannot be stored, or None when it can."""
        if not isinstance(self.prompt, str) or not self.prompt.strip():
            return "has no prompt"
        if self.type == QuestionType.MCQ:
            if not self.options or len(self.options) < 2:
                return "is multiple choice with fewer than two options"
            if any(not isinstance(option, str) or not option.strip() for option in self.options):
                return "has a blank option"
            if len({option.strip() for option in self.options}) != len(self.options):
                return "repeats an option"
            # bool is an int, so True would otherwise pass as option 1.
            if (
                not isinstance(self.correct_option, int)
                or isinstance(self.correct_option, bool)
                or not 0 <= self.correct_option < len(self.options)
            ):
                return "has an answer key that points at no option"
        elif self.options is not None or self.correct_option is not None:
            return "is free text but carries multiple choice fields"
        if self.source_slide is not None and self.source_slide < 1:
            return "cites a slide before the first"
        return None


class ChunkEmbedder(Protocol):
    """Owner: AI 1, issue #37."""

    async def embed(self, chunks: Sequence[ContentChunk]) -> EmbeddingBatch:
        """One vector per chunk, in the order the chunks were given."""
        ...


class QuestionGenerator(Protocol):
    """Owner: AI 1, issue #37.

    Returns the drafts rather than writing them. Persistence stays behind one
    seam, so the success of a material is recorded only after its chunks and
    its questions have both been stored.
    """

    async def generate(
        self, material_id: UUID, chunks: Sequence[ContentChunk]
    ) -> Sequence[DraftQuestion]: ...


class MaterialStore(Protocol):
    """Owner: BBIS, issue #36.

    This seam only records what processing found. The source_material row it
    writes against has to exist first, and nothing creates it yet: the upload
    route knows the filename and size, and inserting the row there is part of
    wiring #36 in. Chunks carry a foreign key to it.
    """

    async def save_chunks(
        self, result: ProcessingResult, embeddings: EmbeddingBatch | None
    ) -> None:
        """Store every chunk. embeddings is None when no embedder is wired up,
        in which case the chunks are stored without vectors."""
        ...

    async def save_questions(self, material_id: UUID, questions: Sequence[DraftQuestion]) -> None:
        """Store the drafts with status draft."""
        ...

    async def record_outcome(
        self,
        status: JobStatus,
        page_count: int | None = None,
        chunk_count: int | None = None,
        warnings: Sequence[str] = (),
    ) -> None:
        """Write a terminal state. source_material.error takes status.message,
        which is written for the lecturer; status.error is a code for logs and
        branching (VALIDATION_ERROR, INTERRUPTED, INTERNAL_ERROR). warnings are
        lecturer-facing too."""
        ...


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
        # Terminal store writes, by material, with the status each one records.
        # Shutdown has to know what reached the database, and the registry
        # cannot say: it shows a failure the moment it is announced, before the
        # write. Entries are removed when run() ends or abandon() reads them.
        self._outcomes: dict[UUID, tuple[JobStatus, asyncio.Future[None]]] = {}

    async def run(self, stored: StoredFile, owner_id: UUID) -> PipelineResult | None:
        """Process one material. Returns None when the file itself was unusable.

        A document that cannot be read is an answer, not a crash: the failure is
        recorded, reported and returned as None. Anything else is a bug in this
        process, so it is recorded and then re-raised, which is what puts a
        traceback in the log.
        """
        material_id = stored.material_id
        cancelled = False
        try:
            return await self._attempt(stored, owner_id)
        except asyncio.CancelledError:
            cancelled = True
            raise
        finally:
            # A cancelled run leaves its entry for abandon(), which the
            # processor calls next and which needs it.
            if not cancelled:
                self._outcomes.pop(material_id, None)

    async def _attempt(self, stored: StoredFile, owner_id: UUID) -> PipelineResult | None:
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
            # Shutdown. The processor reports it through abandon(), which also
            # covers a job cancelled before it ever reached this method.
            raise
        except Exception as exc:
            log.info("material %s failed with %s", material_id, type(exc).__name__)
            await self._fail(
                material_id,
                owner_id,
                "Processing failed unexpectedly.",
                INTERNAL_ERROR,
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
            result = await run_in_daemon_thread(
                process_material,
                str(path),
                material_id,
                self._settings.max_upload_bytes,
            )

        # Cyber 1: reject excessive extraction results before embedding,
        # persistence or question generation use additional resources.
        validate_processing_result(result, self._settings)

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

        # For the lecturer, and stored. The build notes below are for whoever
        # reads the log, and a lecturer has no use for them.
        lecturer_warnings = list(result.warnings)

        questions = await self._generate(material_id, owner_id, result.chunks, lecturer_warnings)
        # Only stored drafts are ready for review. Without a store the drafts
        # go nowhere, and counting them told the lecturer questions were
        # waiting that no screen could ever show.
        unstored = 0
        if questions and self._store is not None:
            await self._store.save_questions(material_id, questions)
        elif questions:
            unstored = len(questions)
        question_count = len(questions) - unstored

        warnings = list(lecturer_warnings)
        for missing, what in (
            (self._embedder is None, "embedding"),
            (self._generator is None, "question generation"),
            (self._store is None, "persistence"),
        ):
            if missing:
                warnings.append(f"{what} is not wired up in this build and was skipped")
        if unstored:
            warnings.append(f"{unstored} draft question(s) were generated but not stored")

        done_message = (
            f"{question_count} question(s) ready for review."
            if question_count
            else f"Processed {len(result.chunks)} chunk(s)."
        )

        # Written down before it is announced. The other order told the
        # lecturer "done" and then, when the database write failed, "failed",
        # about a material whose success was never recorded anywhere durable.
        await self._record(
            JobStatus.for_stage(material_id, MaterialStage.DONE, message=done_message),
            page_count=result.page_count,
            chunk_count=len(result.chunks),
            warnings=tuple(lecturer_warnings),
        )

        await self._report(material_id, owner_id, MaterialStage.DONE, done_message)

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
        drafts = await self._generator.generate(material_id, chunks)

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

    async def abandon(self, material_id: UUID, owner_id: UUID) -> None:
        """Make sure the outcome of a material stopped by shutdown is recorded.

        Handed to the processor as on_cancel, so it covers a job still waiting
        for a slot as well as one halfway through; a queued job never entered
        run() at all, which is why this cannot live there. The stored file is
        kept, since nothing was wrong with it.

        Shutdown can land at three points, and only one of them is an
        interruption:

        - During a terminal write. The write is shielded and finishes. Marking
          the material interrupted on top of it overwrote a committed success
          with a failure, with the chunks and questions already stored.
        - After a failure was announced but before it was written. The registry
          already showed it, so this used to be skipped and the database kept
          saying processing. The real failure is written instead.
        - Anywhere else. The material is reported and recorded as interrupted.
        """
        pending = self._outcomes.pop(material_id, None)
        if pending is not None:
            status, write = pending
            try:
                await asyncio.shield(write)
            except Exception:
                log.warning("the outcome of material %s was not recorded", material_id)
            else:
                current = self._registry.get(material_id)
                if current is None or not current.is_finished:
                    # Success is written before it is announced, so the
                    # announcement is what the shutdown cut off.
                    await self._report(
                        material_id, owner_id, status.stage, status.message, error=status.error
                    )
                return

        current = self._registry.get(material_id)
        if current is not None and current.is_finished:
            # Already announced, whether or not a store is wired. Without a
            # store this used to fall through and mark a material that had
            # just reported done as interrupted, sending the lecturer failed
            # straight after done.
            if self._store is not None:
                await self._record_quietly(current)
            return

        await self._fail(material_id, owner_id, INTERRUPTED_MESSAGE, INTERRUPTED_ERROR)

    async def _fail(self, material_id: UUID, owner_id: UUID, message: str, error: str) -> None:
        # Announced before it is written down, the reverse of success. A
        # lecturer should hear about a failure even when the database is the
        # thing that failed, whereas success must never be claimed until it is
        # durable.
        status = await self._report(
            material_id, owner_id, MaterialStage.FAILED, message, error=error
        )
        await self._record_quietly(status)

    async def _record_quietly(self, status: JobStatus) -> None:
        try:
            await self._record(status)
        except Exception:
            # Already failing. A second error here would replace a message that
            # names the real problem with one about the database.
            log.exception("could not record the failure of material %s", status.material_id)

    async def _record(
        self,
        status: JobStatus,
        page_count: int | None = None,
        chunk_count: int | None = None,
        warnings: Sequence[str] = (),
    ) -> None:
        """Write a terminal state, and finish writing it even if cancelled.

        A write cancelled after the database committed but before the driver
        returned leaves no way to tell whether it happened. Shielded, it always
        completes, and abandon() waits for it and knows the answer.
        """
        if self._store is None:
            return
        write = asyncio.ensure_future(
            self._store.record_outcome(
                status, page_count=page_count, chunk_count=chunk_count, warnings=warnings
            )
        )
        # Read here so an exception nobody awaits is not logged as unretrieved.
        write.add_done_callback(lambda done: done.cancelled() or done.exception())
        self._outcomes[status.material_id] = (status, write)
        await asyncio.shield(write)

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
