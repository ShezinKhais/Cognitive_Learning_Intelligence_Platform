"""File extraction service. Turns an uploaded lecture file into content chunks.

Owner: AI 1, Phase 1.

Parser choice was measured on a 35-page slide-export PDF (see the extraction
comparison notebook). Numbers:

    pypdf              15.4s   0 headings    letter-spacing CORRUPTED
    docling, no OCR    18.4s   110 headings  letter-spacing clean
    docling, OCR on    ~5min   116 headings  (GPU; ~27min on CPU)

So: docling for PDF with OCR off. It costs 3 seconds more than pypdf and is the
only one that survives designed decks, where pypdf returns "T h e  G l o b a l"
one letter at a time. That text would go straight into the embedding model as
garbage, so this is a correctness problem, not a tidiness one.

OCR stays off because it added 6 headings out of 116 and returned empty results
on most images of a normal text-layer PDF. It is worth its cost only on scanned
pages, which is a later phase.

pypdf is kept as a fallback: docling's parser is strict and refuses malformed
PDFs that pypdf reads fine (observed on one real file).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path

from app.core.errors import ValidationError

log = logging.getLogger("clip.extraction")

# from Settings.allowed_upload_extensions, kept here so the service can be
# used and tested without loading app config
SUPPORTED = ("pdf", "pptx", "docx", "txt")


# ---------------------------------------------------------------------------
# the shapes. these are internal to processing - nothing here is stored as-is.
# ContentChunk lines up with the SDD's RAG_Chunk table (4.2 Data Dictionary).
# ---------------------------------------------------------------------------


@dataclass
class ExtractedElement:
    """One piece of content pulled out of a file, before chunking."""

    el_type: str  # "text" | "heading" | "image" | "table"
    content: str  # the text, or a placeholder note for images
    page: int  # page number (PDF) or slide number (PPTX). 1 for docx/txt.


@dataclass
class ContentChunk:
    """A chunk ready to be embedded and stored. SDD: RAG_Chunk."""

    chunk_id: int
    material_id: int  # SDD: Source_material_id
    chunk_text: str  # SDD: Chunk_text
    source_page: int  # not in the SDD table, but QuestionOut.source_slide
    # needs it to render "see slide 3" in feedback


@dataclass
class ProcessingResult:
    """What extraction hands back to the upload route.

    THE CONTRACT. Callers depend on these field names, so changing one is a
    breaking change for BBIS (persistence) and for question generation.
    """

    material_id: int
    elements: list[ExtractedElement] = field(default_factory=list)
    chunks: list[ContentChunk] = field(default_factory=list)
    page_count: int = 0
    parser_used: str = ""  # "docling" | "pypdf-fallback" | "python-pptx" | ...
    warnings: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# validation. runs before any parsing, mirrors the SDD pseudocode
# (5.3.3 process_uploaded_material).
# ---------------------------------------------------------------------------


def validate_file(path: str, max_bytes: int) -> str:
    """Check format and size. Returns the lowercase extension.

    Raises ValidationError so the API renders the standard error envelope
    instead of a 500.
    """
    p = Path(path)

    if not p.exists():
        raise ValidationError("File not found", {"path": path})

    ext = p.suffix.lower().lstrip(".")
    if ext not in SUPPORTED:
        # SDD: unsupported_file_format
        raise ValidationError(
            f"Unsupported file format: .{ext}",
            {"supported": list(SUPPORTED), "received": ext},
        )

    size = p.stat().st_size
    if size == 0:
        raise ValidationError("File is empty", {"filename": p.name})
    if size > max_bytes:
        # SDD: file_size_error
        raise ValidationError(
            "File is too large",
            {"size_bytes": size, "max_bytes": max_bytes},
        )

    return ext


# ---------------------------------------------------------------------------
# readers. one per format. all of them return list[ExtractedElement] so the
# rest of the pipeline never has to know which format it came from.
# ---------------------------------------------------------------------------


def read_pdf_docling(path: str) -> list[ExtractedElement]:
    """Primary PDF reader. Layout-aware, OCR disabled."""
    from docling.datamodel.base_models import InputFormat
    from docling.datamodel.pipeline_options import PdfPipelineOptions
    from docling.document_converter import DocumentConverter, PdfFormatOption

    opts = PdfPipelineOptions()
    opts.do_ocr = False  # see module docstring for why

    converter = DocumentConverter(
        format_options={InputFormat.PDF: PdfFormatOption(pipeline_options=opts)}
    )
    doc = converter.convert(path).document

    els: list[ExtractedElement] = []
    for item, _level in doc.iterate_items():
        text = getattr(item, "text", "") or ""
        if not text.strip():
            continue

        # docling tags every item with its layout role, e.g. section_header
        label = str(getattr(item, "label", "")).lower()
        el_type = "heading" if "header" in label or "title" in label else "text"

        # page number lives on the item's provenance, when docling knows it
        page = 1
        prov = getattr(item, "prov", None)
        if prov:
            page = getattr(prov[0], "page_no", 1)

        els.append(ExtractedElement(el_type, clean_text(text), page))

    # record images as placeholders. we do not read what is inside them yet.
    for pic in getattr(doc, "pictures", []):
        page = 1
        prov = getattr(pic, "prov", None)
        if prov:
            page = getattr(prov[0], "page_no", 1)
        els.append(ExtractedElement("image", "[image]", page))

    return els


def read_pdf_pypdf(path: str) -> list[ExtractedElement]:
    """Fallback PDF reader. Lenient: opens malformed files docling refuses.

    Known to mangle designed decks, so only used when docling fails.
    """
    from pypdf import PdfReader

    els = []
    for i, page in enumerate(PdfReader(path).pages):
        txt = page.extract_text() or ""
        if txt.strip():
            els.append(ExtractedElement("text", clean_text(txt), i + 1))
        else:
            els.append(ExtractedElement("image", "[image-only page]", i + 1))
    return els


def read_pptx(path: str) -> list[ExtractedElement]:
    """PPTX reader. python-pptx already gives clean, slide-scoped text, so
    docling adds nothing here."""
    from pptx import Presentation
    from pptx.enum.shapes import MSO_SHAPE_TYPE

    def walk(shapes, page, els):
        """Yield text from shapes, stepping inside groups so their text
        is not lost (a plain shape loop skips grouped content)."""
        parts = []
        for shape in shapes:
            if shape.shape_type == MSO_SHAPE_TYPE.GROUP:
                parts.extend(walk(shape.shapes, page, els))
            elif shape.has_text_frame and shape.text_frame.text.strip():
                parts.append(shape.text_frame.text)
            elif shape.shape_type == MSO_SHAPE_TYPE.PICTURE:
                els.append(ExtractedElement("image", "[image on slide]", page))
        return parts

    els = []
    for i, slide in enumerate(Presentation(path).slides):
        parts = walk(slide.shapes, i + 1, els)
        if parts:
            els.append(ExtractedElement("heading", clean_text(parts[0]), i + 1))
            if len(parts) > 1:
                body = "\n".join(parts[1:])
                els.append(ExtractedElement("text", clean_text(body), i + 1))
    return els


def read_docx(path: str) -> list[ExtractedElement]:
    """DOCX reader. Word styles tell us which paragraphs are headings.

    Also pulls text out of tables, which python-docx keeps separate from
    paragraphs (so a plain paragraph loop misses them entirely).
    """
    from docx import Document

    doc = Document(path)
    els = []

    for para in doc.paragraphs:
        if not para.text.strip():
            continue
        style = (para.style.name or "").lower()
        el_type = "heading" if style.startswith("heading") or style == "title" else "text"
        els.append(ExtractedElement(el_type, clean_text(para.text), 1))

    for table in doc.tables:
        for row in table.rows:
            cells = [c.text.strip() for c in row.cells if c.text.strip()]
            if cells:
                els.append(ExtractedElement("table", clean_text(" | ".join(cells)), 1))

    return els


def read_txt(path: str) -> list[ExtractedElement]:
    """TXT reader. No structure to recover, so it is one block."""
    with open(path, encoding="utf-8", errors="replace") as f:
        text = f.read()
    return [ExtractedElement("text", clean_text(text), 1)] if text.strip() else []


# ---------------------------------------------------------------------------
# cleaning and chunking
# ---------------------------------------------------------------------------


def clean_text(text: str) -> str:
    """SDD: clean_extracted_text. Collapse whitespace, drop repeated phrases.

    The repeat check exists because docling reads both the visible title and an
    overlapping text layer on some slides, producing headings like
    "Overview Overview" and "The Global Education Crisis The Global Education".
    """
    text = " ".join(text.split())

    # if the second half of a short line repeats the start of it, cut it
    if len(text) < 200:
        words = text.split()
        n = len(words)
        # case 1: the whole line is one phrase said exactly twice, e.g.
        # "Overview Overview" or "Data Mining Data Mining". safe to halve.
        if n % 2 == 0:
            half = n // 2
            if words[:half] == words[half:]:
                return " ".join(words[:half])
        # case 2: a 2+ word chunk repeats at the end (docling overlap),
        # e.g. "The Global Education Crisis The Global Education".
        for size in range(n // 2, 1, -1):
            if words[:size] == words[n - size :]:
                return " ".join(words[: n - size])
    return text


def chunk_elements(
    elements: list[ExtractedElement],
    material_id: int,
    size: int = 500,
    overlap: int = 100,
) -> list[ContentChunk]:
    """SDD: split_text_into_chunks. 500 chars with 100 overlap.

    Headings are glued onto the front of the text that follows them, so a chunk
    still says what topic it belongs to once it is on its own in the database.
    That is what makes retrieval and "see slide 3" work.
    """
    chunks: list[ContentChunk] = []
    cid = 0
    current_heading = ""

    for el in elements:
        if el.el_type == "image":
            continue
        if el.el_type == "heading":
            current_heading = el.content
            continue

        text = f"{current_heading}\n{el.content}" if current_heading else el.content

        step = max(size - overlap, 1)
        for start in range(0, len(text), step):
            piece = text[start : start + size]
            if piece.strip():
                chunks.append(ContentChunk(cid, material_id, piece, el.page))
                cid += 1

    return chunks


# ---------------------------------------------------------------------------
# the router + the entry point everyone else calls
# ---------------------------------------------------------------------------


def extract(path: str, ext: str) -> tuple[list[ExtractedElement], str, list[str]]:
    """Pick a reader for the format. Returns elements, parser name, warnings."""
    warnings: list[str] = []

    if ext == "pdf":
        try:
            return read_pdf_docling(path), "docling", warnings
        except Exception as exc:
            # docling refuses malformed PDFs that pypdf tolerates
            log.warning("docling failed on %s, falling back to pypdf: %s", path, exc)
            warnings.append("Document is malformed; extracted with the fallback parser.")
            return read_pdf_pypdf(path), "pypdf-fallback", warnings

    if ext == "pptx":
        return read_pptx(path), "python-pptx", warnings
    if ext == "docx":
        return read_docx(path), "python-docx", warnings
    if ext == "txt":
        return read_txt(path), "plain-text", warnings

    raise ValidationError(f"Unsupported file format: .{ext}", {"received": ext})


def process_material(path: str, material_id: int, max_bytes: int = 52_428_800) -> ProcessingResult:
    """Entry point. Validate, extract, clean, chunk.

    Called by POST /api/v1/materials. Embedding and storage happen after this,
    in Phase 2.
    """
    ext = validate_file(path, max_bytes)
    elements, parser, warnings = extract(path, ext)

    if not any(e.el_type != "image" for e in elements):
        # SDD: no_readable_text_found -> status Failed
        raise ValidationError(
            "No readable text found in this file",
            {"filename": Path(path).name, "parser": parser},
        )

    chunks = chunk_elements(elements, material_id)
    page_count = max((e.page for e in elements), default=0)

    image_only = sum(1 for e in elements if e.el_type == "image")
    if image_only and parser == "pypdf-fallback":
        warnings.append(f"{image_only} page(s) contained no readable text and were skipped.")

    log.info(
        "material %s: %s elements, %s chunks, parser=%s",
        material_id,
        len(elements),
        len(chunks),
        parser,
    )

    return ProcessingResult(
        material_id=material_id,
        elements=elements,
        chunks=chunks,
        page_count=page_count,
        parser_used=parser,
        warnings=warnings,
    )
