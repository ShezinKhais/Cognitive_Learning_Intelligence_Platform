"""File extraction service. Turns an uploaded lecture file into content chunks.

Owner: AI 1, Phase 1.

Parser choice was measured on a 35-page slide-export PDF (see the extraction
comparison notebook). Numbers:

    pypdf              15.4s   0 headings    letter-spacing CORRUPTED
    docling, no OCR    18.4s   110 headings  letter-spacing clean
    docling, OCR on    ~5min   116 headings  (GPU; ~27min on CPU)

So (Option B): pypdf is the DEFAULT PDF parser - it is light and installs
everywhere, including CI and newest macOS, where docling's pypdfium2 dependency
has no build. A quality guard (looks_letter_spaced) checks pypdf's output for
the letter-spacing corruption above; when it fires and docling is installed,
extraction upgrades to docling. When docling is absent, the pypdf result is
kept but flagged as "pypdf-low-quality" with an honest warning, so corrupted
text never flows silently into the embedding model.

OCR stays off because it added 6 headings out of 116 and returned empty results
on most images of a normal text-layer PDF. It is worth its cost only on scanned
pages, which is a later phase.
"""

from __future__ import annotations

import io
import logging
import re
import uuid
from dataclasses import dataclass, field
from pathlib import Path

from app.core.errors import ValidationError

log = logging.getLogger("clip.extraction")

# The formats extraction can read, and the MIME type of each. A stored upload
# is labelled by its validated extension through this table rather than by the
# client's Content-Type header, and a specific claimed type that contradicts it
# is refused by app.services.upload_security. Kept here, not read from
# Settings.allowed_upload_extensions, so the service can be used and tested
# without loading app config.
CONTENT_TYPES: dict[str, str] = {
    "pdf": "application/pdf",
    "pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "txt": "text/plain",
}
SUPPORTED = tuple(CONTENT_TYPES)

# What an image is recorded as until something describes it. An image still
# holding one of these says nothing a student could search for, so it is left
# out of chunks; a captioned image is chunked like text, where it stood.
IMAGE_ONLY_PAGE = "[image-only page]"
IMAGE_PLACEHOLDERS = frozenset({"[image]", "[image on slide]", IMAGE_ONLY_PAGE})
# Images taken from one page of a PDF with text on it, largest first: a slide
# with more than this is a gallery, not a diagram to explain.
MAX_IMAGES_PER_PAGE = 3


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
    # Headings only: 1 for a top-level section, 2 for one inside it, and so on,
    # where the format says. 0 is a heading with no known level, such as a
    # slide title: it applies to its own page only.
    level: int = 0
    # Images only, and only when asked for: the image itself, as PNG or JPEG
    # bytes, for a vision model to caption. Never stored.
    image: bytes | None = field(default=None, repr=False, compare=False)


@dataclass
class ContentChunk:
    """A chunk ready to be embedded and stored. SDD: RAG_Chunk."""

    chunk_id: uuid.UUID  # matches rag_chunk.chunk_id (UUID)
    chunk_index: int  # 0-based order within the material; UUIDs alone lose it
    material_id: uuid.UUID  # SDD: Source_material_id, matches rag_chunk (UUID)
    chunk_text: str  # SDD: Chunk_text
    source_page: int  # not in the SDD table, but QuestionOut.source_slide
    # needs it to render "see slide 3" in feedback


@dataclass
class ProcessingResult:
    """What extraction hands back to the upload route.

    THE CONTRACT. Callers depend on these field names, so changing one is a
    breaking change for BBIS (persistence) and for question generation.
    """

    material_id: uuid.UUID
    elements: list[ExtractedElement] = field(default_factory=list)
    chunks: list[ContentChunk] = field(default_factory=list)
    # highest page/slide seen. PDF and PPTX report real pages; DOCX and TXT
    # always report 1 because Word/plain-text have no fixed pagination without
    # rendering. BBIS persists this as-is - it is a known format limitation.
    page_count: int = 0
    parser_used: str = ""  # "pypdf" | "docling" | "pypdf-low-quality" | "python-pptx" | ...
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


