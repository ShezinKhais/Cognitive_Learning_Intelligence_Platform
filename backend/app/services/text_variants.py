"""The ways a piece of text can be read, for matching phrases against it.

Owner: Cyber 1, Phase 5. Imports nothing from the application, so any module
that screens text (generation.py, text_screening.py) can use it without a cycle.

A pattern written for plain text misses the same phrase typed with a Cyrillic
"о", spaced out ("i g n o r e"), or with digits for letters ("1gn0re"), though
a model reads each as the plain phrase. screening_variants returns the plain
text and those readings, and a phrase found in any of them counts as found.
"""

from __future__ import annotations

import re
import unicodedata


def normalise_for_screening(text: str) -> str:
    """The text as a reader sees it, for pattern matching.

    NFKC folds compatibility forms (fullwidth letters, ligatures) onto plain
    ones, format characters such as zero-width spaces are dropped, and runs of
    whitespace become one space, so none of them can split a phrase apart.
    """
    folded = unicodedata.normalize("NFKC", text)
    visible = "".join(ch for ch in folded if unicodedata.category(ch) != "Cf")
    return re.sub(r"\s+", " ", visible)


# Cyrillic and Greek letters that render as a Latin one. Folded onto it before
# pattern matching, so "ignоre" (Cyrillic "о") is matched as "ignore" without
# flagging every Greek symbol in a physics lecture.
_CONFUSABLES = str.maketrans(
    {
        "а": "a", "е": "e", "о": "o", "р": "p", "с": "c", "у": "y", "х": "x",
        "і": "i", "ј": "j", "ѕ": "s", "һ": "h", "ԁ": "d", "ɡ": "g", "ո": "n",
        "ο": "o", "α": "a", "ε": "e", "ι": "i", "κ": "k", "ν": "v", "ρ": "p",
        "τ": "t", "υ": "u", "χ": "x", "ϲ": "c",
        "А": "A", "В": "B", "Е": "E", "К": "K", "М": "M", "Н": "H", "О": "O",
        "Р": "P", "С": "C", "Т": "T", "Х": "X", "І": "I",
        "Α": "A", "Β": "B", "Ε": "E", "Ζ": "Z", "Η": "H", "Ι": "I", "Κ": "K",
        "Μ": "M", "Ν": "N", "Ο": "O", "Ρ": "P", "Τ": "T", "Υ": "Y", "Χ": "X",
    }
)  # fmt: skip
# Digits and symbols standing in for letters: "1gn0re".
_LEET = str.maketrans(
    {"0": "o", "1": "i", "3": "e", "4": "a", "5": "s", "7": "t", "@": "a", "$": "s"}
)


def fold_confusables(text: str) -> str:
    """Lookalike Cyrillic and Greek letters replaced by the Latin ones they mimic."""
    return text.translate(_CONFUSABLES)


def _despace(text: str) -> str:
    """Runs of single characters joined: "i g n o r e" becomes "ignore"."""
    out: list[str] = []
    run: list[str] = []
    for token in text.split(" "):
        if len(token) == 1 and token.isalnum():
            run.append(token)
            continue
        if run:
            out.append("".join(run))
            run = []
        out.append(token)
    if run:
        out.append("".join(run))
    return " ".join(out)


def screening_variants(text: str) -> list[str]:
    """The text as written, and the ways of reading it an attacker may rely on.

    Each is matched against the same patterns, so a phrase hidden by lookalike
    letters, spaced-out letters or digits-for-letters is found the same as the
    plain one. A disguised copy that matches nothing costs nothing; a plain one
    that matched before still does.
    """
    base = normalise_for_screening(text)
    folded = fold_confusables(base)
    variants = [base, folded, _despace(folded), _despace(folded).translate(_LEET)]
    return list(dict.fromkeys(variants))
