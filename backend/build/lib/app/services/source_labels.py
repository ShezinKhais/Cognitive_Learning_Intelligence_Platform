"""What a material's numbered parts are called, for whoever reads a citation.

PDFs have pages and PowerPoint files have slides. Word and text files have
neither, so extraction numbers them by section (see
extraction.number_sections), and a student told "page 3" of a Word file
would look for a page that does not exist (#269).
"""

from __future__ import annotations

from typing import Any, Literal

from sqlalchemy import inspect
from sqlalchemy.orm.base import NO_VALUE

SourceLabel = Literal["Page", "Slide", "Section"]

SLIDE_SUFFIXES = (".pptx", ".ppt")
SECTION_SUFFIXES = (".docx", ".txt")


def source_label(filename: str | None) -> SourceLabel | None:
    """ "Slide", "Section" or "Page" for a material's filename, or None when
    the material is not known."""
    if not filename:
        return None
    name = filename.lower()
    if name.endswith(SLIDE_SUFFIXES):
        return "Slide"
    if name.endswith(SECTION_SUFFIXES):
        return "Section"
    return "Page"


def question_source_label(question: Any) -> SourceLabel | None:
    """The label for a question's source_slide, from its material's filename
    when that was loaded with it. Never queries: a question whose filename
    was not loaded, such as one just created, gives None."""
    state = inspect(question, raiseerr=False)
    if state is None:
        return source_label(getattr(question, "source_filename", None))
    filename = state.attrs.source_filename.loaded_value
    return None if filename is NO_VALUE else source_label(filename)
