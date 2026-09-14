"""Uploads are written down before they are processed.

Owner: General CS, Phase 2.

The client-supplied filename is the interesting part of these tests. It decides
which parser runs, and it is the only thing about an upload that an attacker
fully controls, so most of what follows is about the name never reaching the
filesystem.

Filesystem calls live in the sync helpers below rather than inline in the
tests. The ASYNC lint rules are on precisely because blocking the event loop is
the failure this workstream exists to prevent, so the tests do not get an
exemption from them.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from pathlib import Path
from uuid import uuid4

import pytest

from app.core.config import Settings
from app.core.errors import ValidationError
from app.services.storage import LocalDiskStorage, validated_extension

SAMPLES = Path(__file__).resolve().parent / "samples"


def read(path_like: str | Path) -> bytes:
    return Path(path_like).read_bytes()


def resolved(path_like: str | Path) -> Path:
    return Path(path_like).resolve()


def listing(directory: Path) -> list[Path]:
    return sorted(directory.iterdir())


def matching(directory: Path, pattern: str) -> list[Path]:
    return sorted(directory.glob(pattern))


def remove(path_like: str | Path) -> None:
    Path(path_like).unlink()


async def feed(data: bytes, block: int = 256) -> AsyncIterator[bytes]:
    """Hand the storage layer an upload the way Starlette would, in pieces."""
    for start in range(0, len(data), block):
        yield data[start : start + block]


def storage(tmp_path: Path, max_bytes: int = 52_428_800) -> LocalDiskStorage:
    return LocalDiskStorage(Settings(upload_storage_dir=str(tmp_path), max_upload_bytes=max_bytes))


async def test_a_real_file_survives_the_round_trip(tmp_path: Path) -> None:
    store = storage(tmp_path)
    original = read(SAMPLES / "lecture.pdf")
    material_id = uuid4()

    stored = await store.save(material_id, "Week 3 Lecture.pdf", feed(original))

    assert stored.size_bytes == len(original)
    assert stored.extension == "pdf"
    # The lecturer's name for the file is kept, but only as something to show.
    assert stored.filename == "Week 3 Lecture.pdf"

    async with store.materialise(stored) as path:
        assert read(path) == original


@pytest.mark.parametrize(
    "hostile",
    [
        "../../../etc/passwd.pdf",
        "..\\..\\windows\\system32\\config.pdf",
        "/etc/shadow.pdf",
        "A" * 300 + ".pdf",
        "lecture\x00.pdf",
    ],
)
async def test_the_client_filename_never_reaches_the_filesystem(
    tmp_path: Path, hostile: str
) -> None:
    """Files are named by material id, so the supplied name cannot escape."""
    store = storage(tmp_path)
    material_id = uuid4()

    stored = await store.save(material_id, hostile, feed(b"%PDF-1.4 minimal"))
    written = resolved(stored.key)

    assert written.parent == resolved(tmp_path)
    assert written.name == f"{material_id}.pdf"


async def test_two_uploads_of_the_same_name_do_not_collide(tmp_path: Path) -> None:
    store = storage(tmp_path)

    first = await store.save(uuid4(), "lecture.pdf", feed(b"first"))
    second = await store.save(uuid4(), "lecture.pdf", feed(b"second"))

    assert first.key != second.key
    assert read(first.key) == b"first"
    assert read(second.key) == b"second"


async def test_an_upload_over_the_ceiling_is_refused(tmp_path: Path) -> None:
    store = storage(tmp_path, max_bytes=1024)

    with pytest.raises(ValidationError):
        await store.save(uuid4(), "big.pdf", feed(b"x" * 2048))


async def test_a_refused_upload_leaves_nothing_behind(tmp_path: Path) -> None:
    """A partial file would be read as a corrupt document, not a failed upload."""
    store = storage(tmp_path, max_bytes=1024)

    with pytest.raises(ValidationError):
        await store.save(uuid4(), "big.pdf", feed(b"x" * 8192))

    assert listing(tmp_path) == []


async def test_an_empty_upload_is_refused(tmp_path: Path) -> None:
    store = storage(tmp_path)

    with pytest.raises(ValidationError):
        await store.save(uuid4(), "empty.pdf", feed(b""))

    assert listing(tmp_path) == []


async def test_a_source_that_fails_midway_leaves_nothing_behind(tmp_path: Path) -> None:
    """A dropped connection must not leave half a lecture on disk."""
    store = storage(tmp_path)

    async def breaks() -> AsyncIterator[bytes]:
        yield b"x" * 512
        raise ConnectionResetError("client went away")

    with pytest.raises(ConnectionResetError):
        await store.save(uuid4(), "lecture.pdf", breaks())

    assert listing(tmp_path) == []


@pytest.mark.parametrize(
    "filename",
    ["notes.exe", "notes.pdf.exe", "archive.zip", "README", "trailing."],
)
async def test_unsupported_formats_are_refused(tmp_path: Path, filename: str) -> None:
    """The extension picks the parser, so notes.pdf.exe is an exe, not a PDF."""
    store = storage(tmp_path)

    with pytest.raises(ValidationError):
        await store.save(uuid4(), filename, feed(b"MZ"))


def test_extension_matching_is_case_insensitive() -> None:
    assert validated_extension("LECTURE.PDF", {"pdf"}) == "pdf"


async def test_a_missing_stored_file_is_reported_not_crashed(tmp_path: Path) -> None:
    store = storage(tmp_path)
    stored = await store.save(uuid4(), "lecture.pdf", feed(b"content"))
    remove(stored.key)

    with pytest.raises(ValidationError):
        async with store.materialise(stored):
            pass


async def test_delete_removes_the_file_and_tolerates_a_second_call(tmp_path: Path) -> None:
    store = storage(tmp_path)
    material_id = uuid4()
    await store.save(material_id, "lecture.pdf", feed(b"content"))

    await store.delete(material_id)
    assert matching(tmp_path, f"{material_id}.*") == []

    # Retrying a cleanup that already ran is not an error.
    await store.delete(material_id)
