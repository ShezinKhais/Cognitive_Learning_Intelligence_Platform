from __future__ import annotations

import zipfile
from pathlib import Path

import pytest

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
    path = write_file(tmp_path / "lecture.pdf", b"%PDF-1.7\nCyber security lecture")

    validate_uploaded_file(str(path), "pdf", "application/pdf")


def test_fake_pdf_is_rejected(tmp_path: Path) -> None:
    path = write_file(tmp_path / "lecture.pdf", b"MZ fake executable")

    with pytest.raises(ValidationError):
        validate_uploaded_file(str(path), "pdf", "application/pdf")


def test_wrong_mime_type_is_rejected(tmp_path: Path) -> None:
    path = write_file(tmp_path / "lecture.pdf", b"%PDF-1.7\nLecture")

    with pytest.raises(ValidationError):
        validate_uploaded_file(str(path), "pdf", "image/png")


def test_generic_octet_stream_is_allowed_for_content_check() -> None:
    validate_claimed_mime("pdf", "application/octet-stream")


def test_fake_docx_zip_is_rejected(tmp_path: Path) -> None:
    path = tmp_path / "lecture.docx"

    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("random.txt", "Not a Word document")

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
        archive.writestr("random.txt", "Not a PowerPoint")

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
    path = write_file(tmp_path / "notes.txt", b"MZ fake executable")

    with pytest.raises(ValidationError):
        validate_uploaded_file(str(path), "txt", "text/plain")


def test_normal_text_file_is_accepted(tmp_path: Path) -> None:
    path = write_file(
        tmp_path / "notes.txt",
        b"Authentication requires valid credentials.",
    )

    validate_uploaded_file(str(path), "txt", "text/plain")
