"""The material store: where processing writes what it found.

Owner: BBIS, Phase 2.

Implements the MaterialStore seam in app.services.material_seams against
Postgres. Every write runs in a session of its own, because a material's job
outlives the upload request that started it; a store holding the request's
session would be writing through a connection that has already been returned.

Each call is one transaction, so a material is either fully recorded or not
at all: chunks are never retrievable against a material the database says
failed, and a failed write leaves nothing half-applied for a retry to trip on.
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.database import get_session_factory
from app.models.ai_model_run import AIModelRun
from app.models.extraction_element import ExtractionElement
from app.models.question import Question
from app.models.rag_chunk import RagChunk
from app.repositories.material_repository import MaterialRepository
from app.services.extraction import CONTENT_TYPES
from app.services.jobs import JobStatus
from app.services.material_seams import CompletedMaterial
from app.services.storage import StoredFile

log = logging.getLogger("clip.material_store")

# The width of source_material.error, material_processing_status.message and
# ai_model_run.error.
MAX_MESSAGE_LENGTH = 500


def _bounded(text: str | None) -> str | None:
    return text if text is None or len(text) <= MAX_MESSAGE_LENGTH else text[:MAX_MESSAGE_LENGTH]


class DatabaseMaterialStore:
    """MaterialStore backed by the material, chunk, question and history tables."""

    def __init__(
        self,
        sessions: Callable[[], async_sessionmaker[AsyncSession]] = get_session_factory,
    ) -> None:
        # Resolved per write rather than here, so the engine is created on the
        # event loop that uses it.
        self._sessions = sessions

    @asynccontextmanager
    async def _transaction(self) -> AsyncIterator[AsyncSession]:
        async with self._sessions()() as session, session.begin():
            yield session

    async def record_accepted(self, stored: StoredFile, owner_id: UUID) -> None:
        async with self._transaction() as session:
            await MaterialRepository(session).create(
                material_id=stored.material_id,
                filename=stored.filename,
                content_type=CONTENT_TYPES[stored.extension],
                size_bytes=stored.size_bytes,
                uploaded_by_user_id=owner_id,
            )

    async def record_progress(self, status: JobStatus) -> None:
        async with self._transaction() as session:
            await MaterialRepository(session).record_progress(
                material_id=status.material_id,
                stage=status.stage,
                percent=status.percent,
                message=_bounded(status.message),
            )

    async def record_completed(self, material: CompletedMaterial) -> None:
        status, result = material.status, material.result
        material_id = status.material_id

        async with self._transaction() as session:
            repository = MaterialRepository(session)
            row = await repository.get_by_id(material_id)
            if row is None:
                # record_accepted runs before the job is queued, so this is a
                # bug, and writing chunks against nothing would hide it.
                raise LookupError(f"material {material_id} has no row to record against")

            row.page_count = result.page_count
            row.chunk_count = len(result.chunks)
            row.warnings = list(material.warnings)

            session.add_all(
                ExtractionElement(
                    source_material_id=material_id,
                    element_index=index,
                    element_type=element.el_type,
                    content=element.content,
                    source_page=element.page if element.page >= 1 else None,
                )
                for index, element in enumerate(result.elements)
            )
            session.add_all(
                RagChunk(
                    chunk_id=chunk.chunk_id,
                    source_material_id=material_id,
                    chunk_index=chunk.chunk_index,
                    source_page=chunk.source_page,
                    chunk_text=chunk.chunk_text,
                    embedding_vector=list(vector),
                    embedding_model=material.embeddings.model,
                )
                for chunk, vector in zip(result.chunks, material.embeddings.vectors, strict=True)
            )
            # Drafts belong to no session yet; one is assigned when a question
            # is staged for a class. Review access follows the uploader.
            session.add_all(
                Question(
                    source_material_id=material_id,
                    question_text=draft.prompt,
                    question_type=draft.type.value,
                    status="draft",
                    difficulty=draft.difficulty.value,
                    options=list(draft.options) if draft.options is not None else None,
                    correct_option=draft.correct_option,
                    topic=draft.topic,
                    source_slide=draft.source_slide,
                    source_excerpt=draft.source_excerpt,
                )
                for draft in material.questions
            )
            finished = datetime.now(UTC)
            session.add_all(
                AIModelRun(
                    source_material_id=material_id,
                    operation=run.operation,
                    model_name=run.model,
                    status="completed" if run.succeeded else "failed",
                    error=_bounded(run.detail),
                    completed_at=finished,
                )
                for run in material.model_runs
            )
            await session.flush()

            await repository.record_progress(
                material_id=material_id,
                stage=status.stage,
                percent=status.percent,
                message=_bounded(status.message),
            )

        log.info(
            "material %s recorded: %d chunk(s), %d question(s)",
            material_id,
            len(result.chunks),
            len(material.questions),
        )

    async def record_failed(self, status: JobStatus) -> None:
        # source_material.error takes the lecturer-facing message; the code in
        # status.error is for the log.
        async with self._transaction() as session:
            await MaterialRepository(session).record_progress(
                material_id=status.material_id,
                stage=status.stage,
                percent=status.percent,
                message=_bounded(status.message),
            )
