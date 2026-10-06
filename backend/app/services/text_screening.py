"""Screening and sanitising of text that came from a model, a document or a student.

Owner: Cyber 1, Phase 5. Shared by the tutor guardrails (tutor_guardrails.py)
and the alert explanations (ai_explainability.py).

The instruction patterns are AI 1's, from generation.py, and are used as they
are: one pattern set for text aimed at a model, so a phrase added there is
caught here as well. What this module adds is what generation has no need of:
mixed-alphabet words (a Cyrillic "o" inside "ignore" slips past every pattern),
control characters, markup, and a single place that turns a string of unknown
origin into one safe to show a lecturer.
"""

from __future__ import annotations

import re
import unicodedata

from app.services.generation import contains_embedded_instruction, ungrounded_links
from app.services.text_variants import fold_confusables, normalise_for_screening, screening_variants

__all__ = [
    "contains_embedded_instruction",
    "contains_markup",
    "fold_confusables",
    "has_mixed_script_word",
    "looks_like_instruction",
    "normalise_for_screening",
    "safe_display_text",
    "screening_variants",
    "strip_unsafe_characters",
    "ungrounded_links",
]

# Alphabets whose letters look like Latin ones.
_LOOKALIKE_SCRIPTS = ("LATIN", "CYRILLIC", "GREEK")
_WORD = re.compile(r"\w+", flags=re.UNICODE)

# An HTML tag, comment or declaration, a markdown link or image, an HTML entity,
# a code fence. The UI renders text, not markup, so none of it belongs in text we
# write for a screen, and a model has no reason to produce it. A tag needs its
# closing ">" so a lecture's "x < y" or "a<b" is not mistaken for one.
_MARKUP = re.compile(
    r"</?[a-zA-Z][a-zA-Z0-9-]*(?:[\s/]+[^<>=]+=[^<>]*)?\s*/?>|<!--|<\?|<![a-zA-Z]"
    r"|\]\(|&#?\w+;|`{1,3}"
)

# Characters that are neither printable nor whitespace. Format characters
# (zero-width and direction marks) are dropped by normalise_for_screening.
_UNSAFE_CATEGORIES = frozenset({"Cc", "Cs", "Co", "Cn"})


def looks_like_instruction(text: str) -> bool:
    """Whether text, however disguised, carries an instruction aimed at a model."""
    return contains_embedded_instruction(text)


def _script_of(char: str) -> str | None:
    if not char.isalpha():
        return None
    name = unicodedata.name(char, "")
    for script in _LOOKALIKE_SCRIPTS:
        if name.startswith(script):
            return script
    return None


def has_mixed_script_word(text: str) -> bool:
    """Whether any single word mixes Cyrillic letters with Latin or Greek ones.

    "ignоre" with a Cyrillic "о" reads as "ignore" and matches no pattern. No
    word of English or Arabic holds both alphabets, so the mix is a disguise.
    Greek is not counted against Latin: a lecture writes "Δx", "μm" and "ρgh"
    legitimately, and a Greek lookalike hiding a phrase is caught instead by
    fold_confusables, which maps it to the letter it mimics before matching.
    """
    for word in _WORD.findall(unicodedata.normalize("NFKC", text)):
        scripts = {script for char in word if (script := _script_of(char)) is not None}
        if "CYRILLIC" in scripts and len(scripts) > 1:
            return True
    return False


def strip_unsafe_characters(text: str) -> str:
    """The text as a reader sees it: no control, unassigned or format characters,
    and whitespace collapsed to single spaces."""
    visible = "".join(
        ch
        for ch in normalise_for_screening(text)
        if unicodedata.category(ch) not in _UNSAFE_CATEGORIES
    )
    return re.sub(r"\s+", " ", visible).strip()


def contains_markup(text: str) -> bool:
    return _MARKUP.search(normalise_for_screening(text)) is not None


def safe_display_text(text: str | None, *, limit: int) -> str | None:
    """Text of unknown origin, made safe to show a lecturer, or None.

    None means "do not show this": the caller uses its own fallback instead.
    Text is refused, not repaired, when it carries an instruction aimed at a
    model, a link, markup or a disguised word, because a sanitised version of
    an attack is still text someone chose to write for that purpose. Text that
    is only too long is cut at a word boundary.
    """
    if text is None:
        return None
    cleaned = strip_unsafe_characters(text)
    if not cleaned:
        return None
    if (
        looks_like_instruction(cleaned)
        or ungrounded_links(cleaned, "")
        or contains_markup(cleaned)
        or has_mixed_script_word(cleaned)
    ):
        return None
    if len(cleaned) <= limit:
        return cleaned
    cut = cleaned[: max(limit - 1, 1)]
    if " " in cut:
        cut = cut.rsplit(" ", 1)[0]
    return cut.rstrip(" ,.;:-") + "…"
