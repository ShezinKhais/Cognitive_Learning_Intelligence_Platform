"""OCR accuracy on scanned lectures, for the AI evaluation report (Phase 8,
AI 1, #73).

Not a test, and not part of the app. Needs Tesseract installed
(`brew install tesseract` on a Mac). Run from backend/:

    python -m scripts.evaluate_ocr
    python -m scripts.evaluate_ocr --out tests/eval/OCR_RESULTS.md

tests/eval/ocr/ holds two lectures saved as scans: every page a 150 dpi
greyscale picture, with no text layer. The true text of each page is read
from the original PDF's text layer. Each scan is read twice: as it is, and as
a poor scan (lower resolution, blurred, slightly rotated, heavily compressed),
the kind a phone photo of a printout gives.
"""

from __future__ import annotations

import argparse
import io
import time
from pathlib import Path

from app.core.config import get_settings
from app.services.extraction import _pypdf_images
from app.services.ocr import TesseractReader, find_tesseract, has_text
from app.services.ocr_evaluation import OcrScore, markdown_table

BACKEND = Path(__file__).resolve().parent.parent
SCANS = BACKEND / "tests" / "eval" / "ocr"
# Each scan and the original PDF its true text comes from.
DOCUMENTS = {
    "lecture_scanned.pdf": BACKEND / "tests" / "samples" / "lecture.pdf",
    "lecture_pptx_as_pdf_scanned.pdf": BACKEND / "tests" / "eval" / "lecture_pptx_as_pdf.pdf",
}
NAMES = {
    "lecture_scanned.pdf": "Computer vision slides (21 pages)",
    "lecture_pptx_as_pdf_scanned.pdf": "Logistic regression slides (18 pages)",
}


def poor_scan(image: bytes) -> bytes:
    """The same page as a worse scan: half the resolution, blurred, tilted 1.5
    degrees and saved as a low quality JPEG. Always the same for the same page."""
    from PIL import Image, ImageFilter

    with Image.open(io.BytesIO(image)) as page:
        small = page.convert("L").resize((page.width // 2, page.height // 2))
        worse = small.filter(ImageFilter.GaussianBlur(0.8)).rotate(1.5, expand=True, fillcolor=255)
        out = io.BytesIO()
        worse.save(out, format="JPEG", quality=30)
        return out.getvalue()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--out", type=Path, help="also write the results to this Markdown file")
    args = parser.parse_args()

    from pypdf import PdfReader

    settings = get_settings()
    program = find_tesseract(settings.tesseract_path)
    if program is None:
        raise SystemExit("Tesseract not found. Install it first: brew install tesseract")
    reader = TesseractReader(program, language=settings.ocr_language)

    rows = []
    for scan_name, original in DOCUMENTS.items():
        truths = [page.extract_text() or "" for page in PdfReader(str(original)).pages]
        pages = [_pypdf_images(page)[0] for page in PdfReader(str(SCANS / scan_name)).pages]
        for quality, prepare in (("clean, 150 dpi", None), ("poor", poor_scan)):
            score = OcrScore()
            for truth, image in zip(truths, pages, strict=True):
                start = time.perf_counter()
                read = reader.read(prepare(image) if prepare else image)
                score.add(truth, read, time.perf_counter() - start, has_text(read))
            print(
                f"{NAMES[scan_name]}, {quality}: word recall {score.word_recall:.1%}, "
                f"CER {score.cer:.1%}, WER {score.wer:.1%}, "
                f"{score.pages_read} of {score.pages} pages read"
            )
            rows.append((NAMES[scan_name], quality, score))

    table = markdown_table(rows)
    print("\n" + table)
    if args.out:
        args.out.write_text(
            "# OCR accuracy\n\n"
            f"Tesseract ({Path(program).name}, language `{settings.ocr_language}`) on two "
            "lectures saved as image-only scans, scored against each page's true text from "
            "the original PDF, after lower-casing and removing punctuation. Word recall is the "
            "share of the true words OCR found, in any order; higher is better. CER and WER "
            "are the edits needed to reach the true text, over its length; lower is better. "
            "They also count as errors text OCR reads that the text layer lacks, such as the "
            "university logo on every slide and chart labels, and words read in a different "
            "order on two-column slides. A page is "
            "read when OCR finds at least 20 letters or digits on it. The poor scan is half "
            "the resolution, blurred, tilted 1.5 degrees and saved as a low quality JPEG.\n\n"
            + table
            + "\n"
        )
        print(f"\nwritten to {args.out}")


if __name__ == "__main__":
    main()