def read_pdf_docling(path: str, with_images: bool = False) -> list[ExtractedElement]:
    """Primary PDF reader. Layout-aware, OCR disabled."""
    from docling.datamodel.base_models import InputFormat
    from docling.datamodel.pipeline_options import PdfPipelineOptions
    from docling.document_converter import DocumentConverter, PdfFormatOption

    opts = PdfPipelineOptions()
    opts.do_ocr = False  # see module docstring for why
    # Rendering each picture costs memory and time, so only when asked for.
    opts.generate_picture_images = with_images

    converter = DocumentConverter(
        format_options={InputFormat.PDF: PdfFormatOption(pipeline_options=opts)}
    )
    return _docling_elements(converter.convert(path).document, with_images=with_images)


# Running text docling finds at the top and bottom of every page, such as
# "CS101 - Lecture 3" or a page number. Not content, and taken for headings
# they would head every page's chunks.
_DOCLING_SKIPPED = {"page_header", "page_footer"}


def _docling_page(item) -> int:
    """The page an item is on, from its provenance, when docling knows it."""
    prov = getattr(item, "prov", None)
    return getattr(prov[0], "page_no", 1) if prov else 1


def _docling_picture(item, doc) -> bytes | None:
    """A docling picture as PNG bytes, or None when docling did not render it."""
    try:
        picture = item.get_image(doc)
    except Exception:
        return None
    if picture is None:
        return None
    buffer = io.BytesIO()
    picture.save(buffer, format="PNG")
    return buffer.getvalue()


def _docling_elements(doc, with_images: bool = False) -> list[ExtractedElement]:
    """A docling document as elements, in reading order, kept as Markdown.

    Headings carry their section level, so chunks can say where they sit
    ("Chapter 2 > 2.1 Layers"). List items keep their bullet, and a table is
    its Markdown table: a table item has no text, so reading text alone lost
    every table. Images stay placeholders, carrying the picture itself when
    `with_images` asks for it.
    """
    els: list[ExtractedElement] = []
    for item, _depth in doc.iterate_items():
        label = str(getattr(item, "label", "")).lower().rsplit(".", 1)[-1]
        if label in _DOCLING_SKIPPED:
            continue
        page = _docling_page(item)

        if label == "table":
            try:
                table = (item.export_to_markdown(doc=doc) or "").strip()
            except Exception:
                # One unreadable table is not a reason to lose the file.
                log.warning("could not export a table on page %s", page)
                continue
            if table:
                els.append(ExtractedElement("table", table, page))
            continue
        if label == "picture":
            image = _docling_picture(item, doc) if with_images else None
            els.append(ExtractedElement("image", "[image]", page, image=image))
            continue

        text = getattr(item, "text", "") or ""
        if not text.strip():
            continue
        if label == "title":
            els.append(ExtractedElement("heading", clean_text(text, is_heading=True), page, 1))
        elif label == "section_header":
            level = max(1, int(getattr(item, "level", 1) or 1))
            els.append(ExtractedElement("heading", clean_text(text, is_heading=True), page, level))
        elif label == "list_item":
            els.append(ExtractedElement("text", f"- {clean_text(text)}", page))
        else:
            els.append(ExtractedElement("text", clean_text(text), page))
    return els


def looks_letter_spaced(text: str) -> bool:
    """Detect pypdf's letter-spacing corruption on designed decks.

    pypdf turns styled text into single characters separated by spaces,
    e.g. "The Global" becomes "T h e  G l o b a l". We spot this by
    checking what fraction of "words" are a single character.
    """
    words = text.split()
    if len(words) < 20:
        return False
    singles = sum(1 for w in words if len(w) == 1)
    return singles / len(words) > 0.4


def read_pdf_pypdf(path: str, with_images: bool = False) -> list[ExtractedElement]:
    """Default PDF reader (Option B). Lightweight, installs everywhere.

    Known to mangle designed decks (letter-spacing), so callers should run
    looks_letter_spaced() on the output and upgrade to docling if available.

    With `with_images`, a page's embedded images come too, so they can be
    captioned: a page with no text is recorded as its largest image, and a
    page with text gains its largest few after the text.
    """
    from pypdf import PdfReader

    els = []
    for i, page in enumerate(PdfReader(path).pages):
        txt = page.extract_text() or ""
        images = _pypdf_images(page) if with_images else []
        if txt.strip():
            els.append(ExtractedElement("text", clean_text(txt), i + 1))
            els.extend(
                ExtractedElement("image", "[image]", i + 1, image=data)
                for data in images[:MAX_IMAGES_PER_PAGE]
            )
        else:
            els.append(
                ExtractedElement(
                    "image", IMAGE_ONLY_PAGE, i + 1, image=images[0] if images else None
                )
            )
    return els


