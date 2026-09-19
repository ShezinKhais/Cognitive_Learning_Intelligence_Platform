"""Accepting a lecture upload, and the process-wide wiring behind it.

Owner: General CS, Phase 2.

Storage, the background processor and the pipeline are one instance each for
the life of the process. The processor has to be shared or its concurrency
ceiling is per request, which is no ceiling at all, and the shutdown hook in
app.main has to reach the same processor the route submitted to.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from functools import lru_cache
from uuid import UUID, uuid4

from fastapi import UploadFile
from openai import AsyncOpenAI

from app.core.config import Settings, get_settings
from app.services.embeddings import OllamaEmbedder, OllamaEmbeddingClient
from app.services.extraction import SUPPORTED
from app.services.generation import QuestionGenerator
from app.services.jobs import BackgroundProcessor
from app.services.material_store import DatabaseMaterialStore
from app.services.pipeline import MaterialPipeline
from app.services.storage import CHUNK_BYTES, LocalDiskStorage, StoredFile
from app.services.upload_security import validate_uploaded_file


async def accept_upload(file: UploadFile, owner_id: UUID) -> StoredFile:
    """Write an upload down, check it is what it says it is, and queue it.

    Everything the lecturer waits for happens here, while there is still a
    response to refuse the file with: storage enforces the extension, the size
    ceiling and a non-empty body, and the security check reads the stored bytes,
    so an executable renamed lecture.pdf is refused now rather than failing a
    job nobody is watching. The material's row is then created under the id the
    response returns. A file refused, or one whose row cannot be written, is
    removed before the error goes back.
    """
    # Assembled before anything is written, so a wiring fault fails the
    # request without leaving a checked file behind that no job will process.
    storage = get_material_storage()
    pipeline = get_material_pipeline()
    processor = get_background_processor()

    stored = await storage.save(uuid4(), file.filename or "", stream_upload(file))
    try:
        async with storage.materialise(stored) as path:
            # The structure checks open and scan the file, so they run off the
            # event loop like every other disk touch on this path.
            await asyncio.to_thread(
                validate_uploaded_file, str(path), stored.extension, file.content_type
            )
        job = await pipeline.admit(stored, owner_id)
    except Exception:
        await storage.delete(stored.material_id)
        raise

    processor.submit(job)
    return stored


async def stream_upload(file: UploadFile) -> AsyncIterator[bytes]:
    """Hand the storage layer an upload in blocks.

    Starlette has already spilled anything large to a temporary file, so this
    reads it back a block at a time rather than calling read() with no argument
    and holding the whole lecture in memory on the way to disk.
    """
    while block := await file.read(CHUNK_BYTES):
        yield block


def material_extensions(settings: Settings) -> set[str]:
    """What the material route will accept, which is narrower than the config.

    allowed_upload_extensions also serves the administrator CSV and XLSX
    importers, and the shipped default includes both. Accepting a spreadsheet
    here would answer 202 for a file extraction refuses, so the intersection is
    taken: an operator can narrow the list, but not widen it past the parsers.
    """
    return settings.upload_extensions & set(SUPPORTED)


@lru_cache
def get_material_storage() -> LocalDiskStorage:
    settings = get_settings()
    return LocalDiskStorage(settings, allowed=material_extensions(settings))


@lru_cache
def get_background_processor() -> BackgroundProcessor:
    return BackgroundProcessor(max_concurrent=get_settings().max_concurrent_material_jobs)


def get_question_generator() -> QuestionGenerator:
    """The generator the pipeline uses, for regenerating a single question."""
    return get_material_pipeline().generator


@lru_cache
def get_material_pipeline() -> MaterialPipeline:
    """The pipeline with its collaborators as they stand.

    The embedder and generator are AI 1's, the store BBIS's. The store opens
    a database session of its own for each write: the request has returned
    long before the job runs, so it cannot borrow the request's.
    """
    settings = get_settings()
    client = AsyncOpenAI(
        base_url=settings.ollama_base_url,
        api_key="ollama",
        timeout=120.0,
        max_retries=1,
    )

    return MaterialPipeline(
        storage=get_material_storage(),
        settings=settings,
        embedder=OllamaEmbedder(
            OllamaEmbeddingClient(client, settings.embedding_model),
            settings.embedding_model,
        ),
        generator=QuestionGenerator(client, settings.ollama_model),
        store=DatabaseMaterialStore(),
    )
