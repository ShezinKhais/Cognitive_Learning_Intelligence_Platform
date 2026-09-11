"""Process-wide wiring for the upload path.

Owner: General CS, Phase 2.

Storage, the job registry, the background processor and the pipeline are one
instance each for the life of the process. The registry has to be shared or a
status read would look at a different dictionary than the one the worker wrote
to, and the processor has to be shared or its concurrency ceiling is per
request, which is no ceiling at all.

They are assembled here rather than in the route so that the shutdown hook in
app.main can reach the same processor the route submitted to.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from functools import lru_cache

from fastapi import UploadFile

from app.core.config import get_settings
from app.services.jobs import BackgroundProcessor, JobRegistry
from app.services.pipeline import MaterialPipeline
from app.services.storage import CHUNK_BYTES, LocalDiskStorage


async def stream_upload(file: UploadFile) -> AsyncIterator[bytes]:
    """Hand the storage layer an upload in blocks.

    Starlette has already spilled anything large to a temporary file, so this
    reads it back a block at a time rather than calling read() with no argument
    and holding the whole lecture in memory on the way to disk.
    """
    while block := await file.read(CHUNK_BYTES):
        yield block


@lru_cache
def get_material_storage() -> LocalDiskStorage:
    return LocalDiskStorage(get_settings())


@lru_cache
def get_job_registry() -> JobRegistry:
    return JobRegistry()


@lru_cache
def get_background_processor() -> BackgroundProcessor:
    return BackgroundProcessor(
        get_job_registry(),
        max_concurrent=get_settings().max_concurrent_material_jobs,
    )


@lru_cache
def get_material_pipeline() -> MaterialPipeline:
    """The pipeline with its collaborators as they stand.

    The embedder, generator and store seams are left unset until AI 1's #37 and
    BBIS's #36 land. When the store is wired in, note that it cannot hold the
    request's database session: the request has returned long before the job
    runs, so the store has to open a session of its own.
    """
    return MaterialPipeline(
        storage=get_material_storage(),
        registry=get_job_registry(),
        settings=get_settings(),
    )
