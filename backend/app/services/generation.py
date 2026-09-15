from __future__ import annotations

from dataclasses import dataclass

from rapidfuzz import fuzz

from app.services.retrieval import RetrievedChunk

OPTION_COUNT = 4
GROUNDING_THRESHOLD = 80


@dataclass(frozen=True)
class DraftQuestion:
    """A question as the model produced it, before anyone has checked it."""

    prompt: str
    options: list[str]
    correct_option: int
    topic: str | None
    source_slide: int | None
    source_excerpt: str | None


def rejection_reasons(draft: DraftQuestion, chunks: list[RetrievedChunk]) -> list[str]:
    """Every reason this draft is unusable. Empty list means it passed."""
    reasons: list[str] = []

    if not draft.prompt.strip():
        reasons.append("prompt is empty")

    if len(draft.options) != OPTION_COUNT:
        reasons.append(f"expected {OPTION_COUNT} options, got {len(draft.options)}")

    # Duplicates mean either two correct answers or an unanswerable question.
    cleaned = [option.strip().lower() for option in draft.options]
    if len(set(cleaned)) != len(cleaned):
        reasons.append("options contain duplicates")

    if not 0 <= draft.correct_option < len(draft.options):
        reasons.append(f"correct_option {draft.correct_option} is out of range")

    pages = {chunk.source_page for chunk in chunks}
    if draft.source_slide is not None and draft.source_slide not in pages:
        reasons.append(f"cites page {draft.source_slide}, not among {sorted(pages)}")

    if not draft.source_excerpt:
        reasons.append("no source excerpt, so grounding cannot be checked")
    else:
        # The model paraphrases, so exact matching would reject good questions.
        # partial_ratio finds the best-matching window inside the chunk.
        best = max(
            (fuzz.partial_ratio(draft.source_excerpt, chunk.chunk_text) for chunk in chunks),
            default=0,
        )
        if best < GROUNDING_THRESHOLD:
            reasons.append(f"excerpt not grounded in any chunk (best match {best:.0f})")

    return reasons
