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

from app.core.config import Settings, get_settings
from app.services.extraction import SUPPORTED
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
