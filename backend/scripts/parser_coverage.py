"""Parser coverage for the AI evaluation report (Phase 8, AI 1, #73).

Not a test. Reads every sample lecture as an upload would and prints, per
file, whether it was read, how many pages gave text, headings, images,
letter-spacing and time. No model is needed. Run from backend/:

    python -m scripts.parser_coverage
    python -m scripts.parser_coverage --out tests/eval/PARSER_COVERAGE.md
    python -m scripts.parser_coverage --edge-cases
    python -m scripts.parser_coverage path/to/other.pdf ...

--edge-cases also reads two files made on the spot: a scanned PDF with no text
layer, and a corrupt PDF. They show how a failure is reported. Scanned pages
are read with OCR when Tesseract is installed, as in the app.
"""

from __future__ import annotations

import argparse
import tempfile
from pathlib import Path

from app.core.config import get_settings
from app.services.ocr import TesseractReader, find_tesseract
from app.services.parser_coverage import markdown_table, measure

SAMPLES = Path(__file__).resolve().parent.parent / "tests" / "samples"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("files", nargs="*", help="files to read (default: tests/samples)")
    parser.add_argument("--out", help="also write the table to this Markdown file")
    parser.add_argument("--edge-cases", action="store_true", help="add a scanned and a corrupt PDF")
    args = parser.parse_args()

    settings = get_settings()
    program = find_tesseract(settings.tesseract_path) if settings.ocr_enabled else None
    ocr = TesseractReader(program, language=settings.ocr_language).read if program else None
    print(f"OCR: {'Tesseract' if ocr else 'off (Tesseract not found)'}")

    files = args.files or sorted(str(p) for p in SAMPLES.iterdir() if p.is_file())
    with tempfile.TemporaryDirectory() as folder:
        if args.edge_cases:
            files += edge_cases(Path(folder))
        table = markdown_table([measure(f, ocr=ocr) for f in files])
    print(table)
    if args.out:
        Path(args.out).write_text(
            "# Parser coverage\n\nEach sample read as an upload would be, with images. "
            "Pages with text counts pages or slides with any text, heading or table; "
            "Word and text files count as one page.\n\n" + table + "\n"
        )


def edge_cases(folder: Path) -> list[str]:
    """A scanned page (an image, no text layer) and a file that only claims to be a PDF."""
    from PIL import Image, ImageDraw, ImageFont

    scanned = folder / "scanned.pdf"
    page = Image.new("RGB", (1240, 900), "white")
    ImageDraw.Draw(page).text(
        (80, 120),
        "A scanned lecture slide about logistic regression.",
        fill="black",
        font=ImageFont.load_default(size=40),
    )
    page.save(scanned)
    corrupt = folder / "corrupt.pdf"
    corrupt.write_bytes(b"%PDF-1.4 this is not really a PDF")
    return [str(scanned), str(corrupt)]


if __name__ == "__main__":
    main()