def _pypdf_images(page) -> list[bytes]:
    """A page's embedded images, largest first. An image pypdf cannot decode
    is left out: it is one image, not a reason to lose the page."""
    found = []
    try:
        for image in page.images:
            try:
                found.append(image.data)
            except Exception:
                continue
    except Exception:
        log.debug("could not list the images on a page", exc_info=True)
    return sorted(found, key=len, reverse=True)


def read_pptx(path: str, with_images: bool = False) -> list[ExtractedElement]:
    """PPTX reader. python-pptx already gives clean, slide-scoped text, so
    docling adds nothing here."""
    from pptx import Presentation
    from pptx.enum.shapes import MSO_SHAPE_TYPE

    def walk(shapes, page, images):
        """Yield text from shapes, stepping inside groups so their text
        is not lost. Images are collected separately and appended after the
        slide's text, so elements keep document order (heading, body, images)
        instead of images always landing first."""
        parts = []
        for shape in shapes:
            if shape.shape_type == MSO_SHAPE_TYPE.GROUP:
                parts.extend(walk(shape.shapes, page, images))
            elif shape.has_text_frame and shape.text_frame.text.strip():
                parts.append(shape.text_frame.text)
            elif shape.shape_type == MSO_SHAPE_TYPE.PICTURE:
                data = shape.image.blob if with_images else None
                images.append(ExtractedElement("image", "[image on slide]", page, image=data))
        return parts

    els = []
    for i, slide in enumerate(Presentation(path).slides):
        slide_images: list[ExtractedElement] = []
        parts = walk(slide.shapes, i + 1, slide_images)
        if not parts:
            els.extend(slide_images)
            continue
        # use the real title placeholder if the slide has one, otherwise fall
        # back to the first shape. parts[0] is just first in z-order, which is
        # often NOT the title, so it would tag chunks with the wrong topic.
        title = None
        if slide.shapes.title is not None and slide.shapes.title.text.strip():
            title = slide.shapes.title.text
        heading = title if title else parts[0]
        els.append(ExtractedElement("heading", clean_text(heading, is_heading=True), i + 1))
        # body is everything except the shape we used as the heading
        body_parts = [p for p in parts if p != heading]
        if body_parts:
            body = "\n".join(body_parts)
            els.append(ExtractedElement("text", clean_text(body), i + 1))
        els.extend(slide_images)
    return els


def _docx_heading_level(style: str) -> int | None:
    """The outline level of a Word paragraph style, or None for body text.

    "Title" and "Heading 1" are top level, "Heading 2" sits inside a
    "Heading 1", and so on. A heading style with no number is top level.
    """
    if style == "title":
        return 1
    if not style.startswith("heading"):
        return None
    number = style.removeprefix("heading").strip()
    return int(number) if number.isdigit() and int(number) > 0 else 1


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
        level = _docx_heading_level(style)
        if level is None:
            els.append(ExtractedElement("text", clean_text(para.text), 1))
        else:
            els.append(
                ExtractedElement("heading", clean_text(para.text, is_heading=True), 1, level)
            )

    for table in doc.tables:
        for row in table.rows:
            cells = [c.text.strip() for c in row.cells if c.text.strip()]
            if cells:
                els.append(ExtractedElement("table", clean_text(" | ".join(cells)), 1))

    return els


