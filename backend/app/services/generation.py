"""Generation service for multiple-choice questions."""

from __future__ import annotations

import json
import logging
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


logger = logging.getLogger(__name__)

PROMPT_TEMPLATE = """You write multiple-choice questions for university lecturers.

Use ONLY the numbered excerpts below. Do not use outside knowledge.

{excerpts}

Write {count} multiple-choice questions. Reply with a JSON array and nothing
else - no markdown fences, no explanation.

Each object must have exactly these keys:
  "prompt": the question
  "options": exactly 4 answer strings, all different
  "correct_option": the 0-based index of the correct answer
  "topic": a short topic label
  "source_slide": the page number of the excerpt you used
  "source_excerpt": the sentence from that excerpt the answer comes from,
                    copied as closely as you can
"""


@dataclass(frozen=True)
class GenerationOutcome:
    """What generation produced, and what it threw away."""

    accepted: list[DraftQuestion]
    rejected: list[tuple[DraftQuestion, list[str]]]


def build_prompt(chunks: list[RetrievedChunk], count: int) -> str:
    excerpts = "\n\n".join(f"[page {chunk.source_page}]\n{chunk.chunk_text}" for chunk in chunks)
    return PROMPT_TEMPLATE.format(excerpts=excerpts, count=count)


def parse_drafts(raw: str) -> list[DraftQuestion]:
    """Turn the model's reply into drafts, tolerating markdown fences."""
    text = raw.strip()
    if text.startswith("```"):
        text = text.split("```")[1]
        if text.startswith("json"):
            text = text[4:]

    payload = json.loads(text)
    if not isinstance(payload, list):
        raise ValueError("expected a JSON array of questions")

    drafts = []
    for item in payload:
        drafts.append(
            DraftQuestion(
                prompt=str(item.get("prompt", "")),
                options=[str(o) for o in item.get("options", [])],
                correct_option=int(item.get("correct_option", -1)),
                topic=item.get("topic"),
                source_slide=item.get("source_slide"),
                source_excerpt=item.get("source_excerpt"),
            )
        )
    return drafts
