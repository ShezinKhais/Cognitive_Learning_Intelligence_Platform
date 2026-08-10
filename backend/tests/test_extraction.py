"""Tests for the extraction service. Owner: AI 1.

Sample files live in tests/samples/ and are the same ones used for the parser
comparison, so the numbers in extraction.py's docstring can be re-checked.
"""

from __future__ import annotations

import uuid
from pathlib import Path

import pytest

from app.core.errors import ValidationError
from app.services.extraction import (
    ContentChunk,
    ExtractedElement,
    chunk_elements,
    clean_text,
    process_material,
    validate_file,
)

SAMPLES = Path(__file__).parent / "samples"


# --- validation -------------------------------------------------------------


def test_rejects_unsupported_format(tmp_path):
    f = tmp_path / "notes.md"
    f.write_text("hello")
    with pytest.raises(ValidationError):
        validate_file(str(f), max_bytes=1000)


def test_rejects_empty_file(tmp_path):
    f = tmp_path / "empty.txt"
    f.write_text("")
    with pytest.raises(ValidationError):
        validate_file(str(f), max_bytes=1000)


def test_rejects_oversized_file(tmp_path):
    f = tmp_path / "big.txt"
    f.write_text("x" * 500)
    with pytest.raises(ValidationError):
        validate_file(str(f), max_bytes=100)


def test_accepts_each_supported_extension(tmp_path):
    for ext in ("pdf", "pptx", "docx", "txt"):
        f = tmp_path / f"lecture.{ext}"
        f.write_text("content")
        assert validate_file(str(f), max_bytes=1000) == ext


# --- cleaning ---------------------------------------------------------------


def test_clean_collapses_whitespace():
    assert clean_text("The   Global\n\nEducation") == "The Global Education"


def test_clean_removes_docling_duplicate_heading():
    # docling reads the visible title and an overlapping text layer
    assert clean_text("Overview Overview") == "Overview"
    assert clean_text("Data Mining Data Mining") == "Data Mining"
    assert (
        clean_text("The Global Education Crisis The Global Education")
        == "The Global Education Crisis"
    )


def test_clean_keeps_real_titles_that_repeat_a_word():
    # regression: a title that legitimately starts and ends with the same word
    # must NOT be truncated (the bug Shezin found).
    assert clean_text("Networks of Networks") == "Networks of Networks"
    assert clean_text("Business Intelligence for Business") == "Business Intelligence for Business"
    assert (
        clean_text("Deep Learning for Deep Understanding") == "Deep Learning for Deep Understanding"
    )


# --- chunking ---------------------------------------------------------------


def test_chunks_carry_material_id_and_page():
    mid = uuid.uuid4()
    els = [ExtractedElement("text", "a" * 600, 4)]
    chunks = chunk_elements(els, material_id=mid)
    assert all(isinstance(c, ContentChunk) for c in chunks)
    assert all(c.material_id == mid for c in chunks)
    assert all(c.source_page == 4 for c in chunks)


def test_chunks_overlap():
    els = [ExtractedElement("text", "abcdefghij" * 100, 1)]
    chunks = chunk_elements(els, material_id=uuid.uuid4(), size=500, overlap=100)
    assert len(chunks) > 1
    # end of chunk 0 should reappear at the start of chunk 1
    assert chunks[0].chunk_text[-100:] == chunks[1].chunk_text[:100]


def test_heading_is_prefixed_to_following_text():
    els = [
        ExtractedElement("heading", "Planetary Boundaries", 2),
        ExtractedElement("text", "Nine processes regulate stability.", 2),
    ]
    chunks = chunk_elements(els, material_id=uuid.uuid4())
    assert "Planetary Boundaries" in chunks[0].chunk_text


def test_images_are_not_chunked():
    els = [ExtractedElement("image", "[image]", 1)]
    assert chunk_elements(els, material_id=uuid.uuid4()) == []


# --- end to end, one per supported format ------------------------------------


def test_txt_end_to_end(tmp_path):
    f = tmp_path / "notes.txt"
    f.write_text("Education is a right of all children.")
    result = process_material(str(f), material_id=uuid.uuid4())
    assert result.parser_used == "plain-text"
    assert len(result.chunks) == 1


@pytest.mark.skipif(not (SAMPLES / "lecture.pdf").exists(), reason="sample not committed")
def test_pdf_end_to_end():
    result = process_material(str(SAMPLES / "lecture.pdf"), material_id=uuid.uuid4())
    assert result.parser_used in ("pypdf", "docling", "pypdf-low-quality")
    assert result.page_count > 0
    assert result.chunks
    # the letter-spacing bug that pypdf produces on designed decks
    joined = " ".join(c.chunk_text for c in result.chunks)
    assert "T h e  G l o b a l" not in joined


@pytest.mark.skipif(not (SAMPLES / "lecture.pptx").exists(), reason="sample not committed")
def test_pptx_end_to_end():
    result = process_material(str(SAMPLES / "lecture.pptx"), material_id=uuid.uuid4())
    assert result.parser_used == "python-pptx"
    assert any(e.el_type == "heading" for e in result.elements)


@pytest.mark.skipif(not (SAMPLES / "lecture.docx").exists(), reason="sample not committed")
def test_docx_end_to_end():
    result = process_material(str(SAMPLES / "lecture.docx"), material_id=uuid.uuid4())
    assert result.parser_used == "python-docx"
    assert result.chunks


def test_file_with_no_text_is_rejected(tmp_path):
    f = tmp_path / "blank.txt"
    f.write_text("   \n  ")
    with pytest.raises(ValidationError):
        process_material(str(f), material_id=uuid.uuid4())
