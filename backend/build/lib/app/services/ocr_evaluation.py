"""OCR accuracy for the AI evaluation report (Phase 8, AI 1, #73).

Character error rate (CER) and word error rate (WER) are the standard OCR
measures: the edits (insertions, deletions, substitutions) needed to turn
what OCR read into the true text, divided by the length of the true text.
0 is perfect; a rate can pass 1 when OCR reads in a lot that is not there.

Both texts are normalised first, so the rates count misread words, not
differences of case, punctuation or spacing: the true text comes from a PDF's
text layer, which runs words together ("Goal:Enable") where a person, and
OCR, sees two.

CER and WER also count, as errors, text OCR reads that the text layer does not
hold: a logo, the labels on a chart. Word recall does not: it is the share of
the true words OCR found, in any order, which is what search needs.
"""

from __future__ import annotations

import re
import unicodedata
from collections import Counter
from dataclasses import dataclass

from rapidfuzz.distance import Levenshtein


def normalise(text: str) -> str:
    """Lower case, letters and digits only, single spaces."""
    text = unicodedata.normalize("NFKC", text).lower()
    return " ".join(re.sub(r"[^\w]+|_", " ", text).split())


@dataclass
class OcrScore:
    """Errors summed over pages, so long pages count for more than short ones."""

    pages: int = 0
    pages_read: int = 0
    char_errors: int = 0
    chars: int = 0
    word_errors: int = 0
    words: int = 0
    words_found: int = 0
    seconds: float = 0.0

    def add(self, reference: str, read: str, seconds: float, was_read: bool) -> None:
        """Score one page: its true text against what OCR read."""
        truth, found = normalise(reference), normalise(read)
        self.pages += 1
        self.pages_read += was_read
        self.seconds += seconds
        # Characters without spaces: a space OCR adds or drops is not a misread letter.
        self.char_errors += Levenshtein.distance(truth.replace(" ", ""), found.replace(" ", ""))
        self.chars += len(truth.replace(" ", ""))
        self.word_errors += Levenshtein.distance(truth.split(), found.split())
        self.words += len(truth.split())
        self.words_found += sum((Counter(truth.split()) & Counter(found.split())).values())

    @property
    def cer(self) -> float:
        return self.char_errors / self.chars if self.chars else 0.0

    @property
    def wer(self) -> float:
        return self.word_errors / self.words if self.words else 0.0

    @property
    def word_recall(self) -> float:
        return self.words_found / self.words if self.words else 0.0

    @property
    def seconds_per_page(self) -> float:
        return self.seconds / self.pages if self.pages else 0.0


def markdown_table(rows: list[tuple[str, str, OcrScore]]) -> str:
    """One row per document and scan quality."""
    lines = [
        "| Document | Scan | Pages read | Word recall | CER | WER | Seconds per page |",
        "|---|---|---|---|---|---|---|",
    ]
    for document, quality, score in rows:
        lines.append(
            f"| {document} | {quality} | {score.pages_read} of {score.pages} | "
            f"{score.word_recall:.1%} | {score.cer:.1%} | {score.wer:.1%} | "
            f"{score.seconds_per_page:.1f} |"
        )
    return "\n".join(lines)
