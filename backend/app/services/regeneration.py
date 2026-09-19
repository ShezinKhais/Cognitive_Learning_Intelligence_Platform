"""Replacing one draft question with a newly generated one.

Owner: Cyber 2 with AI 1, Phase 2.

A lecturer who does not like a draft can ask for another instead of editing
it. The replacement is generated from the same page's stored chunks, so it is
grounded in the same part of the material and passes the same checks as the
drafts made at upload. The old draft is rejected rather than deleted, so the
review history still shows what was replaced.
"""

from __future__ import annotations

import logging
import re
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import ConflictError, ServiceUnavailableError
from app.models.question import Question
from app.repositories.material_repository import MaterialRepository
from app.repositories.question_repository import QuestionRepository
from app.services.extraction import ContentChunk
from app.services.material_seams import DraftQuestion, QuestionGenerator
from app.services.material_store import question_row

log = logging.getLogger("clip.regeneration")

# Asking for a few candidates rather than one gives the checks room to reject
# a bad draft, or one that repeats the question being replaced.
REPLACEMENT_CANDIDATES = 3


def _same_question(a: str, b: str) -> bool:
    def words(text: str) -> list[str]:
        return re.findall(r"[a-z0-9]+", text.lower())

    return words(a) == words(b)


async def regenerate(
    question: Question,
    reviewer_id: UUID,
    session: AsyncSession,
    generator: QuestionGenerator,
) -> Question:
    """Reject `question` and return the new draft that replaces it.

    Only a draft can be replaced. Once a question is approved a lecturer has
    vouched for it, and swapping it silently would undo that.
    """
    _require_draft(question)

    material_id = question.source_material_id
    materials = MaterialRepository(session)
    stored = await materials.list_chunks(material_id, page=question.source_slide)
    if not stored:
        stored = await materials.list_chunks(material_id)
    if not stored:
        raise ConflictError(
            "This material has no stored content to generate a question from.",
            {"material_id": str(material_id)},
        )

    chunks = [
        ContentChunk(
            chunk_id=chunk.chunk_id,
            chunk_index=chunk.chunk_index,
            material_id=material_id,
            chunk_text=chunk.chunk_text,
            source_page=chunk.source_page or 1,
        )
        for chunk in stored
    ]
    # Generation takes seconds. Ending the read transaction first returns the
    # connection to the pool instead of holding it for the whole model call,
    # so a lecturer regenerating a batch cannot starve every other request.
    await session.commit()
    try:
        drafts = await generator.generate(material_id, chunks, count=REPLACEMENT_CANDIDATES)
    except Exception:
        log.exception("regeneration failed for question %s", question.question_id)
        raise ServiceUnavailableError(
            "The question generator did not respond. Try again shortly.", {}
        ) from None

    replacement = _first_usable(drafts, question.question_text)
    if replacement is None:
        raise ServiceUnavailableError(
            "No usable replacement was generated this time. Try again.",
            {"candidates": len(drafts)},
        )

    # The question may have been reviewed, or regenerated from another tab,
    # while the model ran. Re-read it under a row lock so only one of two
    # overlapping requests can replace it.
    await session.refresh(question, with_for_update=True)
    _require_draft(question)

    await QuestionRepository(session).apply_review(
        question, status="rejected", reviewer_id=reviewer_id
    )
    new = question_row(material_id, replacement, session_id=question.session_id)
    session.add(new)
    await session.flush()
    await session.refresh(new)
    return new


def _require_draft(question: Question) -> None:
    if question.status != "draft":
        raise ConflictError(
            "Only a draft question can be regenerated.",
            {"question_id": str(question.question_id), "status": question.status},
        )


def _first_usable(drafts, replaced_prompt: str) -> DraftQuestion | None:
    for draft in drafts:
        try:
            problem = draft.problem()
        except Exception:
            continue
        if problem is None and not _same_question(draft.prompt, replaced_prompt):
            return draft
    return None
