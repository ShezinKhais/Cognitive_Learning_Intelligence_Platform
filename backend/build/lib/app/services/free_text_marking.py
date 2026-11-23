"""Marks free-text answers in a live class, after they are stored.

Owner: AI 1 (the classifier, free_text_classifier.py) and BBIS (where the
result is kept, comprehension_writer.save_classification). Wired by General
CS in Phase 8: until then the classifier ran only in the evaluation script,
and a free-text answer was stored with no label at all.

The student's receipt never waits for the model. The answer is stored and
acknowledged as before, then marked here in the background through the AI
gateway, at background priority so a class's tutor questions go first. The
label it stores is what topics, alerts and reports read, and an answer that
already has a label keeps it.

A question with no reference answer or key points cannot be marked, and is
left unlabelled, as is an answer whose marking fails: it is logged, and the
class carries on.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from functools import lru_cache
from typing import Protocol
from uuid import UUID

from app.core.config import get_settings
from app.core.database import get_session_factory
from app.models.question import Question
from app.repositories.question_repository import QuestionRepository
from app.schemas.content import QuestionType
from app.services.comprehension_writer import save_classification
from app.services.free_text_classifier import (
    Classification,
    FreeTextClassifier,
    FreeTextQuestion,
)

log = logging.getLogger("clip.free_text_marking")


class Classifier(Protocol):
    model: str

    async def classify(self, question: FreeTextQuestion, answer: str) -> Classification: ...


@lru_cache
def _gateway_classifier() -> Classifier:
    from app.services.ai_gateway import GatewayEmbeddingClient, Priority, get_ai_gateway

    gateway = get_ai_gateway()
    return FreeTextClassifier(
        gateway.chat_client("free_text_marking", priority=Priority.BACKGROUND),
        GatewayEmbeddingClient(gateway, "free_text_marking", priority=Priority.BACKGROUND),
        get_settings().ollama_model,
    )


# Replaced in tests.
classifier: Callable[[], Classifier] = _gateway_classifier

# Held so a marking in progress is not collected half way: asyncio keeps only
# a weak reference to a task.
_marking: set[asyncio.Task[None]] = set()


def gradable(question: Question | None) -> FreeTextQuestion | None:
    """The question as the classifier reads it, or None when it cannot be
    marked: not free text, or without its reference answer or key points."""
    if (
        question is None
        or question.question_type != QuestionType.FREE_TEXT.value
        or not question.reference_answer
        or not question.key_points
    ):
        return None
    return FreeTextQuestion(
        prompt=question.question_text,
        reference_answer=question.reference_answer,
        key_points=tuple(question.key_points),
    )


def mark_later(response_id: UUID, question_id: UUID, answer: str) -> None:
    """Mark a stored answer in the background."""
    task = asyncio.create_task(
        mark(response_id, question_id, answer), name=f"free-text-marking-{response_id}"
    )
    _marking.add(task)
    task.add_done_callback(_marking.discard)


async def mark(response_id: UUID, question_id: UUID, answer: str) -> bool:
    """Mark one stored answer and keep the result. Returns whether a label
    was stored."""
    try:
        async with get_session_factory()() as db:
            source = await QuestionRepository(db).get_by_id(question_id)
            session_id = source.session_id if source is not None else None
            question = gradable(source)
        if question is None:
            return False
        marker = classifier()
        result = await marker.classify(question, answer)
        async with get_session_factory()() as db:
            stored = await save_classification(
                db,
                response_id=response_id,
                label=result.label,
                confidence=result.confidence,
                score=result.score,
                feedback=result.feedback,
                model_name=result.model,
                prompt_version=result.prompt_version if result.model else None,
                reasons=result.reasons,
                key_point_coverage=[c.value for c in result.coverage],
                wrong_claim=result.wrong_claim,
                similarity=result.similarity,
            )
            await db.commit()
        if stored and session_id is not None:
            from app.realtime.classroom import classroom

            await classroom.refresh_comprehension(session_id, question_id)
        return stored
    except Exception:
        log.exception("could not mark free-text answer %s", response_id)
        return False
