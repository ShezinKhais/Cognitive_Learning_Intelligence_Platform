"""Where an uploaded lecture file lives between the request and the parser.

Owner: General CS, Phase 2.

The upload route returns 202 and hands processing to a background job, so the
bytes have to outlive the request that carried them. Holding them in memory
until a worker gets to them puts a 50 MB ceiling times however many uploads are
queued onto the process; writing them down instead costs disk, which is the
cheaper thing to run out of.

`MaterialStorage` is a Protocol because the prototype writes to local disk and
a deployed Teams app would write to Azure Blob. The pipeline never learns which
it got. `materialise` exists because the parsers in app.services.extraction
take a filesystem path (pypdf, python-pptx and python-docx all open files, not
streams), so a remote backend has to produce a real local file and clean it up
afterwards. On local disk that context manager yields the stored file directly
and copies nothing.

The client's filename never reaches the filesystem. The on-disk name is the
material id plus a validated extension, so `../../etc/passwd` and a 400
character unicode name are both stored as `<uuid>.csv`. The original is kept as
metadata for display only.
"""

from __future__ import annotations

import asyncio
import logging
import shutil
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol
from uuid import UUID

from app.core.config import Settings
from app.core.errors import ValidationError

log = logging.getLogger("clip.storage")

# Read in fixed blocks so a large upload never sits in memory in one piece and
# the size ceiling is enforced while writing rather than after.
CHUNK_BYTES = 1024 * 1024


@dataclass(frozen=True)
class StoredFile:
    """A file that has been written down and can be processed later."""

    material_id: UUID
    filename: str  # what the lecturer called it, for display only
    extension: str  # validated, lowercase, no leading dot
    size_bytes: int
    key: str  # locator the storage backend understands


class MaterialStorage(Protocol):
    """The seam between uploading a file and processing it."""

    async def save(
        self,
        material_id: UUID,
        filename: str,
        source: AsyncIterator[bytes],
    ) -> StoredFile:
        """Write an upload down and return a handle to it."""
        ...

    def materialise(self, stored: StoredFile):  # -> AsyncContextManager[Path]
        """Yield a local filesystem path the parsers can open."""
        ...

    async def delete(self, material_id: UUID) -> None:
        """Remove a stored file. Missing is not an error."""
        ...


def validated_extension(filename: str, allowed: set[str]) -> str:
    """Return the lowercase extension, or refuse the file.

    The extension decides which parser runs, so it is the one part of a
    client-supplied name that reaches our logic and it is checked here rather
    than trusted. Suffix comes from PurePath, so a name like `notes.pdf.exe`
    yields `exe` and is refused instead of being read as a PDF.
    """
    extension = Path(filename).suffix.lower().lstrip(".")

    if not extension:
        raise ValidationError(
            "This file has no extension, so there is no way to tell what it is.",
            {"filename": Path(filename).name},
        )

    if extension not in allowed:
        raise ValidationError(
            f"Unsupported file format: .{extension}",
            {"supported": sorted(allowed), "received": extension},
        )

    return extension


class LocalDiskStorage:
    """Writes uploads under a directory on the local filesystem.

    Files are named by material id, so two lecturers uploading `lecture.pdf`
    on the same afternoon do not collide and neither can overwrite the other.
    """

    def __init__(self, settings: Settings) -> None:
        self._root = Path(settings.upload_storage_dir).resolve()
        self._max_bytes = settings.max_upload_bytes
        self._allowed = settings.upload_extensions

    @property
    def root(self) -> Path:
        return self._root

    def _path_for(self, material_id: UUID, extension: str) -> Path:
        return self._root / f"{material_id}.{extension}"

    async def save(
        self,
        material_id: UUID,
        filename: str,
        source: AsyncIterator[bytes],
    ) -> StoredFile:
        extension = validated_extension(filename, self._allowed)
        await asyncio.to_thread(self._root.mkdir, parents=True, exist_ok=True)
        destination = self._path_for(material_id, extension)

        # Every disk touch goes through a worker thread. A 50 MB upload written
        # inline holds the event loop for the whole write, which stalls the
        # heartbeat of every live session on the process. Uploading is meant to
        # be the thing that does not block the API.
        written = 0
        try:
            handle = await asyncio.to_thread(destination.open, "wb")
            try:
                async for block in source:
                    written += len(block)
                    # Checked before the write, so the ceiling is what lands on
                    # disk rather than the ceiling plus one block.
                    if written > self._max_bytes:
                        raise ValidationError(
                            "File is too large",
                            {"max_bytes": self._max_bytes},
                        )
                    await asyncio.to_thread(handle.write, block)
            finally:
                await asyncio.to_thread(handle.close)
        except BaseException:
            # A partial file is worse than none: the parser would read it and
            # report corrupt content rather than a failed upload.
            await asyncio.to_thread(destination.unlink, missing_ok=True)
            raise

        if written == 0:
            await asyncio.to_thread(destination.unlink, missing_ok=True)
            raise ValidationError("File is empty", {"filename": Path(filename).name})

        log.info("stored material %s as %s (%d bytes)", material_id, destination.name, written)

        return StoredFile(
            material_id=material_id,
            filename=Path(filename).name,
            extension=extension,
            size_bytes=written,
            key=str(destination),
        )

    @asynccontextmanager
    async def materialise(self, stored: StoredFile) -> AsyncIterator[Path]:
        """The file is already local, so hand back its path and copy nothing."""
        path = Path(stored.key)
        if not await asyncio.to_thread(path.is_file):
            raise ValidationError(
                "The stored file for this material is missing.",
                {"material_id": str(stored.material_id)},
            )
        yield path

    async def delete(self, material_id: UUID) -> None:
        matches = await asyncio.to_thread(lambda: list(self._root.glob(f"{material_id}.*")))
        for path in matches:
            await asyncio.to_thread(path.unlink, missing_ok=True)

    def purge_all(self) -> None:
        """Drop the whole storage root. Tests and local resets only."""
        shutil.rmtree(self._root, ignore_errors=True)
