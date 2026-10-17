"""Parser coverage for the AI evaluation report (Phase 8, AI 1, #73)."""

from pathlib import Path

from app.services.extraction import ExtractedElement
from app.services.parser_coverage import markdown_table, measure, summarise

SAMPLES = Path(__file__).parent / "samples"


def test_summarise_counts_text_pages_headings_and_images():
    elements = [
        ExtractedElement("heading", "Logistic regression", 1, level=1),
        ExtractedElement("text", "Models a binary response.", 1),
        ExtractedElement("heading", "Odds", 2),
        ExtractedElement("image", "[image]", 3),
    ]
    row = summarise("x.pdf", "pdf", "pypdf", elements, pages=3, seconds=0.123)
    assert (row.pages_with_text, row.pages) == (2, 3)
    assert (row.headings, row.leveled_headings) == (2, 1)
    assert row.images == 1
    assert row.letter_spaced is False
    assert row.seconds == 0.12


def test_summarise_flags_letter_spaced_text():
    spaced = ExtractedElement("text", "T h e G l o b a l E d u c a t i o n C r i s i s " * 3, 1)
    assert summarise("x.pdf", "pdf", "pypdf", [spaced], 1, 0).letter_spaced is True


def test_each_sample_format_is_read():
    for name in ("lecture.pdf", "lecture.pptx", "lecture.docx", "lecture.txt"):
        row = measure(str(SAMPLES / name))
        assert row.ok, row.error
        assert row.pages_with_text > 0


def test_the_sample_deck_reports_its_slides_and_pictures():
    row = measure(str(SAMPLES / "lecture.pptx"))
    assert row.parser == "python-pptx"
    assert row.pages == 18
    assert row.images > 0


def test_a_corrupt_file_is_recorded_not_raised(tmp_path):
    broken = tmp_path / "broken.pdf"
    broken.write_bytes(b"%PDF-1.4 not really a PDF")
    row = measure(str(broken))
    assert row.ok is False
    assert row.error
    assert "| broken.pdf | - | no:" in markdown_table([row])
