"""OCR of scanned PDF pages (Phase 8, AI 1).

Most tests give extraction a fake reader, so they run without Tesseract. The
last few run the real program and are skipped where it is not installed.
"""

from __future__ import annotations

import io
import subprocess
import uuid

import pytest
from PIL import Image, ImageDraw, ImageFont

from app.core.errors import ValidationError
from app.services import ocr
from app.services.extraction import (
    IMAGE_ONLY_PAGE,
    NO_OCR_NOTE,
    extract,
    extract_material,
    process_material,
)
from app.services.ocr import TesseractReader, find_tesseract, has_text

PAGE_TEXT = "Logistic regression predicts the probability of a binary outcome."


def scanned_pdf(path, pages: int = 1) -> str:
    """A PDF whose pages are pictures of text, with no text layer."""
    images = []
    for n in range(pages):
        image = Image.new("RGB", (1240, 900), "white")
        ImageDraw.Draw(image).text(
            (80, 120), f"{PAGE_TEXT} Page {n + 1}.", fill="black", font=_font()
        )
        images.append(image)
    images[0].save(path, save_all=True, append_images=images[1:])
    return str(path)


def text_pdf(path) -> str:
    """A PDF with a real text layer."""
    from pypdf import PdfWriter
    from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject

    writer = PdfWriter()
    page = writer.add_blank_page(width=600, height=400)
    font = DictionaryObject(
        {
            NameObject("/Type"): NameObject("/Font"),
            NameObject("/Subtype"): NameObject("/Type1"),
            NameObject("/BaseFont"): NameObject("/Helvetica"),
        }
    )
    page[NameObject("/Resources")] = DictionaryObject(
        {NameObject("/Font"): DictionaryObject({NameObject("/F1"): font})}
    )
    stream = DecodedStreamObject()
    stream.set_data(f"BT /F1 14 Tf 40 300 Td ({PAGE_TEXT}) Tj ET".encode())
    page[NameObject("/Contents")] = writer._add_object(stream)
    with open(path, "wb") as out:
        writer.write(out)
    return str(path)


def _font():
    try:
        return ImageFont.truetype("DejaVuSans.ttf", 36)
    except OSError:
        return ImageFont.load_default(size=36)


class FakeOcr:
    """Stands in for Tesseract: returns set text and records each call."""

    def __init__(self, text: str = PAGE_TEXT) -> None:
        self.text = text
        self.calls = 0

    def __call__(self, image: bytes) -> str:
        assert image, "OCR is given the page's image"
        self.calls += 1
        return self.text


# --- extraction with OCR ----------------------------------------------------


def test_a_scanned_page_is_read_with_ocr(tmp_path):
    fake = FakeOcr()
    result = process_material(scanned_pdf(tmp_path / "scan.pdf"), uuid.uuid4(), ocr=fake)
    assert fake.calls == 1
    assert result.parser_used == "pypdf+ocr"
    assert [e.el_type for e in result.elements] == ["text"]
    assert PAGE_TEXT in result.chunks[0].chunk_text
    assert result.chunks[0].source_page == 1
    assert any("read with OCR" in w for w in result.warnings)


def test_a_page_with_a_text_layer_is_never_sent_to_ocr(tmp_path):
    fake = FakeOcr()
    result = process_material(text_pdf(tmp_path / "text.pdf"), uuid.uuid4(), ocr=fake)
    assert fake.calls == 0
    assert result.parser_used == "pypdf"
    assert PAGE_TEXT in result.chunks[0].chunk_text


def test_a_scan_with_no_real_text_stays_an_image_only_page(tmp_path):
    path = scanned_pdf(tmp_path / "photo.pdf")
    elements, parser, warnings = extract(path, "pdf", ocr=FakeOcr("~ |"))
    assert [e.content for e in elements] == [IMAGE_ONLY_PAGE]
    assert parser == "pypdf"
    assert not any("read with OCR" in w for w in warnings)


def test_a_scan_with_no_real_text_and_no_captioning_still_fails(tmp_path):
    with pytest.raises(ValidationError):
        process_material(scanned_pdf(tmp_path / "photo.pdf"), uuid.uuid4(), ocr=FakeOcr(""))


