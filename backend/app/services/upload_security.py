"""Security validation for uploaded lecture material.

Owner: Cyber 1, Phase 2.

Filename extensions and client-supplied MIME types are not trusted on their
own. Uploaded material is checked against its real file structure before it
is handed to the extraction pipeline.
"""

from __future__ import annotations

import zipfile
from pathlib import Path

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
    # The PDF header is expected within the first 1024 bytes.
    with path.open("rb") as handle:
        header = handle.read(1024)

    if b"%PDF-" not in header:
        raise ValidationError(
            "File contents do not match a PDF",
            {"filename": path.name},
        )


def _validate_office_zip(path: Path, extension: str) -> None:
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
    # Read only an initial sample here. Full decoding remains the extractor's
    # responsibility. This check is for obvious binary files disguised as TXT.
    with path.open("rb") as handle:
        sample = handle.read(8192)

    binary_signatures = (
        b"MZ",  # Windows executable
        b"\x7fELF",  # Linux executable
        b"%PDF-",  # PDF renamed to TXT
        b"PK\x03\x04",  # ZIP / DOCX / PPTX renamed to TXT
        b"\x89PNG",  # PNG
        b"\xff\xd8\xff",  # JPEG
    )

    if sample.startswith(binary_signatures) or b"\x00" in sample:
        raise ValidationError(
            "Text upload appears to contain binary data",
            {"filename": path.name},
        )


def validate_uploaded_file(
    path: str,
    extension: str,
    content_type: str | None,
) -> None:
    """Validate MIME consistency and the actual file structure."""

    validate_claimed_mime(extension, content_type)

    file_path = Path(path)

    if extension == "pdf":
        _validate_pdf(file_path)
    elif extension in {"docx", "pptx"}:
        _validate_office_zip(file_path, extension)
    elif extension == "txt":
        _validate_text(file_path)
    else:
        raise ValidationError(
            "Unsupported material format",
            {"extension": extension},
        )
