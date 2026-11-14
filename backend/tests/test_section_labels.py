"""Word and text files are numbered by section, and everything that names a
part of one says "section" (#269, #282).

Owner: AI 1. The numbering itself is tested in test_extraction.py; these
cover what the numbering must not break: the page limit, the thin-page
warning, and the label a student is shown.
"""

from __future__ import annotations

import uuid
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.models.question import Question
from app.services.extraction import SUPPORTED
from app.services.material_pages import THIN_PAGE_WORDS, page_previews
from app.services.pipeline import MaterialPipeline
from app.services.scoring import build_mcq_feedback, build_mcq_reveal, feedback_payload, score_mcq
from app.services.source_labels import question_source_label, source_label
from app.services.storage import LocalDiskStorage

from .pipeline_support import Embedder, Generator, ProgressLog, feed, settings_for

SECTION_WORDS_OF_TEXT = " ".join(["Gradient descent lowers the loss a little at each step."] * 50)


@pytest.mark.parametrize(
    ("filename", "label"),
    [
        ("Week 3.pdf", "Page"),
        ("Week 3.PPTX", "Slide"),
        ("old.ppt", "Slide"),
        ("Notes.docx", "Section"),
        ("notes.txt", "Section"),
        ("", None),
        (None, None),
    ],
)
def test_each_format_names_its_parts(filename: str | None, label: str | None) -> None:
    assert source_label(filename) == label


def _question(filename: str | None) -> Question:
    question = Question(
        question_id=uuid.uuid4(),
        source_material_id=uuid.uuid4(),
        question_text="What does each step lower?",
        question_type="mcq",
        status="approved",
        difficulty="medium",
        options=["The loss", "The data"],
        correct_option=0,
        source_slide=3,
        source_excerpt="Gradient descent lowers the loss.",
    )
    if filename is not None:
        question.source_filename = filename
    return question


def test_feedback_on_a_word_file_says_section() -> None:
    score = score_mcq(_question("Notes.docx"), 1)

    feedback = build_mcq_feedback(score)

    assert feedback.message == "Incorrect. See section 3 for the supporting material."
    assert build_mcq_reveal(score).message.endswith("See section 3 for the supporting material.")
    assert feedback_payload(uuid.uuid4(), feedback).source_label == "Section"


@pytest.mark.parametrize(
    ("filename", "place"), [("Week 3.pdf", "page 3"), ("Week 3.pptx", "slide 3")]
)
def test_feedback_on_other_files_names_their_page_or_slide(filename: str, place: str) -> None:
    feedback = build_mcq_feedback(score_mcq(_question(filename), 0))

    assert feedback.message == f"Correct. See {place} for the supporting material."


def test_a_question_whose_material_was_not_loaded_keeps_the_old_wording() -> None:
    """Reading the label never runs a query, so a question built in memory
    has none, and the feedback says what it always did."""
    question = _question(None)

    assert question_source_label(question) is None
    assert build_mcq_feedback(score_mcq(question, 0)).message == (
        "Correct. See slide/page 3 for the supporting material."
    )
    assert question_source_label(SimpleNamespace(source_filename="a.docx")) == "Section"


def _element(page: int, text: str) -> SimpleNamespace:
    return SimpleNamespace(element_type="text", content=text, source_page=page)


def test_short_sections_are_not_each_called_thin() -> None:
    """A Word file of headings and short paragraphs has many short sections.
    Each is normal there, so none is flagged when the document has text."""
    elements = [_element(1, SECTION_WORDS_OF_TEXT), _element(2, "A short closing note.")]
    elements += [_element(page, "Summary of the week.") for page in range(3, 9)]

    sections = page_previews(elements, sections=True)
    pages = page_previews(elements)

    assert [preview.is_thin for preview in sections] == [False] * 8
    assert [preview.is_thin for preview in pages] == [False] + [True] * 7


def test_a_document_with_almost_no_text_is_flagged_once() -> None:
    elements = [_element(1, "Week 3."), _element(2, "Read chapter two.")]
    assert sum(len(e.content.split()) for e in elements) < THIN_PAGE_WORDS

    previews = page_previews(elements, sections=True)

    assert [preview.is_thin for preview in previews] == [True, False]


async def test_a_long_text_file_is_not_rejected_for_its_number_of_sections(
    tmp_path: Path,
) -> None:
    """Sections are not pages: a document with more sections than the page
    limit is held back by the character limit, not refused as too many pages."""
    settings = settings_for(tmp_path).model_copy(update={"max_material_pages": 2})
    storage = LocalDiskStorage(settings, allowed=set(SUPPORTED))
    progress = ProgressLog()
    pipeline = MaterialPipeline(
        storage=storage, settings=settings, hub=progress, embedder=Embedder(), generator=Generator()
    )
    text = "\n\n".join([SECTION_WORDS_OF_TEXT] * 5).encode()
    stored = await storage.save(uuid.uuid4(), "notes.txt", feed(text))

    result = await pipeline.job(stored, uuid.uuid4()).run()

    assert result is not None
    assert progress.last(stored.material_id)["stage"] == "done"
