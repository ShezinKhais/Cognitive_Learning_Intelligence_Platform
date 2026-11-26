"""Persist successful student tutor exchanges without retaining partial replies.

Only terminal completed exchanges are stored. This wrapper does not
change the tutor, source selection, guardrails, or lecturer controls.
"""

from __future__ import annotations

import json
import logging
from collections.abc import AsyncIterator
from uuid import UUID

from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert

from app.core.database import get_session_factory
from app.models.student_chat_exchange import StudentChatExchange
from app.models.user import User

log = logging.getLogger("clip.tutor.history")

# Keep storage bounded independently of time-based retention.
MAX_HISTORY_PER_STUDENT = 500


async def save_completed_exchange(
    *,
    student_id: UUID,
    session_id: UUID,
    request_id: str,
    question: str,
    answer: str,
    source: str,
    citations: list[dict],
    follow_ups: list[str],
    general: bool,
) -> None:
    """Insert one successfully completed exchange, idempotently.

    The authenticated student ID must come from the principal, never
    from the request body. Duplicate request IDs cannot create duplicates.
    """
    statement = (
        insert(StudentChatExchange)
        .values(
            student_id=student_id,
            session_id=session_id,
            request_id=request_id,
            question=question,
            answer=answer,
            source=source,
            phase="completed",
            citations=citations,
            follow_ups=follow_ups,
            general=general,
            explanation=None,
        )
        .on_conflict_do_nothing(constraint="uq_student_chat_exchange_student_request")
    )

    async with get_session_factory()() as db:
        # Serialize history writes for this student so concurrent saves
        # cannot each leave more than the configured maximum.
        await db.scalar(select(User.user_id).where(User.user_id == student_id).with_for_update())

        await db.execute(statement)

        # Keep the newest exchanges. The UUID resolves timestamp ties.
        expired_ids = (
            select(StudentChatExchange.id)
            .where(StudentChatExchange.student_id == student_id)
            .order_by(
                StudentChatExchange.created_at.desc(),
                StudentChatExchange.id.desc(),
            )
            .offset(MAX_HISTORY_PER_STUDENT)
        )

        await db.execute(
            delete(StudentChatExchange).where(
                StudentChatExchange.student_id == student_id,
                StudentChatExchange.id.in_(expired_ids),
            )
        )
        await db.commit()


async def save_completed_stream(
    stream: AsyncIterator[bytes],
    *,
    student_id: UUID,
    session_id: UUID,
    request_id: str,
    question: str,
    source: str,
) -> AsyncIterator[bytes]:
    """Forward original NDJSON and persist only after terminal completion.

    Never hold a database connection while the model generates tokens.
    A storage failure must not turn a completed model reply into an
    interrupted response. Partial, refused and failed streams are not saved.
    """
    answer_parts: list[str] = []
    citations: list[dict] = []
    follow_ups: list[str] = []
    general = False
    completed = False

    async for chunk in stream:
        event = json.loads(chunk)
        event_type = event.get("type")

        if event_type == "delta":
            answer_parts.append(event.get("text", ""))
            if event.get("grounded") is False:
                general = True
        elif event_type == "citation":
            citation = event.get("citation")
            if isinstance(citation, dict):
                if not any(previous.get("id") == citation.get("id") for previous in citations):
                    citations.append(citation)
        elif event_type == "follow_up":
            prompt = event.get("prompt")
            if isinstance(prompt, str) and prompt not in follow_ups:
                follow_ups.append(prompt)
        elif event_type == "completed" and not completed:
            completed = True
            try:
                await save_completed_exchange(
                    student_id=student_id,
                    session_id=session_id,
                    request_id=request_id,
                    question=question,
                    answer="".join(answer_parts),
                    source=source,
                    citations=citations,
                    follow_ups=follow_ups,
                    general=general,
                )
            except Exception as exc:
                # The database driver hides SQL parameters. Do not log
                # the student's question, answer or conversation content.
                log.warning(
                    "tutor history write failed request=%s error=%s",
                    request_id,
                    type(exc).__name__,
                )

        yield chunk
