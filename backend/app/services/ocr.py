"""OCR for scanned PDF pages, with Tesseract (Phase 8, AI 1).

A scanned PDF page is a picture of text with no text layer, so pypdf reads
nothing from it and the page used to be skipped. When Tesseract is installed,
extraction reads such a page's picture with it instead. Only pages with no
text layer are read: OCR on a normal page adds nothing and costs seconds.

Tesseract is a program, not a Python package, so it is run directly with the
image on stdin, without a shell, the way LibreOffice is in image_captioning.
Without it, scanned pages are skipped as before and the lecturer is told how
to have them read. Install it with `brew install tesseract` on a Mac or
`apt-get install tesseract-ocr` on Debian or Ubuntu.

Measured accuracy is in tests/eval/OCR_RESULTS.md (scripts/evaluate_ocr.py).
"""

from __future__ import annotations

import io
import logging
import shutil
import subprocess
from pathlib import Path

log = logging.getLogger("clip.ocr")

# Where Homebrew puts it on an Apple silicon Mac, which a server started
# outside a terminal may not have on its PATH.
MAC_TESSERACT = "/opt/homebrew/bin/tesseract"
# A full page takes one to three seconds; a page still going after this is
# abandoned and skipped, not allowed to hold the material's worker.
OCR_TIMEOUT_SECONDS = 60.0
# Pages read per material. At a few seconds a page this bounds the work a
# long scanned file can cause; the pages after it are skipped and reported.
MAX_OCR_PAGES = 60
# Time spent on OCR per material. Without it the worst case is MAX_OCR_PAGES
# pages at OCR_TIMEOUT_SECONDS each, an hour; with it a material's OCR stops
# within this plus one page's timeout, and the pages after it are reported.
MAX_OCR_SECONDS = 300.0
# Fewer letters and digits than this is a page with no real text, such as a
# photo or a diagram, where Tesseract returns a few stray characters.
MIN_OCR_CHARACTERS = 20


def find_tesseract(configured: str = "") -> str | None:
    """The Tesseract program to read with, or None when there is none.

    A configured path wins; otherwise the PATH, then the usual place on a Mac.
    """
    if configured:
        return shutil.which(configured) or (configured if Path(configured).is_file() else None)
    found = shutil.which("tesseract")
    if found:
        return found
    return MAC_TESSERACT if Path(MAC_TESSERACT).is_file() else None


def has_text(text: str) -> bool:
    """Whether OCR output holds enough letters and digits to be a page of text."""
    return sum(ch.isalnum() for ch in text) >= MIN_OCR_CHARACTERS


class TesseractReader:
    """Reads the text in one page image with Tesseract."""

    def __init__(
        self, program: str, language: str = "eng", timeout: float = OCR_TIMEOUT_SECONDS
    ) -> None:
        self.program = program
        self.language = language
        self._timeout = timeout

    def read(self, image: bytes) -> str:
        """The text Tesseract finds in the image, or "" if it found none or failed.

        The image is decoded with Pillow first and sent on as a greyscale PNG:
        that refuses an image too large to decode safely, and gives Tesseract
        one format whatever the PDF stored the scan as.
        """
        png = _greyscale_png(image)
        if png is None:
            return ""
        try:
            done = subprocess.run(
                [self.program, "stdin", "stdout", "-l", self.language],
                input=png,
                capture_output=True,
                timeout=self._timeout,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired):
            log.warning("tesseract did not finish a page", exc_info=True)
            return ""
        if done.returncode != 0:
            log.warning(
                "tesseract failed on a page (exit %s): %s",
                done.returncode,
                done.stderr.decode("utf-8", "replace")[:200],
            )
            return ""
        return done.stdout.decode("utf-8", "replace")


def _greyscale_png(image: bytes) -> bytes | None:
    """The image as a greyscale PNG, or None if Pillow cannot read it safely."""
    from PIL import Image

    from app.services.extraction import MAX_IMAGE_PIXELS

    try:
        with Image.open(io.BytesIO(image)) as opened:
            width, height = opened.size
            if width * height > MAX_IMAGE_PIXELS:
                return None
            out = io.BytesIO()
            opened.convert("L").save(out, format="PNG")
            return out.getvalue()
    except Exception:
        log.debug("could not decode a page image for OCR", exc_info=True)
        return None
