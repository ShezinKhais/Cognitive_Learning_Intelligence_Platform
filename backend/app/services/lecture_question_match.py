"""Conservative lexical evidence gate for lecture checkpoint candidates."""

from __future__ import annotations

import re
from collections.abc import Iterable
from datetime import datetime, timedelta

STOPWORDS = frozenset(
    {
        "a",
        "an",
        "and",
        "are",
        "as",
        "at",
        "be",
        "by",
        "can",
        "define",
        "describe",
        "do",
        "does",
        "explain",
        "for",
        "from",
        "how",
        "in",
        "into",
        "is",
        "it",
        "of",
        "on",
        "or",
        "the",
        "their",
        "them",
        "these",
        "this",
        "to",
        "what",
        "when",
        "where",
        "which",
        "why",
        "with",
        "give",
        "example",
        "following",
        "about",
        "between",
        "difference",
    }
)

TOKEN_PATTERN = re.compile(r"[^\W_]+", re.UNICODE)
ARABIC_MARKS = re.compile(r"[ـً-ٰٟ]")
ARABIC_VARIANTS = str.maketrans("أإآٱى", "ااااي")
ARABIC_STOP = frozenset({"ماذا", "لماذا", "اشرح", "عرف", "هذا", "هذه", "الذي", "التي"})


def normalize_token(token: str) -> str:
    """Normalize simple English plurals without changing Arabic words."""
    if (
        token.isascii()
        and token.isalpha()
        and len(token) >= 5
        and token.endswith("s")
        and not token.endswith(("ss", "us", "is"))
    ):
        return token[:-1]
    if token.startswith("ال") and len(token) >= 5:
        return token[2:]
    return token


def concepts(text: str) -> set[str]:
    """Extract substantive words with conservative plural normalization."""
    normalized = ARABIC_MARKS.sub("", text.casefold()).translate(ARABIC_VARIANTS)
    return {
        normalize_token(token)
        for token in TOKEN_PATTERN.findall(normalized)
        if len(token) >= 3 and token not in STOPWORDS and token not in ARABIC_STOP
    }


def supported_by_recent_lecture(
    question: str,
    topic: str | None,
    recent_segments: Iterable[str],
) -> bool:
    """Require question-specific concepts in recent transcript text.

    A topic word alone is insufficient evidence for a more specific
    concept. This deliberately rejects uncertain matches.
    """
    terms = concepts(question)
    if not terms:
        return False
    required = terms | concepts(topic or "")
    segments = list(recent_segments)
    # Check nearby note text together. Distant mentions from separate
    # lecture topics cannot independently satisfy the same question.
    return any(
        required.issubset(concepts(" ".join(segments[index : index + 3])))
        for index in range(len(segments))
    )


def recent_transcript_segments(
    notes: Iterable[object],
    checkpoint_at: datetime,
    window_minutes: int = 20,
) -> list[str]:
    """Select live Whisper notes from the recent lecture window.

    Exclude lecturer-written notes, future timestamps and older
    transcript segments. Return text in chronological order.
    """
    if not 10 <= window_minutes <= 20:
        raise ValueError("Transcript window must be between 10 and 20 minutes.")
    if checkpoint_at.tzinfo is None or checkpoint_at.utcoffset() is None:
        raise ValueError("Checkpoint timestamp must be timezone-aware.")

    start = checkpoint_at - timedelta(minutes=window_minutes)
    selected = []

    for note in notes:
        occurred_at = getattr(note, "occurred_at", None)
        text = getattr(note, "text", None)
        origin = getattr(note, "origin", None)

        if (
            origin != "live_transcript"
            or not isinstance(occurred_at, datetime)
            or occurred_at.tzinfo is None
            or occurred_at.utcoffset() is None
            or not isinstance(text, str)
            or not text.strip()
        ):
            continue

        if start <= occurred_at <= checkpoint_at:
            selected.append((occurred_at, text.strip()))

    selected.sort(key=lambda item: item[0])
    return [text for _, text in selected]
