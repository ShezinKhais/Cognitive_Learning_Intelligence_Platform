"""Run in the deployed backend image; generate synthetic PDFs with no text layer."""

from pathlib import Path
from tempfile import TemporaryDirectory

from PIL import Image, ImageDraw, ImageFont

from app.core.config import get_settings
from app.services.extraction import IMAGE_ONLY_PAGE, extract
from app.services.ocr import TesseractReader, find_tesseract


def main() -> None:
    settings = get_settings()
    program = find_tesseract(settings.tesseract_path)
    if not settings.ocr_enabled or not program:
        raise SystemExit("OCR is disabled or Tesseract is missing in the deployment.")
    reader = TesseractReader(program, language=settings.ocr_language)
    font = ImageFont.truetype("DejaVuSans.ttf", 40)
    with TemporaryDirectory(prefix="clip-ocr-check-") as temporary:
        for name, phrase, ink in (
            ("clean", "Logistic regression predicts a binary outcome.", "black"),
            ("low-contrast", "Logistic regression predicts a binary outcome.", "#b8b8b8"),
            ("formula", "The line equation is y = 2x + 3.", "black"),
            ("blank", "", "black"),
        ):
            path = Path(temporary) / f"{name}.pdf"
            page = Image.new("RGB", (1300, 800), "white")
            ImageDraw.Draw(page).text((80, 120), phrase, font=font, fill=ink)
            page.save(path)
            elements, _, warnings = extract(str(path), "pdf", ocr=reader.read)
            text = " ".join(item.content or "" for item in elements).lower()
            if name == "clean" and not all(
                expected in text for expected in ("logistic regression", "binary outcome")
            ):
                raise SystemExit("Clean scanned PDF lost expected text.")
            if name == "blank" and (text.strip() != IMAGE_ONLY_PAGE or not warnings):
                raise SystemExit("Blank scanned PDF was not identified as unreadable.")
            if name in {"low-contrast", "formula"}:
                print(f"{name}: {text.strip()} (observation only)")
            else:
                print(f"{name}: passed")
            for warning in warnings:
                print(f"  {warning}")


if __name__ == "__main__":
    main()
