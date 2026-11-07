"""Authorized, bounded publication and retrieval of session minutes."""

from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import NotFoundError, ValidationError
from app.models.discussion_note import DiscussionNote
from app.models.session import Session
from app.repositories.session_repository import SessionRepository
from app.schemas.discussion import DiscussionWrite
from app.schemas.identity import Role
from app.services.course_membership import courses_of_user

MAX_NOTES = 1400


async def accessible_session(
    db: AsyncSession, session_id: UUID, user_id: UUID, role: Role, *, write: bool = False
) -> Session:
    row = await SessionRepository(db).get(session_id, for_update=write)
    allowed = row is not None and (
        role == Role.ADMIN
        or (role == Role.LECTURER and row.instructor_id == user_id)
        or (
            not write
            and role == Role.STUDENT
            and await db.scalar(
                select(Session.session_id).where(
                    Session.session_id == session_id,
                    Session.course_id.in_(courses_of_user(user_id)),
                )
            )
            is not None
        )
    )
    if not allowed or row.status not in {"active", "ended"}:
        raise NotFoundError("Discussion notes are unavailable.")
    return row


async def notes_for(db: AsyncSession, session_id: UUID) -> list[DiscussionNote]:
    return list(
        await db.scalars(
            select(DiscussionNote)
            .where(DiscussionNote.session_id == session_id)
            .order_by(DiscussionNote.occurred_at, DiscussionNote.note_id)
            .limit(MAX_NOTES)
        )
    )


async def save(
    db: AsyncSession, session_id: UUID, note_id: UUID, payload: DiscussionWrite
) -> DiscussionNote:
    if not payload.shareable_confirmed:
        raise ValidationError("Confirm these minutes are reviewed and suitable for the course.")
    if payload.occurred_at > datetime.now(UTC) + timedelta(minutes=1):
        raise ValidationError("Discussion time cannot be in the future.")
    note = await db.get(DiscussionNote, note_id)
    if note is not None and note.session_id != session_id:
        raise NotFoundError("Discussion note was not found.")
    if note is None:
        count = await db.scalar(
            select(func.count())
            .select_from(DiscussionNote)
            .where(DiscussionNote.session_id == session_id)
        )
        if count >= MAX_NOTES:
            raise ValidationError("This session has 1400 entries. Edit an existing note.")
        note = DiscussionNote(note_id=note_id, session_id=session_id)
        db.add(note)
    note.occurred_at, note.text = payload.occurred_at, payload.text
    note.origin = "lecturer"
    await db.commit()
    await db.refresh(note)
    return note
