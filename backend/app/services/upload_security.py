"""Security validation for uploaded lecture material.

Owner: Cyber 1, Phase 2.

Filename extensions and client-supplied MIME types are not trusted on their
own. Uploaded material is checked against its real file structure before it
is handed to the extraction pipeline.

Compressed Office documents are also bounded before parsing so a small ZIP
archive cannot expand into excessive memory or disk use.
"""

from __future__ import annotations

import zipfile
from pathlib import Path

from app.core.config import Settings, get_settings
from app.core.errors import ValidationError

EXPECTED_MIME_TYPES: dict[str, set[str]] = {
    "pdf": {"application/pdf"},
    "docx": {"application/vnd.openxmlformats-officedocument.wordprocessingml.document"},
    "pptx": {"application/vnd.openxmlformats-officedocument.presentationml.presentation"},
    "txt": {"text/plain"},
}

# Browsers and API clients sometimes use this when they do not know the exact
# MIME type. It is not trusted as proof; the actual bytes are still checked.
GENERIC_MIME_TYPES = {
    "",
    "application/octet-stream",
}

TEXT_SCAN_CHUNK_SIZE = 8192


def validate_claimed_mime(extension: str, content_type: str | None) -> None:
    """Reject a specific MIME type that contradicts the file extension."""

    claimed = (content_type or "").split(";", 1)[0].strip().lower()

    if claimed in GENERIC_MIME_TYPES:
        return

    expected = EXPECTED_MIME_TYPES.get(extension, set())

    if claimed not in expected:
        raise ValidationError(
            "File content type does not match its extension",
            {
                "extension": extension,
                "content_type": claimed,
                "expected": sorted(expected),
            },
        )


def _validate_pdf(path: Path) -> None:
    """Require the PDF signature at the actual start of the file."""

    with path.open("rb") as handle:
        header = handle.read(5)

    if header != b"%PDF-":
        raise ValidationError(
            "File contents do not match a PDF",
            {"filename": path.name},
        )


def _validate_archive_limits(
    archive: zipfile.ZipFile,
    path: Path,
    settings: Settings,
) -> None:
    """Reject Office archives that are unsafe to expand or process."""

    entries = archive.infolist()

    if len(entries) > settings.max_material_archive_entries:
        raise ValidationError(
            "Office document contains too many internal files",
            {
                "filename": path.name,
                "entries": len(entries),
                "max_entries": settings.max_material_archive_entries,
            },
        )

    total_uncompressed = 0

    for entry in entries:
        total_uncompressed += entry.file_size

        if total_uncompressed > settings.max_material_uncompressed_bytes:
            raise ValidationError(
                "Office document expands beyond the processing limit",
                {
                    "filename": path.name,
                    "max_uncompressed_bytes": settings.max_material_uncompressed_bytes,
                },
            )

        # Office files should not contain encrypted ZIP entries. The parsers
        # cannot safely inspect them and they would bypass content validation.
        if entry.flag_bits & 0x1:
            raise ValidationError(
                "Encrypted Office document entries are not supported",
                {"filename": path.name},
            )


def _validate_office_zip(
    path: Path,
    extension: str,
    settings: Settings,
) -> None:
    """Check Office structure and enforce archive processing limits."""

    if not zipfile.is_zipfile(path):
        raise ValidationError(
            f"File contents do not match a {extension.upper()} document",
            {"filename": path.name},
        )

    required_entry = {
        "docx": "word/document.xml",
        "pptx": "ppt/presentation.xml",
    }[extension]

    try:
        with zipfile.ZipFile(path) as archive:
            _validate_archive_limits(
                archive,
                path,
                settings,
            )

            names = set(archive.namelist())

            if "[Content_Types].xml" not in names or required_entry not in names:
                raise ValidationError(
                    f"File contents do not match a {extension.upper()} document",
                    {"filename": path.name},
                )

    except (zipfile.BadZipFile, OSError) as exc:
        raise ValidationError(
            f"File contents do not match a {extension.upper()} document",
            {"filename": path.name},
        ) from exc


def _validate_text(path: Path) -> None:
    """Reject binary files disguised as plain text.

    Binary signatures are checked at the actual beginning of the file, while
    the complete file is scanned for NUL bytes so binary data cannot be hidden
    after the first sample window.
    """

    binary_signatures = (
        b"MZ",  # Windows executable
        b"\x7fELF",  # Linux executable
        b"%PDF-",  # PDF renamed to TXT
        b"PK\x03\x04",  # ZIP / DOCX / PPTX renamed to TXT
        b"\x89PNG",  # PNG
        b"\xff\xd8\xff",  # JPEG
    )

    with path.open("rb") as handle:
        first_chunk = handle.read(TEXT_SCAN_CHUNK_SIZE)

        if first_chunk.startswith(binary_signatures) or b"\x00" in first_chunk:
            raise ValidationError(
                "Text upload appears to contain binary data",
                {"filename": path.name},
            )

        while True:
            chunk = handle.read(TEXT_SCAN_CHUNK_SIZE)

            if not chunk:
                break

            if b"\x00" in chunk:
                raise ValidationError(
                    "Text upload appears to contain binary data",
                    {"filename": path.name},
                )


def validate_uploaded_file(
    path: str,
    extension: str,
    content_type: str | None,
    settings: Settings | None = None,
) -> None:
    """Validate MIME, file structure and processing safety limits."""

    validate_claimed_mime(extension, content_type)

    file_path = Path(path)
    effective_settings = settings or get_settings()

    if extension == "pdf":
        _validate_pdf(file_path)
    elif extension in {"docx", "pptx"}:
        _validate_office_zip(
            file_path,
            extension,
            effective_settings,
        )
    elif extension == "txt":
        _validate_text(file_path)
    else:
        raise ValidationError(
            "Unsupported material format",
            {"extension": extension},
        )
