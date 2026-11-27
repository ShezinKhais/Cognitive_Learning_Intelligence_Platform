"""Persist successful student tutor exchanges without retaining partial replies.

Only terminal completed exchanges are stored. This wrapper does not
change the tutor, source selection, guardrails, or lecturer controls.
"""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import AsyncIterator
from datetime import datetime
from uuid import UUID

from sqlalchemy import delete, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.store import get_consent_repository
from app.core.config import get_settings
from app.core.database import get_session_factory
from app.models.consent import Consent
from app.models.student_chat_exchange import StudentChatExchange
from app.models.user import User
from app.schemas.identity import ConsentType

log = logging.getLogger("clip.tutor.history")

# Keep storage bounded independently of time-based retention.
MAX_HISTORY_PER_STUDENT = 500
HISTORY_SAVE_TIMEOUT_SECONDS = 3


async def history_permission(
    db: AsyncSession, student_id: UUID, *, lock: bool = False
) -> tuple[int, datetime] | None:
    """Read the account generation and current terms grant for a saved reply."""
    user = select(User.chat_history_generation).where(
        User.user_id == student_id, User.active.is_(True), User.role == "student"
    )
    # FOR NO KEY UPDATE serializes account changes and our writes while
    # allowing a concurrent consent audit to reference the account by FK.
    generation = await db.scalar(user.with_for_update(key_share=True) if lock else user)
    if generation is None:
        return None
    settings = get_settings()
    if not settings.is_production:
        consent = get_consent_repository(settings).get(student_id, ConsentType.TERMS)
        return (generation, consent.recorded_at) if consent and consent.granted else None

    grant = select(Consent.recorded_at).where(
        Consent.user_id == student_id, Consent.consent_type == "terms", Consent.granted.is_(True)
    )
    recorded_at = await db.scalar(grant.with_for_update() if lock else grant)
    return (generation, recorded_at) if recorded_at is not None else None


async def invalidate_history_writes(db: AsyncSession, student_id: UUID) -> None:
    """Serialize deletion against writes and invalidate any older stream."""
    await db.execute(
        update(User)
        .where(User.user_id == student_id)
        .values(chat_history_generation=User.chat_history_generation + 1)
    )


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
    permission: tuple[int, datetime] | None,
) -> bool:
    """Insert one successfully completed exchange, idempotently.

    The authenticated student ID must come from the principal, never
    from the request body. Duplicate request IDs cannot create duplicates.
    """
    if permission is None:
        return False

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
        # Serialize saves, deletion and account changes for this student.
        if await history_permission(db, student_id, lock=True) != permission:
            return False

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
        return True


async def save_completed_stream(
    stream: AsyncIterator[bytes],
    *,
    student_id: UUID,
    session_id: UUID,
    request_id: str,
    question: str,
    source: str,
    permission: tuple[int, datetime] | None = None,
) -> AsyncIterator[bytes]:
    """Forward NDJSON and flag an unsaved reply at terminal completion.

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
                async with asyncio.timeout(HISTORY_SAVE_TIMEOUT_SECONDS):
                    saved = await save_completed_exchange(
                        student_id=student_id,
                        session_id=session_id,
                        request_id=request_id,
                        question=question,
                        answer="".join(answer_parts),
                        source=source,
                        citations=citations,
                        follow_ups=follow_ups,
                        general=general,
                        permission=permission,
                    )
            except Exception as exc:
                saved = False
                # The database driver hides SQL parameters. Do not log
                # the student's question, answer or conversation content.
                log.warning(
                    "tutor history write failed request=%s error=%s",
                    request_id,
                    type(exc).__name__,
                )
            if not saved:
                event["history_saved"] = False
                chunk = (json.dumps(event) + "\n").encode()

        yield chunk
