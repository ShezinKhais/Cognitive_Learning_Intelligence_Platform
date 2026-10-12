"""How well extraction reads each supported file format.

Owner: AI 1, Phase 8 (#73). For one file it records whether the reader ran
without an error, how many of its pages gave text, how many headings and
images it found, whether the text came out letter-spaced, and how long it
took. No model is needed: this measures the parsers alone.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from pathlib import Path

from app.services.extraction import (
    ExtractedElement,
    extract,
    looks_letter_spaced,
    validate_file,
)

# Element types that carry readable text, as opposed to an image.
TEXT_TYPES = frozenset({"text", "heading", "table"})


@dataclass(frozen=True)
class ParserCoverage:
    file: str
    format: str
    parser: str
    # Whether extraction finished without raising; the rest is empty if not.
    ok: bool
    pages: int
    pages_with_text: int
    headings: int
    leveled_headings: int
    images: int
    letter_spaced: bool
    seconds: float
    error: str = ""


def total_pages(path: str, ext: str) -> int:
    """Pages in a PDF, slides in a deck. Word and text files have no fixed
    pages without rendering, so they count as one."""
    if ext == "pdf":
        from pypdf import PdfReader

        return len(PdfReader(path).pages)
    if ext == "pptx":
        from pptx import Presentation

        return len(Presentation(path).slides)
    return 1


def summarise(
    file: str, ext: str, parser: str, elements: list[ExtractedElement], pages: int, seconds: float
) -> ParserCoverage:
    """The coverage of one file from what extraction returned."""
    text = [e for e in elements if e.el_type in TEXT_TYPES]
    headings = [e for e in elements if e.el_type == "heading"]
    return ParserCoverage(
        file=file,
        format=ext,
        parser=parser,
        ok=True,
        pages=pages,
        pages_with_text=len({e.page for e in text}),
        headings=len(headings),
        leveled_headings=sum(1 for h in headings if h.level > 0),
        images=sum(1 for e in elements if e.el_type == "image"),
        letter_spaced=looks_letter_spaced(" ".join(e.content for e in text)),
        seconds=round(seconds, 2),
    )


def measure(path: str, max_bytes: int = 52_428_800) -> ParserCoverage:
    """Read one file as an upload would, with images, and measure it.

    An error is recorded rather than raised, so one unreadable file does not
    stop the report.
    """
    name = Path(path).name
    ext = Path(path).suffix.lower().lstrip(".")
    start = time.perf_counter()
    try:
        ext = validate_file(path, max_bytes)
        elements, parser, _ = extract(path, ext, with_images=True)
        pages = total_pages(path, ext)
    except Exception as exc:
        return ParserCoverage(
            file=name,
            format=ext,
            parser="",
            ok=False,
            pages=0,
            pages_with_text=0,
            headings=0,
            leveled_headings=0,
            images=0,
            letter_spaced=False,
            seconds=round(time.perf_counter() - start, 2),
            error=f"{type(exc).__name__}: {exc}",
        )
    return summarise(name, ext, parser, elements, pages, time.perf_counter() - start)


def markdown_table(rows: list[ParserCoverage]) -> str:
    lines = [
        "| File | Parser | Read OK | Pages with text | Headings (with level) "
        "| Images | Letter-spaced | Time (s) |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for r in rows:
        if not r.ok:
            lines.append(f"| {r.file} | - | no: {r.error} | - | - | - | - | {r.seconds} |")
            continue
        lines.append(
            f"| {r.file} | {r.parser} | yes | {r.pages_with_text} of {r.pages} "
            f"| {r.headings} ({r.leveled_headings}) | {r.images} "
            f"| {'yes' if r.letter_spaced else 'no'} | {r.seconds} |"
        )
    return "\n".join(lines)
