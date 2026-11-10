"""PDF text from fonts with no character map (#266). Owner: AI 1.

Such a text layer decodes to control characters and shifted letters, which
were chunked and shown to the question generator as if they were real text.
The pages here are stand-ins for pypdf's, so no third-party PDF is committed.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.services import extraction
from app.services.extraction import (
    IMAGE_ONLY_PAGE,
    looks_undecoded,
    readable_lines,
    undecoded_pages_warning,
)

# What pypdf gave for a line of MIT 6.0002 lecture 3: \x01 for each space.
JUNK = "\x12\x1b0\x01*\x01)*\x1a\x1b/\x01E4\x1b.1\x19\x1b/F\x01$\x1b0\x01#\x174\x1b"
FOOTER = "Q>KKKM\x01"


@pytest.mark.parametrize(
    "text",
    [
        "A graph is a set of nodes (vertices) and a set of edges.",
        "Let σ(X) = √(Σ(x − μ)² / |X|), and ∇²h(θ) ≤ 0 for all θ ∈ Θ.",
        " big brackets from an old Symbol font",
        "الانحدار الخطي هو أبسط نماذج التعلم الآلي",
        "Columns:\tname\tscore",
        "",
    ],
)
def test_real_text_is_never_flagged(text):
    assert not looks_undecoded(text)


def test_text_from_a_font_with_no_character_map_is_flagged():
    assert looks_undecoded(JUNK)
    # One stray control character in a long line is not enough.
    assert not looks_undecoded("A perfectly ordinary sentence with one stray\x01 character.")


def test_a_broken_page_keeps_its_readable_lines_and_loses_the_rest():
    text = "\n".join(["Graph-theoretic Models", JUNK, FOOTER, "Eric Grimson"])
    kept, dropped = readable_lines(text)
    assert kept == "Graph-theoretic Models\nEric Grimson"
    # The footer goes too: on a broken page one control character is enough.
    assert dropped == 2


def test_a_clean_page_is_left_exactly_as_it_was():
    text = "Line one\n\nLine two with a\ttab"
    assert readable_lines(text) == (text, 0)


def pdf(monkeypatch, *texts, images=()):
    pages = [SimpleNamespace(extract_text=lambda t=t: t) for t in texts]
    monkeypatch.setattr("pypdf.PdfReader", lambda path: SimpleNamespace(pages=pages))
    monkeypatch.setattr(extraction, "_pypdf_images", lambda page: list(images))


def test_the_reader_drops_junk_and_counts_the_pages(monkeypatch):
    pdf(monkeypatch, "Good page one", f"Title\n{JUNK}", JUNK)
    undecoded: list[int] = []
    elements = extraction.read_pdf_pypdf("fake.pdf", undecoded=undecoded)
    assert [(e.page, e.content) for e in elements] == [
        (1, "Good page one"),
        (2, "Title"),
        # Nothing readable is left, so it is handled as a page with no text.
        (3, IMAGE_ONLY_PAGE),
    ]
    assert all(not any(c < " " for c in e.content) for e in elements)
    assert undecoded == [2, 3]


def test_a_page_left_with_no_text_is_read_with_ocr_when_it_can_be(monkeypatch):
    pdf(monkeypatch, JUNK, images=[b"page picture"])
    elements = extraction.read_pdf_pypdf(
        "fake.pdf", ocr=lambda image: "Breadth first search visits nodes level by level."
    )
    assert [e.content for e in elements] == ["Breadth first search visits nodes level by level."]


def test_the_lecturer_is_told_which_pages_lost_text(monkeypatch):
    monkeypatch.setattr(extraction, "validate_file", lambda path, max_bytes: "pdf")
    pdf(monkeypatch, "Good page one", f"Title\n{JUNK}")
    elements, parser, warnings = extraction.extract("fake.pdf", "pdf")
    assert parser == "pypdf"
    assert warnings == [undecoded_pages_warning([2])]
    assert "page 2" in warnings[0] and "original slides" in warnings[0]


def test_a_long_list_of_pages_is_shortened():
    text = undecoded_pages_warning(list(range(1, 37)))
    assert text.startswith("36 page(s)")
    assert "1, 2, 3, 4, 5, 6, 7, 8, 9, 10, …" in text