def test_ocr_text_is_not_also_kept_as_an_image_to_caption(tmp_path):
    path = scanned_pdf(tmp_path / "scan.pdf")
    extraction = extract_material(path, 52_428_800, with_images=True, ocr=FakeOcr())
    assert not any(e.image for e in extraction.elements)


def test_without_ocr_a_scanned_page_says_how_to_have_it_read(tmp_path):
    path = scanned_pdf(tmp_path / "scan.pdf")
    elements, parser, warnings = extract(path, "pdf")
    assert [e.content for e in elements] == [IMAGE_ONLY_PAGE]
    assert NO_OCR_NOTE in warnings
    assert not elements[0].image, "image bytes are kept only when captioning asks"


def test_ocr_reads_at_most_the_page_limit(tmp_path, monkeypatch):
    monkeypatch.setattr(ocr, "MAX_OCR_PAGES", 2)
    fake = FakeOcr()
    path = scanned_pdf(tmp_path / "long.pdf", pages=3)
    elements, parser, warnings = extract(path, "pdf", ocr=fake)
    assert fake.calls == 2
    assert [e.el_type for e in elements] == ["text", "text", "image"]
    assert any("1 scanned page(s) were not read" in w for w in warnings)
    assert any("2 scanned page(s) were read with OCR" in w for w in warnings)


def test_has_text_needs_enough_letters_and_digits():
    assert has_text(PAGE_TEXT)
    assert not has_text("  | ~ . ,  \n")
    assert not has_text("ab cd")


# --- the Tesseract reader ---------------------------------------------------


def _png(size=(200, 100)) -> bytes:
    out = io.BytesIO()
    Image.new("RGB", size, "white").save(out, format="PNG")
    return out.getvalue()


def test_find_tesseract_prefers_a_configured_path(tmp_path):
    program = tmp_path / "tesseract"
    program.write_text("")
    assert find_tesseract(str(program)) == str(program)
    assert find_tesseract(str(tmp_path / "missing")) is None


def test_the_reader_sends_a_greyscale_png_without_a_shell(monkeypatch):
    seen = {}

    def run(args, **kwargs):
        seen["args"], seen["kwargs"] = args, kwargs
        return subprocess.CompletedProcess(args, 0, stdout=b"read text", stderr=b"")

    monkeypatch.setattr(ocr.subprocess, "run", run)
    assert TesseractReader("/bin/tesseract", language="eng+ara").read(_png()) == "read text"
    assert seen["args"] == ["/bin/tesseract", "stdin", "stdout", "-l", "eng+ara"]
    assert "shell" not in seen["kwargs"]
    with Image.open(io.BytesIO(seen["kwargs"]["input"])) as sent:
        assert sent.format == "PNG" and sent.mode == "L"


@pytest.mark.parametrize(
    "outcome",
    [
        subprocess.CompletedProcess([], 1, stdout=b"", stderr=b"bad"),
        subprocess.TimeoutExpired("tesseract", 60),
        FileNotFoundError("gone"),
    ],
)
def test_a_failed_read_returns_nothing(monkeypatch, outcome):
    def run(*args, **kwargs):
        if isinstance(outcome, BaseException):
            raise outcome
        return outcome

    monkeypatch.setattr(ocr.subprocess, "run", run)
    assert TesseractReader("tesseract").read(_png()) == ""


def test_an_oversized_or_broken_image_is_never_sent(monkeypatch):
    from app.services import extraction

    def run(*args, **kwargs):
        raise AssertionError("Tesseract should not be called")

    monkeypatch.setattr(ocr.subprocess, "run", run)
    monkeypatch.setattr(extraction, "MAX_IMAGE_PIXELS", 100 * 100)
    reader = TesseractReader("tesseract")
    assert reader.read(_png((200, 100))) == ""
    assert reader.read(b"not an image") == ""


# --- the real program, where installed --------------------------------------

needs_tesseract = pytest.mark.skipif(find_tesseract() is None, reason="Tesseract not installed")


@needs_tesseract
def test_real_tesseract_reads_a_scanned_page(tmp_path):
    reader = TesseractReader(find_tesseract())
    result = process_material(scanned_pdf(tmp_path / "scan.pdf"), uuid.uuid4(), ocr=reader.read)
    text = result.chunks[0].chunk_text.lower()
    assert "logistic regression" in text
    assert "binary outcome" in text
