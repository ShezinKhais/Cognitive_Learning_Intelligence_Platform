from __future__ import annotations

import zipfile
from pathlib import Path

import pytest

from app.core.config import Settings
from app.core.errors import ValidationError
from app.services.upload_security import (
    validate_claimed_mime,
    validate_uploaded_file,
)


def write_file(path: Path, data: bytes) -> Path:
    path.write_bytes(data)
    return path


def make_office_zip(path: Path, required_entry: str) -> Path:
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("[Content_Types].xml", "<Types></Types>")
        archive.writestr(required_entry, "<document></document>")
    return path


def test_pdf_with_correct_signature_is_accepted(tmp_path: Path) -> None:
    path = write_file(
        tmp_path / "lecture.pdf",
        b"%PDF-1.7\nCyber security lecture",
    )

    validate_uploaded_file(
        str(path),
        "pdf",
        "application/pdf",
    )


def test_fake_pdf_is_rejected(tmp_path: Path) -> None:
    path = write_file(
        tmp_path / "lecture.pdf",
        b"MZ fake executable",
    )

    with pytest.raises(ValidationError):
        validate_uploaded_file(
            str(path),
            "pdf",
            "application/pdf",
        )


def test_executable_with_later_pdf_marker_is_rejected(tmp_path: Path) -> None:
    """A PDF marker later in an executable must not satisfy PDF validation."""
    path = write_file(
        tmp_path / "lecture.pdf",
        b"MZ fake executable payload " + b"A" * 100 + b"%PDF-1.7\nfake",
    )

    with pytest.raises(ValidationError):
        validate_uploaded_file(
            str(path),
            "pdf",
            "application/pdf",
        )


def test_wrong_mime_type_is_rejected(tmp_path: Path) -> None:
    path = write_file(
        tmp_path / "lecture.pdf",
        b"%PDF-1.7\nLecture",
    )

    with pytest.raises(ValidationError):
        validate_uploaded_file(
            str(path),
            "pdf",
            "image/png",
        )


def test_generic_octet_stream_is_allowed_for_content_check() -> None:
    validate_claimed_mime(
        "pdf",
        "application/octet-stream",
    )


def test_fake_docx_zip_is_rejected(tmp_path: Path) -> None:
    path = tmp_path / "lecture.docx"

    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr(
            "random.txt",
            "Not a Word document",
        )

    with pytest.raises(ValidationError):
        validate_uploaded_file(
            str(path),
            "docx",
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        )


def test_valid_docx_structure_is_accepted(tmp_path: Path) -> None:
    path = make_office_zip(
        tmp_path / "lecture.docx",
        "word/document.xml",
    )

    validate_uploaded_file(
        str(path),
        "docx",
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    )


def test_fake_pptx_zip_is_rejected(tmp_path: Path) -> None:
    path = tmp_path / "slides.pptx"

    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr(
            "random.txt",
            "Not a PowerPoint",
        )

    with pytest.raises(ValidationError):
        validate_uploaded_file(
            str(path),
            "pptx",
            "application/vnd.openxmlformats-officedocument.presentationml.presentation",
        )


def test_valid_pptx_structure_is_accepted(tmp_path: Path) -> None:
    path = make_office_zip(
        tmp_path / "slides.pptx",
        "ppt/presentation.xml",
    )

    validate_uploaded_file(
        str(path),
        "pptx",
        "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    )


def test_executable_renamed_as_txt_is_rejected(tmp_path: Path) -> None:
    path = write_file(
        tmp_path / "notes.txt",
        b"MZ fake executable",
    )

    with pytest.raises(ValidationError):
        validate_uploaded_file(
            str(path),
            "txt",
            "text/plain",
        )


def test_binary_nul_after_first_text_window_is_rejected(tmp_path: Path) -> None:
    """Binary content hidden after byte 8192 must still be detected."""
    path = write_file(
        tmp_path / "notes.txt",
        b"A" * 9000 + b"\x00" + b"hidden binary data",
    )

    with pytest.raises(ValidationError):
        validate_uploaded_file(
            str(path),
            "txt",
            "text/plain",
        )


def test_normal_text_file_is_accepted(tmp_path: Path) -> None:
    path = write_file(
        tmp_path / "notes.txt",
        b"Authentication requires valid credentials.",
    )

    validate_uploaded_file(
        str(path),
        "txt",
        "text/plain",
    )


def test_office_archive_with_too_many_entries_is_rejected(
    tmp_path: Path,
) -> None:
    path = tmp_path / "lecture.docx"

    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr(
            "[Content_Types].xml",
            "<Types></Types>",
        )
        archive.writestr(
            "word/document.xml",
            "<document></document>",
        )
        archive.writestr(
            "word/extra1.xml",
            "<extra></extra>",
        )
        archive.writestr(
            "word/extra2.xml",
            "<extra></extra>",
        )

    settings = Settings(
        _env_file=None,
        max_material_archive_entries=3,
    )

    with pytest.raises(ValidationError):
        validate_uploaded_file(
            str(path),
            "docx",
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            settings,
        )


def test_office_archive_exceeding_uncompressed_limit_is_rejected(
    tmp_path: Path,
) -> None:
    path = tmp_path / "slides.pptx"

    with zipfile.ZipFile(
        path,
        "w",
        compression=zipfile.ZIP_DEFLATED,
    ) as archive:
        archive.writestr(
            "[Content_Types].xml",
            "<Types></Types>",
        )
        archive.writestr(
            "ppt/presentation.xml",
            "<presentation></presentation>",
        )
        archive.writestr(
            "ppt/media/large.txt",
            b"A" * 4096,
        )

    settings = Settings(
        _env_file=None,
        max_material_uncompressed_bytes=1024,
    )

    with pytest.raises(ValidationError):
        validate_uploaded_file(
            str(path),
            "pptx",
            "application/vnd.openxmlformats-officedocument.presentationml.presentation",
            settings,
        )


def test_normal_office_archive_stays_within_processing_limits(
    tmp_path: Path,
) -> None:
    path = make_office_zip(
        tmp_path / "lecture.docx",
        "word/document.xml",
    )

    settings = Settings(
        _env_file=None,
        max_material_archive_entries=20,
        max_material_uncompressed_bytes=100_000,
    )

    validate_uploaded_file(
        str(path),
        "docx",
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        settings,
    )