def read_txt(path: str) -> list[ExtractedElement]:
    """TXT reader. No structure to recover, so it is one block.

    utf-8-sig first (strips Word/Notepad's BOM), then a cp1252 retry for
    Windows files. errors="replace" would silently turn dashes and accents
    into U+FFFD, corrupting the text instead of decoding it.
    """
    raw = Path(path).read_bytes()

    # UTF-16 first: Notepad's "Unicode" option writes it, and cp1252 would
    # happily decode those bytes into garbage with embedded NULs.
    if raw[:2] in (b"\xff\xfe", b"\xfe\xff"):
        try:
            text = raw.decode("utf-16")
        except UnicodeDecodeError as exc:
            raise ValidationError(
                "Text file is not valid UTF-16",
                {"filename": Path(path).name},
            ) from exc
    else:
        try:
            text = raw.decode("utf-8-sig")
        except UnicodeDecodeError:
            try:
                text = raw.decode("cp1252")
            except UnicodeDecodeError as exc:
                raise ValidationError(
                    "Text file is not UTF-8 or Windows-1252 encoded",
                    {"filename": Path(path).name},
                ) from exc

    # a NUL means we decoded with the wrong codec (cp1252 never errors, it
    # just produces nonsense), so reject rather than embed garbage.
    if "\x00" in text:
        raise ValidationError(
            "Text file encoding could not be determined",
            {"filename": Path(path).name},
        )

    return [ExtractedElement("text", clean_text(text), 1)] if text.strip() else []


# ---------------------------------------------------------------------------
# cleaning and chunking
# ---------------------------------------------------------------------------


def clean_text(text: str, is_heading: bool = False) -> str:
    """SDD: clean_extracted_text. Collapse whitespace; on headings only, drop
    docling's repeated-phrase duplication.

    The repeat check runs on headings only, because that is where docling's
    duplication happens ("Overview Overview"). Running it on body text would
    wrongly mutate real sentences like "Rain in Spain ... Rain in Spain".
    """
    text = " ".join(text.split())

    # repeat-strip is heading-only, to avoid mangling real body text
    if is_heading and len(text) < 200:
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


