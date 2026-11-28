"""Private, student-owned history of chatbot exchanges.

Lecturer and admin roles have no access. This API never exposes
student chatbot analytics or reads another student's conversations.
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from sqlalchemy import delete, func, select, tuple_

from app.api.deps import (
    AppSettings,
    CurrentUser,
    DbSession,
    require_roles,
)
from app.core.audit import audit_action
from app.models.student_chat_exchange import StudentChatExchange
from app.schemas.identity import Role
from app.services.chat_history_persistence import invalidate_history_writes

router = APIRouter(
    prefix="/me/chat-history",
    tags=["student-chat-history"],
    dependencies=[Depends(require_roles(Role.STUDENT))],
)


def _out(row: StudentChatExchange) -> dict:
    return {
        "id": str(row.id),
        "request_id": row.request_id,
        "session_id": str(row.session_id) if row.session_id else None,
        "question": row.question,
        "answer": row.answer,
        "source": row.source,
        "phase": row.phase,
        "citations": row.citations,
        "follow_ups": row.follow_ups,
        "general": row.general,
        "explanation": row.explanation,
        "created_at": row.created_at,
    }


@router.get("")
async def my_chat_history(
    principal: CurrentUser,
    db: DbSession,
    response: Response,
    limit: int = Query(default=100, ge=1, le=200),
    offset: int = Query(default=0, ge=0, le=100_000),
    session_id: UUID | None = None,
    before: str | None = None,
) -> dict:
    """Return only this student's conversations, newest first."""
    response.headers["Cache-Control"] = "no-store"
    owner = StudentChatExchange.student_id == principal.user_id
    conditions = [owner]
    if session_id is not None:
        conditions.append(StudentChatExchange.session_id == session_id)
    total = await db.scalar(
        select(func.count()).select_from(StudentChatExchange).where(*conditions)
    )

    page_conditions = list(conditions)
    if before is not None:
        stamp, separator, record_id = before.partition("|")
        try:
            if not separator or len(before) > 120:
                raise ValueError("Malformed cursor")
            timestamp = datetime.fromisoformat(stamp)
            identifier = UUID(record_id)
            if timestamp.tzinfo is None or timestamp.utcoffset() is None:
                raise ValueError("Cursor timestamp needs a timezone")
        except ValueError as exc:
            raise HTTPException(
                status_code=422,
                detail="Invalid chat history cursor.",
            ) from exc

        page_conditions.append(
            tuple_(
                StudentChatExchange.created_at,
                StudentChatExchange.id,
            )
            < (timestamp, identifier)
        )

    rows = (
        await db.scalars(
            select(StudentChatExchange)
            .where(*page_conditions)
            .order_by(StudentChatExchange.created_at.desc(), StudentChatExchange.id.desc())
            .limit(limit)
            .offset(0 if before is not None else offset)
        )
    ).all()
    next_before = None
    if len(rows) == limit:
        oldest = rows[-1]
        next_before = f"{oldest.created_at.isoformat()}|{oldest.id}"

    return {
        "items": [_out(row) for row in rows],
        "total": total or 0,
        "limit": limit,
        "offset": offset,
        "next_before": next_before,
    }


@router.delete("", status_code=204)
@audit_action("STUDENT_CHAT_HISTORY_CLEARED")
async def delete_my_chat_history(
    principal: CurrentUser, db: DbSession, response: Response, settings: AppSettings
) -> None:
    """Delete all of this student's history, not anyone else's."""
    response.headers["Cache-Control"] = "no-store"
    await invalidate_history_writes(db, principal.user_id)
    await db.execute(
        delete(StudentChatExchange).where(StudentChatExchange.student_id == principal.user_id)
    )


@router.delete("/{exchange_id}", status_code=204)
@audit_action("STUDENT_CHAT_EXCHANGE_DELETED")
async def delete_my_chat_exchange(
    exchange_id: UUID,
    principal: CurrentUser,
    db: DbSession,
    response: Response,
    settings: AppSettings,
) -> None:
    """Delete one owned exchange; never reveal whether another student's exists."""
    response.headers["Cache-Control"] = "no-store"
    await invalidate_history_writes(db, principal.user_id)
    await db.execute(
        delete(StudentChatExchange).where(
            StudentChatExchange.student_id == principal.user_id,
            StudentChatExchange.id == exchange_id,
        )
    )
