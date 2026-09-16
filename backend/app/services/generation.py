"""Generation service for multiple-choice questions."""

from __future__ import annotations

import json
import logging
import re
from collections.abc import Sequence
from dataclasses import dataclass
from uuid import UUID

from rapidfuzz import fuzz

from app.schemas.content import Difficulty, QuestionType
from app.services.extraction import ContentChunk
from app.services.pipeline import DraftQuestion
from app.services.retrieval import RetrievedChunk

OPTION_COUNT = 4
GROUNDING_THRESHOLD = 80
ANSWER_SUPPORT_THRESHOLD = 40


def rejection_reasons(draft: DraftQuestion, chunks: list[RetrievedChunk]) -> list[str]:
    """Every reason this draft is unusable. Empty list means it passed."""
    reasons: list[str] = []
    options = draft.options or ()

    if not draft.prompt.strip():
        reasons.append("prompt is empty")

    if len(options) != OPTION_COUNT:
        reasons.append(f"expected {OPTION_COUNT} options, got {len(options)}")

    if any(o.strip().startswith("{") for o in options):
        reasons.append("options are objects, not answer strings")

    cleaned = [o.strip().lower() for o in options]
    if len(set(cleaned)) != len(cleaned):
        reasons.append("options contain duplicates")

    def normalised(option: str) -> str:
        words = re.findall(r"[a-z0-9]+", option.lower())
        return " ".join(sorted(words))

    if len({normalised(o) for o in options}) != len(options):
        reasons.append("options are reorderings of each other")

    if draft.correct_option is None or not 0 <= draft.correct_option < len(options):
        reasons.append(f"correct_option {draft.correct_option} is out of range")

    pages = {chunk.source_page for chunk in chunks}
    # A question with no citation cannot be traced back to the material, which
    # is the point of the feature.
    if draft.source_slide is None:
        reasons.append("no page or slide citation")
    elif draft.source_slide not in pages:
        reasons.append(f"cites page {draft.source_slide}, not among {sorted(pages)}")

    if not draft.source_excerpt:
        reasons.append("no source excerpt, so grounding cannot be checked")
    else:
        # Page membership and excerpt matching were checked independently, so a
        # question could cite page 3 while quoting page 4 and pass both.
        cited_chunks = (
            [c for c in chunks if c.source_page == draft.source_slide]
            if draft.source_slide is not None
            else chunks
        )
        best = max(
            (fuzz.partial_ratio(draft.source_excerpt, c.chunk_text) for c in cited_chunks),
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
  "correct_option": the index of the correct answer, counting from 0.
                    The first option is 0 and the last is 3. Never use 4.
  "topic": a short topic label
  "source_slide": the page number of the excerpt you used
  "source_excerpt": the sentence from that excerpt the answer comes from,
                    copied as closely as you can

Example of the exact format required:

[
  {{
    "prompt": "What is frozen during transfer learning?",
    "options": ["The base layers", "The output layer", "The dataset", "The optimiser"],
    "correct_option": 0,
    "topic": "Transfer learning",
    "source_slide": 3,
    "source_excerpt": "The base layers are frozen"
  }}
]

"options" must be an array of exactly 4 plain strings. Not objects. Not 3.
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
        if not isinstance(item, dict):
            drafts.append(
                DraftQuestion(
                    type=QuestionType.MCQ,
                    difficulty=Difficulty.MEDIUM,
                    prompt="",
                    options=(),
                    correct_option=-1,
                )
            )
            continue

        raw_options = item.get("options") or []
        if not isinstance(raw_options, list):
            raw_options = []
        # A non-string option kept as a bare string would look valid: [1,2,3,4]
        # becomes ['1','2','3','4'] and passes every check.
        options = tuple(
            o if isinstance(o, str) else json.dumps({"_invalid_option": o}) for o in raw_options
        )

        try:
            correct = int(item.get("correct_option", -1))
        except (TypeError, ValueError):
            correct = -1

        try:
            slide = item.get("source_slide")
            slide = int(slide) if slide is not None else None
        except (TypeError, ValueError):
            slide = None

        try:
            difficulty = Difficulty(item.get("difficulty") or "medium")
        except ValueError:
            difficulty = Difficulty.MEDIUM

        drafts.append(
            DraftQuestion(
                type=QuestionType.MCQ,
                difficulty=difficulty,
                prompt=str(item.get("prompt") or ""),
                options=options,
                correct_option=correct,
                topic=item.get("topic"),
                source_slide=slide,
                source_excerpt=item.get("source_excerpt"),
            )
        )
    return drafts


class QuestionGenerator:
    """Asks the model for questions about the given chunks, keeps the valid ones.

    Chunks arrive from the pipeline rather than from retrieval: at upload time
    every chunk of the material is new, so there is nothing to search against.
    Retrieval serves the student feedback path instead.
    """

    def __init__(self, client, model: str, count: int = 5) -> None:
        self._client = client
        self._model = model
        self._count = count

    async def generate(
        self, material_id: UUID, chunks: Sequence[ContentChunk]
    ) -> Sequence[DraftQuestion]:
        if not chunks:
            return []

        outcome = await self._draft(chunks)
        for _, reasons in outcome.rejected:
            logger.info("rejected draft question: %s", "; ".join(reasons))
        return outcome.accepted

    async def _draft(self, chunks) -> GenerationOutcome:
        """Kept separate so tests can see what was rejected and why."""
        response = await self._client.chat.completions.create(
            model=self._model,
            messages=[{"role": "user", "content": build_prompt(chunks, self._count)}],
        )
        drafts = parse_drafts(response.choices[0].message.content or "")

        accepted, rejected = [], []
        for draft in drafts:
            reasons = rejection_reasons(draft, chunks)
            if reasons:
                rejected.append((draft, reasons))
            else:
                accepted.append(draft)

        return GenerationOutcome(accepted=accepted, rejected=rejected)
