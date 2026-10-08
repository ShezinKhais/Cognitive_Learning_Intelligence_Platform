"""Tests for the extraction service. Owner: AI 1.

Sample files live in tests/samples/ and are the same ones used for the parser
comparison, so the numbers in extraction.py's docstring can be re-checked.
"""

from __future__ import annotations

import uuid
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.core.errors import ValidationError
from app.services.extraction import (
    ContentChunk,
    ExtractedElement,
    _docling_elements,
    _docx_heading_level,
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


def test_long_unbroken_token_preserves_real_overlap():
    token = "a" * 400 + "b" * 100 + "c" * 400 + "d" * 100 + "e" * 200
    els = [ExtractedElement("text", token, 1)]

    chunks = chunk_elements(
        els,
        material_id=uuid.uuid4(),
        size=500,
        overlap=100,
    )

    assert len(chunks) > 1
    assert chunks[0].chunk_text[-100:] == chunks[1].chunk_text[:100]
    assert all(len(chunk.chunk_text) <= 500 for chunk in chunks)


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


def test_chunks_never_exceed_the_size_limit():
    els = [ExtractedElement("text", "Transfer learning is useful. " * 60, 1)]
    chunks = chunk_elements(els, material_id=uuid.uuid4(), size=500, overlap=100)
    assert all(len(c.chunk_text) <= 500 for c in chunks)


def test_prose_is_split_on_sentence_boundaries():
    """Character slicing cut words in half, which the embedder then saw as
    broken tokens at both edges of every chunk."""
    els = [ExtractedElement("text", "Transfer learning is useful. " * 60, 1)]
    chunks = chunk_elements(els, material_id=uuid.uuid4(), size=500, overlap=100)
    assert len(chunks) > 1
    for chunk in chunks[:-1]:
        assert chunk.chunk_text.rstrip().endswith(".")


def test_small_blocks_on_one_page_are_packed_together():
    """A PPTX slide arrives as one element per bullet. Chunking per element
    embedded four-word fragments with no surrounding context."""
    els = [ExtractedElement("text", f"Bullet point number {i}", 3) for i in range(6)]
    chunks = chunk_elements(els, material_id=uuid.uuid4())
    assert len(chunks) == 1
    assert "number 0" in chunks[0].chunk_text
    assert "number 5" in chunks[0].chunk_text


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


def test_consecutive_chunks_actually_share_text():
    """The older overlap test uses a repeating pattern, so every 100-character
    window looks alike and it passes with or without overlap. Total length is
    the honest check: overlapping chunks must exceed the input."""
    text = "Transfer learning reuses a pretrained network. " * 30
    els = [ExtractedElement("text", text, 1)]

    chunks = chunk_elements(els, material_id=uuid.uuid4(), size=500, overlap=100)

    assert len(chunks) > 1
    assert sum(len(c.chunk_text) for c in chunks) > len(text)


def test_heading_appears_once_per_chunk_not_once_per_bullet():
    """Prefixing the heading to every element repeated it for every bullet on
    a slide, wasting the chunk budget and skewing the embedding."""
    els = [ExtractedElement("heading", "Transfer learning", 3)] + [
        ExtractedElement("text", f"Bullet point number {i}", 3) for i in range(6)
    ]

    chunks = chunk_elements(els, material_id=uuid.uuid4())

    assert len(chunks) == 1
    assert chunks[0].chunk_text.count("Transfer learning") == 1


def test_an_oversized_heading_cannot_break_the_size_limit():
    """A heading longer than a chunk would drive the budget negative."""
    els = [
        ExtractedElement("heading", "H" * 800, 1),
        ExtractedElement("text", "Some body text about normalisation.", 1),
    ]

    chunks = chunk_elements(els, material_id=uuid.uuid4(), size=500, overlap=100)

    assert chunks
    assert all(len(c.chunk_text) <= 500 for c in chunks)


def test_a_second_heading_on_a_page_applies_to_the_text_after_it():
    """DOCX puts every element on page 1, so grouping by page alone filed a
    whole document under its first heading."""
    els = [
        ExtractedElement("heading", "Normalisation", 1),
        ExtractedElement("text", "Redundancy is removed from the schema.", 1),
        ExtractedElement("heading", "Indexing", 1),
        ExtractedElement("text", "A B-tree keeps lookups fast.", 1),
    ]

    chunks = chunk_elements(els, material_id=uuid.uuid4())

    indexing = [c for c in chunks if "B-tree" in c.chunk_text]
    assert indexing
    assert all("Normalisation" not in c.chunk_text for c in indexing)
    assert any("Indexing" in c.chunk_text for c in indexing)


# --- heading paths (Phase 6, #127) -------------------------------------------


def _first_line(chunk: ContentChunk) -> str:
    return chunk.chunk_text.split("\n", 1)[0]


def test_a_chunk_starts_with_the_full_path_of_its_headings():
    els = [
        ExtractedElement("heading", "Chapter 2", 1, level=1),
        ExtractedElement("heading", "2.1 Layers", 1, level=2),
        ExtractedElement("text", "A dense layer connects every input to every output.", 1),
    ]

    [chunk] = chunk_elements(els, material_id=uuid.uuid4())

    assert _first_line(chunk) == "Chapter 2 > 2.1 Layers"


def test_a_sibling_heading_replaces_the_one_before_it():
    els = [
        ExtractedElement("heading", "Chapter 2", 1, level=1),
        ExtractedElement("heading", "2.1 Layers", 1, level=2),
        ExtractedElement("text", "Dense layers.", 1),
        ExtractedElement("heading", "2.2 Activations", 1, level=2),
        ExtractedElement("text", "ReLU keeps positive values.", 1),
    ]

    chunks = chunk_elements(els, material_id=uuid.uuid4())

    relu = next(c for c in chunks if "ReLU" in c.chunk_text)
    assert _first_line(relu) == "Chapter 2 > 2.2 Activations"
    assert "Dense layers" not in relu.chunk_text


def test_a_higher_heading_closes_the_sections_inside_the_last_one():
    els = [
        ExtractedElement("heading", "Chapter 2", 1, level=1),
        ExtractedElement("heading", "2.1 Layers", 1, level=2),
        ExtractedElement("text", "Dense layers.", 1),
        ExtractedElement("heading", "Chapter 3", 1, level=1),
        ExtractedElement("text", "Training loops.", 1),
    ]

    chunks = chunk_elements(els, material_id=uuid.uuid4())

    training = next(c for c in chunks if "Training" in c.chunk_text)
    assert _first_line(training) == "Chapter 3"


def test_a_section_runs_on_across_pages():
    """A document section continues onto the next page. Only headings with no
    level, such as slide titles, stop at the end of their page."""
    els = [
        ExtractedElement("heading", "Chapter 2", 4, level=1),
        ExtractedElement("text", "Start of the chapter.", 4),
        ExtractedElement("text", "The chapter continues here.", 5),
    ]

    chunks = chunk_elements(els, material_id=uuid.uuid4())

    page5 = next(c for c in chunks if c.source_page == 5)
    assert _first_line(page5) == "Chapter 2"


def test_a_path_too_long_for_its_chunk_drops_the_outermost_headings():
    els = [
        ExtractedElement("heading", "A" * 150, 1, level=1),
        ExtractedElement("heading", "B" * 150, 1, level=2),
        ExtractedElement("heading", "Backpropagation", 1, level=3),
        ExtractedElement("text", "Gradients flow backwards through the network.", 1),
    ]

    [chunk] = chunk_elements(els, material_id=uuid.uuid4(), size=500, overlap=100)

    assert _first_line(chunk) == f"{'B' * 150} > Backpropagation"
    assert len(chunk.chunk_text) <= 500


@pytest.mark.parametrize(
    ("style", "level"),
    [
        ("title", 1),
        ("heading 1", 1),
        ("heading 3", 3),
        ("heading", 1),
        ("normal", None),
        ("list paragraph", None),
    ],
)
def test_word_heading_styles_give_their_level(style, level):
    assert _docx_heading_level(style) == level


class _FakeItem:
    def __init__(self, label, text="", page=1, level=None, table=None):
        self.label = label
        self.text = text
        self.prov = [SimpleNamespace(page_no=page)]
        if level is not None:
            self.level = level
        self._table = table

    def export_to_markdown(self, doc=None):
        if self._table is None:
            raise ValueError("not a table")
        return self._table


class _FakeDoclingDocument:
    def __init__(self, items):
        self.items = items

    def iterate_items(self):
        return ((item, 0) for item in self.items)


def test_docling_output_keeps_levels_lists_and_tables():
    table = "| Layer | Units |\n|---|---|\n| Dense | 64 |"
    doc = _FakeDoclingDocument(
        [
            _FakeItem("DocItemLabel.PAGE_HEADER", "CS101 - Lecture 3", page=2),
            _FakeItem("title", "Neural Networks", page=2),
            _FakeItem("DocItemLabel.SECTION_HEADER", "2.1 Layers", page=2, level=2),
            _FakeItem("text", "Layers are stacked.", page=2),
            _FakeItem("list_item", "Dense", page=2),
            _FakeItem("table", page=3, table=table),
            _FakeItem("picture", page=3),
            _FakeItem("page_footer", "Page 3", page=3),
        ]
    )

    els = _docling_elements(doc)

    assert [(e.el_type, e.content, e.page, e.level) for e in els] == [
        ("heading", "Neural Networks", 2, 1),
        ("heading", "2.1 Layers", 2, 2),
        ("text", "Layers are stacked.", 2, 0),
        ("text", "- Dense", 2, 0),
        ("table", table, 3, 0),
        ("image", "[image]", 3, 0),
    ]


def test_a_docling_table_that_cannot_be_exported_does_not_lose_the_file():
    doc = _FakeDoclingDocument(
        [_FakeItem("table", page=1), _FakeItem("text", "Still read.", page=1)]
    )

    assert [e.content for e in _docling_elements(doc)] == ["Still read."]
