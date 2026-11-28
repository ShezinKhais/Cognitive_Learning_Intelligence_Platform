"""Select staged questions supported by recent live lecture transcripts."""

import asyncio
from datetime import timedelta
from math import isfinite, sqrt
from uuid import UUID

from sqlalchemy import select

from app.models.discussion_note import DiscussionNote
from app.repositories.session_repository import SessionRepository
from app.services.ai_gateway import AiUnavailableError, Priority, get_ai_gateway
from app.services.lecture_question_match import (
    recent_transcript_segments,
    supported_by_recent_lecture,
)

PAGE_SIZE = 100
MAX_CANDIDATES = 500
SEMANTIC_CANDIDATES = 16
SEMANTIC_WINDOW_COUNT = 12
SEMANTIC_MIN_COSINE = 0.82
SEMANTIC_MIN_MARGIN = 0.06


async def choose_recent_question(db, session, checkpoint_at, *, semantic=False) -> UUID | None:
    """Choose an eligible staged question, or abstain.

    Only this session's recent live-transcription notes count.
    Never use lecturer-written notes as automatic teaching evidence.
    """
    beginning = checkpoint_at - timedelta(minutes=20)

    result = await db.scalars(
        select(DiscussionNote)
        .where(
            DiscussionNote.session_id == session.session_id,
            DiscussionNote.origin == "live_transcript",
            DiscussionNote.occurred_at >= beginning,
            DiscussionNote.occurred_at <= checkpoint_at,
        )
        .order_by(DiscussionNote.occurred_at, DiscussionNote.note_id)
        .limit(1200)
    )

    segments = recent_transcript_segments(result.all(), checkpoint_at)
    if not segments:
        return None

    repository = SessionRepository(db)

    for_semantic = []
    for offset in range(0, MAX_CANDIDATES, PAGE_SIZE):
        candidates, _ = await repository.list_deliverable(
            session,
            limit=PAGE_SIZE,
            offset=offset,
        )
        if not candidates:
            break

        for_semantic.extend(candidates[: max(0, SEMANTIC_CANDIDATES - len(for_semantic))])
        for question in candidates:
            if supported_by_recent_lecture(
                question.question_text,
                question.topic,
                segments,
            ):
                return question.question_id

        if len(candidates) < PAGE_SIZE:
            break

    if semantic and for_semantic:
        return await semantic_match(for_semantic, segments)
    return None


def cosine(left: list[float], right: list[float]) -> float:
    products = list(zip(left, right, strict=True))
    scale = sqrt(sum(x * x for x, _ in products) * sum(y * y for _, y in products))
    if not scale or not isfinite(scale):
        return 0
    return sum(x * y for x, y in products) / scale


async def semantic_match(candidates, notes: list[str]) -> UUID | None:
    """Bounded fallback when captions and questions use different words.

    Compare the complete question to chronological groups of transcript notes.
    A weak or ambiguous result is an abstention, as is a busy gateway.
    """
    windows = [" ".join(notes[index : index + 3])[:1200] for index in range(0, len(notes), 3)]
    if len(windows) > SEMANTIC_WINDOW_COUNT:
        step = (len(windows) - 1) / (SEMANTIC_WINDOW_COUNT - 1)
        windows = [windows[round(index * step)] for index in range(SEMANTIC_WINDOW_COUNT)]
    prompts = [f"{item.question_text} {item.topic or ''}"[:1000] for item in candidates]
    try:
        async with asyncio.timeout(2):
            vectors = await get_ai_gateway().embed(
                windows + prompts,
                purpose="lecture_checkpoint_match",
                priority=Priority.BACKGROUND,
                max_attempts=1,
            )
        if len(vectors) != len(windows) + len(prompts):
            return None
        evidence = vectors[: len(windows)]
        scores = sorted(
            (
                (max(cosine(vector, window) for window in evidence), index)
                for index, vector in enumerate(vectors[len(windows) :])
            ),
            reverse=True,
        )
    except (AiUnavailableError, TimeoutError, ValueError, ArithmeticError):
        return None
    score, index = scores[0]
    runner_up = scores[1][0] if len(scores) > 1 else 0.0
    if score >= SEMANTIC_MIN_COSINE and score - runner_up >= SEMANTIC_MIN_MARGIN:
        return candidates[index].question_id
    return None
