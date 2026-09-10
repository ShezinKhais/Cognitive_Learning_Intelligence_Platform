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
    looks_letter_spaced,
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
    assert clean_text("Overview Overview", is_heading=True) == "Overview"
    assert clean_text("Data Mining Data Mining", is_heading=True) == "Data Mining"
    assert (
        clean_text("The Global Education Crisis The Global Education", is_heading=True)
        == "The Global Education Crisis"
    )


def test_clean_keeps_real_titles_that_repeat_a_word():
    # regression: a title that legitimately starts and ends with the same word
    # must NOT be truncated (the bug Shezin found).
    assert clean_text("Networks of Networks", is_heading=True) == "Networks of Networks"
    assert (
        clean_text("Business Intelligence for Business", is_heading=True)
        == "Business Intelligence for Business"
    )
    assert (
        clean_text("Deep Learning for Deep Understanding", is_heading=True)
        == "Deep Learning for Deep Understanding"
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


def test_pptx_images_are_not_reported_as_skipped_pages():
    # a normal deck with text + one picture per slide skips nothing
    result = process_material(str(SAMPLES / "lecture.pptx"), material_id=uuid.uuid4())
    assert not any("skipped" in w for w in result.warnings)


def test_utf16_txt_is_decoded_not_mangled(tmp_path):
    # Notepad's "Unicode" save is UTF-16; cp1252 would decode it to garbage
    f = tmp_path / "notes.txt"
    f.write_bytes("Caf\u00e9 notes".encode("utf-16"))
    result = process_material(str(f), material_id=uuid.uuid4())
    text = result.chunks[0].chunk_text
    assert "\x00" not in text
    assert "Caf\u00e9" in text


def test_rejects_overlap_one_less_than_size():
    # step would be 1, so 10k chars would make 10,000 chunks
    els = [ExtractedElement("text", "a" * 10_000, 1)]
    with pytest.raises(ValidationError):
        chunk_elements(els, material_id=uuid.uuid4(), size=500, overlap=499)


def test_rejects_overlap_not_smaller_than_size():
    els = [ExtractedElement("text", "a" * 600, 1)]
    with pytest.raises(ValidationError):
        chunk_elements(els, material_id=uuid.uuid4(), size=500, overlap=500)


def test_chunk_index_records_order():
    els = [ExtractedElement("text", "a" * 1200, 1)]
    chunks = chunk_elements(els, material_id=uuid.uuid4())
    assert [c.chunk_index for c in chunks] == list(range(len(chunks)))


def test_heading_does_not_leak_across_pages():
    # regression: a heading on page 1 must NOT attach to text on a later page
    els = [
        ExtractedElement("heading", "Chapter 1", 1),
        ExtractedElement("text", "intro text", 1),
        ExtractedElement("text", "unrelated body on page 9", 9),
    ]
    chunks = chunk_elements(els, material_id=uuid.uuid4())
    page9 = [c for c in chunks if c.source_page == 9]
    assert page9, "expected a chunk from page 9"
    assert all("Chapter 1" not in c.chunk_text for c in page9)


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


def test_low_quality_pdf_warns_when_docling_missing(monkeypatch):
    # force the docling import to fail so this behaves the same whether or not
    # the extraction extra is installed.
    import builtins

    from app.services import extraction

    real_import = builtins.__import__

    def blocked(name, *args, **kwargs):
        if name.startswith("docling"):
            raise ImportError("docling not installed (simulated)")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", blocked)

    corrupt = [ExtractedElement("text", "T h e G l o b a l E d u c a t i o n C r i s i s " * 3, 1)]
    monkeypatch.setattr(extraction, "read_pdf_pypdf", lambda path: corrupt)

    elements, parser, warnings = extraction.extract("fake.pdf", "pdf")
    assert parser == "pypdf-low-quality"
    assert any("styled text" in w for w in warnings)


def test_corrupt_pypdf_output_upgrades_to_docling(monkeypatch):
    # docling is FORCED available via sys.modules, so this runs identically
    # whether or not the extraction extra is installed.
    import sys
    import types

    from app.services import extraction

    pkg = types.ModuleType("docling")
    mod = types.ModuleType("docling.document_converter")
    mod.DocumentConverter = object
    pkg.document_converter = mod
    monkeypatch.setitem(sys.modules, "docling", pkg)
    monkeypatch.setitem(sys.modules, "docling.document_converter", mod)

    corrupt = [ExtractedElement("text", "T h e G l o b a l E d u c a t i o n C r i s i s " * 3, 1)]
    clean = [ExtractedElement("text", "The Global Education Crisis", 1)]
    monkeypatch.setattr(extraction, "read_pdf_pypdf", lambda path: corrupt)
    monkeypatch.setattr(extraction, "read_pdf_docling", lambda path: clean)

    elements, parser, warnings = extraction.extract("fake.pdf", "pdf")
    assert parser == "docling"
    assert elements == clean


def test_looks_letter_spaced_flags_corrupt_text():
    # pypdf turns styled text into single letters; the guard must catch it
    corrupt = "T h e G l o b a l E d u c a t i o n C r i s i s " * 3
    assert looks_letter_spaced(corrupt) is True


def test_looks_letter_spaced_ignores_normal_text():
    normal = (
        "The global education crisis affects millions of students across many "
        "regions who lack access to quality learning and basic resources today"
    )
    assert looks_letter_spaced(normal) is False


def test_txt_cp1252_is_decoded_not_corrupted(tmp_path):
    # Word/Notepad on Windows produce cp1252; errors="replace" used to turn
    # the dash and accent into U+FFFD. now it must decode cleanly.
    f = tmp_path / "notes.txt"
    f.write_bytes("Education \u2013 caf\u00e9 rules".encode("cp1252"))
    result = process_material(str(f), material_id=uuid.uuid4())
    text = result.chunks[0].chunk_text
    assert "\ufffd" not in text
    assert "caf\u00e9" in text


def test_malformed_file_raises_validation_error(tmp_path):
    # a file with a valid extension but corrupt/garbage bytes should raise a
    # clean ValidationError, not crash with a library error / 500.
    bad = tmp_path / "broken.pdf"
    bad.write_bytes(b"this is not a real pdf at all")
    with pytest.raises(ValidationError):
        process_material(str(bad), material_id=uuid.uuid4())


def test_file_with_no_text_is_rejected(tmp_path):
    f = tmp_path / "blank.txt"
    f.write_text("   \n  ")
    with pytest.raises(ValidationError):
        process_material(str(f), material_id=uuid.uuid4())
