"""Select staged questions supported by recent live lecture transcripts."""

from datetime import timedelta
from uuid import UUID

from sqlalchemy import select

from app.models.discussion_note import DiscussionNote
from app.repositories.session_repository import SessionRepository
from app.services.lecture_question_match import (
    recent_transcript_segments,
    supported_by_recent_lecture,
)

PAGE_SIZE = 100
MAX_CANDIDATES = 500


async def choose_recent_question(db, session, checkpoint_at) -> UUID | None:
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

    for offset in range(0, MAX_CANDIDATES, PAGE_SIZE):
        candidates, _ = await repository.list_deliverable(
            session,
            limit=PAGE_SIZE,
            offset=offset,
        )
        if not candidates:
            break

        for question in candidates:
            if supported_by_recent_lecture(
                question.question_text,
                question.topic,
                segments,
            ):
                return question.question_id

        if len(candidates) < PAGE_SIZE:
            break

    return None
