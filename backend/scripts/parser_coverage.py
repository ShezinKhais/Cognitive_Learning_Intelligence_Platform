"""Parser coverage for the AI evaluation report (Phase 8, AI 1, #73).

Not a test. Reads every sample lecture as an upload would and prints, per
file, whether it was read, how many pages gave text, headings, images,
letter-spacing and time. No model is needed. Run from backend/:

    python -m scripts.parser_coverage
    python -m scripts.parser_coverage --out tests/eval/PARSER_COVERAGE.md
    python -m scripts.parser_coverage --edge-cases
    python -m scripts.parser_coverage path/to/other.pdf ...

--edge-cases also reads two files made on the spot: a scanned PDF with no text
layer, and a corrupt PDF. They show how a failure is reported.
"""

from __future__ import annotations

import argparse
import tempfile
from pathlib import Path

from app.services.parser_coverage import markdown_table, measure

SAMPLES = Path(__file__).resolve().parent.parent / "tests" / "samples"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("files", nargs="*", help="files to read (default: tests/samples)")
    parser.add_argument("--out", help="also write the table to this Markdown file")
    parser.add_argument("--edge-cases", action="store_true", help="add a scanned and a corrupt PDF")
    args = parser.parse_args()

    files = args.files or sorted(str(p) for p in SAMPLES.iterdir() if p.is_file())
    with tempfile.TemporaryDirectory() as folder:
        if args.edge_cases:
            files += edge_cases(Path(folder))
        table = markdown_table([measure(f) for f in files])
    print(table)
    if args.out:
        Path(args.out).write_text(
            "# Parser coverage\n\nEach sample read as an upload would be, with images. "
            "Pages with text counts pages or slides with any text, heading or table; "
            "Word and text files count as one page.\n\n" + table + "\n"
        )


def edge_cases(folder: Path) -> list[str]:
    """A scanned page (an image, no text layer) and a file that only claims to be a PDF."""
    from PIL import Image, ImageDraw

    scanned = folder / "scanned.pdf"
    page = Image.new("RGB", (800, 600), "white")
    ImageDraw.Draw(page).text((40, 40), "A scanned lecture slide", fill="black")
    page.save(scanned)
    corrupt = folder / "corrupt.pdf"
    corrupt.write_bytes(b"%PDF-1.4 this is not really a PDF")
    return [str(scanned), str(corrupt)]


if __name__ == "__main__":
    main()