def _split_oversized(text: str, size: int, overlap: int = 0) -> list[str]:
    """A block too big for one chunk: sentences, then words, then characters.

    Each level is a fallback for the one above. Characters are the last resort
    and only reached by a single token longer than a whole chunk - a URL or a
    base64 blob, where there is no boundary to respect anyway.
    """
    if len(text) <= size:
        return [text]

    pieces: list[str] = []
    for sentence in re.split(r"(?<=[.!?])\s+", text):
        if not sentence.strip():
            continue
        if len(sentence) <= size:
            pieces.append(sentence)
            continue

        current = ""
        for word in sentence.split():
            if len(word) > size:
                if current:
                    pieces.append(current)
                    current = ""
                min_step = max(1, size // 10)
                char_overlap = min(overlap, max(0, size - min_step))
                step = max(1, size - char_overlap)
                for start in range(0, len(word), step):
                    pieces.append(word[start : start + size])
                    if start + size >= len(word):
                        break
                continue
            candidate = f"{current} {word}".strip()
            if len(candidate) > size:
                pieces.append(current)
                current = word
            else:
                current = candidate
        if current:
            pieces.append(current)

    return pieces or [text[:size]]


def _tail(text: str, overlap: int) -> str:
    """The last whole words of a chunk, up to `overlap` characters.

    Text with no usable word boundary - one long token - has no words that
    fit, so character overlap is the only option left.
    """
    if overlap <= 0:
        return ""

    tail = ""
    for word in reversed(text.split()):
        candidate = f"{word} {tail}".strip()
        if len(candidate) > overlap:
            break
        tail = candidate

    return tail or text[-overlap:]


HEADING_SEPARATOR = " > "


def _path_prefix(path: tuple[str, ...], limit: int) -> str:
    """The heading path as a chunk's first line, at most `limit` characters.

    When the whole path does not fit, the outermost headings go first: the
    innermost one is the chunk's topic. A single heading that is still too
    long is cut.
    """
    parts = list(path)
    while parts:
        line = HEADING_SEPARATOR.join(parts) + "\n"
        if len(line) <= limit:
            return line
        if len(parts) == 1:
            return line[:limit]
        parts.pop(0)
    return ""


def chunk_elements(
    elements: list[ExtractedElement],
    material_id: uuid.UUID,
    size: int = 500,
    overlap: int = 100,
) -> list[ContentChunk]:
    """SDD: split_text_into_chunks. 500 chars with 100 overlap.

    Each chunk starts with the path of headings it sits under, such as
    "Chapter 2 > 2.1 Layers", so it still says what topic it belongs to once it
    is on its own in the database. That is what makes retrieval and "see slide
    3" work. Text is split at headings first and only then by size, so a chunk
    never runs from one section into the next.

    A heading with a level stays in force until the next heading at its level
    or above, across pages: a section of a document runs on. A heading with no
    level, such as a slide title, applies to its own page only.
    """
    # overlap >= size is not the only blowup: overlap = size - 1 leaves a step
    # of 1, so 10k chars still produce 10,000 chunks. require the step to be a
    # meaningful fraction of the chunk size.
    min_step = max(1, size // 10)
    if size - overlap < min_step:
        raise ValidationError(
            "Chunk overlap is too large for the chunk size",
            {"size": size, "overlap": overlap, "min_step": min_step},
        )

    chunks: list[ContentChunk] = []
    index = 0
    # The leveled headings in force, outermost first, as (level, text).
    outline: list[tuple[int, str]] = []
    # A heading with no level, and the page it applies to.
    page_heading = ""
    page_heading_page = None

    # Group by page first. A PDF page arrives as one large element and a PPTX
    # slide as many small ones; chunking per element made the same content
    # produce completely different chunk sizes depending on the parser.
    pages: list[tuple[int, tuple[str, ...], list[str]]] = []
    for el in elements:
        if el.el_type == "image" and el.content in IMAGE_PLACEHOLDERS:
            continue
        if el.page != page_heading_page:
            page_heading = ""
        if el.el_type == "heading":
            if el.level > 0:
                # A heading closes every section at its level or deeper.
                while outline and outline[-1][0] >= el.level:
                    outline.pop()
                outline.append((el.level, el.content))
                page_heading = ""
            else:
                page_heading = el.content
                page_heading_page = el.page
            continue

        path = tuple(text for _, text in outline) + ((page_heading,) if page_heading else ())
        if pages and pages[-1][0] == el.page and pages[-1][1] == path:
            pages[-1][2].append(el.content)
        else:
            # The path is held per group and prefixed once per chunk below.
            # Prefixing it per element repeated it for every bullet on a slide,
            # which wastes the chunk budget and skews the embedding.
            # A new heading on the same page starts a new group: grouping by
            # page alone filed a whole DOCX, where every element is page 1,
            # under its first heading.
            pages.append((el.page, path, [el.content]))

    for page, path, blocks in pages:
        flat: list[str] = []
        for block in blocks:
            for part in re.split(r"\n\s*\n|\n", block):
                if part.strip():
                    flat.append(part.strip())

        # A path longer than half a chunk would leave too little room for
        # content, or drive the budget negative and break the size invariant.
        prefix = _path_prefix(path, size // 2)
        budget = size - len(prefix)

        buffer = ""
        carried = ""
        for block in flat:
            for piece in _split_oversized(block, budget, overlap):
                joined = f"{buffer}\n{piece}".strip() if buffer else piece
                if len(joined) > budget:
                    if buffer:
                        chunks.append(
                            ContentChunk(uuid.uuid4(), index, material_id, prefix + buffer, page)
                        )
                        index += 1
                        carried = _tail(buffer, overlap)
                    # Character-fallback pieces already contain their overlap. Do not
                    # prepend the same carried text a second time.
                    if carried and piece.startswith(carried):
                        buffer = piece
                    else:
                        seed = f"{carried} {piece}".strip() if carried else piece
                        buffer = seed if len(seed) <= budget else piece
                else:
                    buffer = joined

        if buffer.strip():
            chunks.append(ContentChunk(uuid.uuid4(), index, material_id, prefix + buffer, page))
            index += 1

    return chunks


# ---------------------------------------------------------------------------
# the router + the entry point everyone else calls
# ---------------------------------------------------------------------------


def _run_reader(reader, path: str, **options) -> list[ExtractedElement]:
    """Run one reader, turning file-level failures into a clean ValidationError.

    Only the reader call is wrapped, so bugs in our own routing/chunking logic
    still surface as real errors instead of being mislabelled "corrupt file".
    The library detail goes to the log; the client gets the filename only, so
    no library internals or server paths leak into the API response.
    """
    try:
        return reader(path, **options)
    except ValidationError:
        raise  # the reader already produced a precise message; keep it
    except Exception as exc:
        log.warning("%s failed on %s: %s", reader.__name__, path, exc)
        raise ValidationError(
            "This file could not be read; it may be corrupt or not a real document.",
            {"filename": Path(path).name},
        ) from exc


def extract(
    path: str, ext: str, with_images: bool = False
) -> tuple[list[ExtractedElement], str, list[str]]:
    """Pick a reader for the format. Returns elements, parser name, warnings.

    `with_images` keeps each image's bytes on its element, for captioning.
    Word documents do not supply them yet.
    """
    warnings: list[str] = []
    # Asked of a reader only when wanted, so the readers are called exactly as
    # before when images are not.
    images = {"with_images": True} if with_images else {}

    if ext == "pdf":
        # Option B: pypdf is the default (light, installs everywhere).
        elements = _run_reader(read_pdf_pypdf, path, **images)
        joined = " ".join(e.content for e in elements if e.el_type != "image")

        # quality guard: if pypdf produced letter-spaced garbage, try to
        # upgrade to docling. this only helps if docling is installed.
        if looks_letter_spaced(joined):
            try:
                from docling.document_converter import DocumentConverter  # noqa: F401

                log.info("pypdf output looks corrupted on %s, upgrading to docling", path)
                return (
                    _run_reader(read_pdf_docling, path, **images),
                    "docling",
                    warnings,
                )
            except ImportError:
                warnings.append(
                    "This PDF uses styled text that the default parser reads poorly. "
                    "Install the 'extraction' extra (docling) for better results."
                )
                return elements, "pypdf-low-quality", warnings

        return elements, "pypdf", warnings

    if ext == "pptx":
        return _run_reader(read_pptx, path, **images), "python-pptx", warnings
    if ext == "docx":
        return _run_reader(read_docx, path), "python-docx", warnings
    if ext == "txt":
        return _run_reader(read_txt, path), "plain-text", warnings

    raise ValidationError(f"Unsupported file format: .{ext}", {"received": ext})


def element_metadata(element: ExtractedElement) -> dict[str, int]:
    """What is stored beside an element so its chunks can be rebuilt later.

    The uploaded file is deleted once processed (Design Document 4.1), so the
    stored elements are all a material can ever be chunked again from. A
    heading's level is the one thing chunking needs that the row has no column
    for. A caption needs nothing extra: it is the element's content.
    """
    if element.el_type == "heading" and element.level > 0:
        return {"level": element.level}
    return {}


def stored_element(
    element_type: str, content: str | None, source_page: int | None, metadata: dict | None
) -> ExtractedElement:
    """A stored extraction_element row as the element it was saved from.

    Rows saved before levels were kept read back as headings with no level,
    which chunk as they always did: each applies to its own page.
    """
    level = (metadata or {}).get("level", 0)
    return ExtractedElement(
        element_type,
        content or "",
        source_page or 1,
        level=level if isinstance(level, int) and level > 0 else 0,
    )


def skipped_pages_warning(elements: list[ExtractedElement]) -> str | None:
    """The warning for PDF pages that gave no text and were not captioned.

    Only those pages are skipped. A PPTX picture sits alongside the slide's
    text and is not a skipped page, so counting every image element would
    report "2 pages skipped" on a normal deck.
    """
    skipped = sum(1 for e in elements if e.el_type == "image" and e.content == IMAGE_ONLY_PAGE)
    if not skipped:
        return None
    return f"{skipped} page(s) contained no readable text and were skipped."


def process_material(
    path: str,
    material_id: uuid.UUID,
    max_bytes: int = 52_428_800,
    *,
    with_images: bool = False,
) -> ProcessingResult:
    """Entry point. Validate, extract, clean, chunk.

    Called by POST /api/v1/materials. Embedding and storage happen after this,
    in Phase 2. `with_images` keeps image bytes for captioning, which the
    pipeline then does and re-chunks (see image_captioning.py).
    """
    ext = validate_file(path, max_bytes)
    elements, parser, warnings = extract(path, ext, with_images=with_images)

    if not any(e.el_type != "image" for e in elements):
        # SDD: no_readable_text_found -> status Failed
        raise ValidationError(
            "No readable text found in this file",
            {"filename": Path(path).name, "parser": parser},
        )

    chunks = chunk_elements(elements, material_id)
    page_count = max((e.page for e in elements), default=0)

    skipped = skipped_pages_warning(elements)
    if skipped:
        warnings.append(skipped)

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
