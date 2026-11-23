import asyncio
import contextlib
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import delete

from app.api.deps import AppSettings, CurrentUser, DbSession, require_consents, require_roles
from app.core.audit import audit_action
from app.core.errors import ValidationError
from app.models.discussion_note import DiscussionNote
from app.schemas.discussion import (
    DiscussionNoteOut,
    DiscussionOut,
    DiscussionWrite,
    TranscriptDraft,
    TranscriptImport,
    TranscriptList,
)
from app.schemas.identity import ConsentType, Role
from app.services import discussion, live_transcription, transcript_minutes

router = APIRouter(
    prefix="/sessions/{session_id}/discussion",
    tags=["discussion"],
    dependencies=[Depends(require_consents(ConsentType.TERMS))],
)


async def writable_session(session_id: UUID, principal: CurrentUser, db: DbSession) -> None:
    await discussion.accessible_session(
        db, session_id, principal.user_id, principal.role, write=True
    )


@router.get("", response_model=DiscussionOut)
async def read_notes(session_id: UUID, principal: CurrentUser, db: DbSession) -> DiscussionOut:
    session = await discussion.accessible_session(db, session_id, principal.user_id, principal.role)
    notes = await discussion.notes_for(db, session_id)
    return DiscussionOut(
        notes=[DiscussionNoteOut.model_validate(note) for note in notes],
        latest_recorded_at=max((note.occurred_at for note in notes), default=None),
        session_status=session.status,
        live_transcription_active=session.status == "active"
        and session.paused_at is None
        and live_transcription.captures.active(session_id) is not None,
    )


@router.put(
    "/{note_id}",
    response_model=DiscussionNoteOut,
    dependencies=[Depends(require_roles(Role.LECTURER, Role.ADMIN)), Depends(writable_session)],
)
@audit_action("DISCUSSION_NOTE_PUBLISHED")
async def publish_note(
    session_id: UUID,
    note_id: UUID,
    payload: DiscussionWrite,
    principal: CurrentUser,
    db: DbSession,
    request: Request,
    settings: AppSettings,
) -> DiscussionNoteOut:
    return DiscussionNoteOut.model_validate(await discussion.save(db, session_id, note_id, payload))


@router.delete(
    "/{note_id}",
    dependencies=[Depends(require_roles(Role.LECTURER, Role.ADMIN)), Depends(writable_session)],
)
@audit_action("DISCUSSION_NOTE_REMOVED")
async def remove_note(
    session_id: UUID,
    note_id: UUID,
    principal: CurrentUser,
    db: DbSession,
    request: Request,
    settings: AppSettings,
) -> dict[str, bool]:
    await db.execute(
        delete(DiscussionNote).where(
            DiscussionNote.session_id == session_id, DiscussionNote.note_id == note_id
        )
    )
    await db.commit()
    return {"removed": True}


@router.get(
    "/transcripts",
    response_model=TranscriptList,
    dependencies=[Depends(require_roles(Role.LECTURER, Role.ADMIN))],
)
async def available_transcripts(
    session_id: UUID, principal: CurrentUser, db: DbSession, settings: AppSettings
) -> TranscriptList:
    session = await discussion.accessible_session(db, session_id, principal.user_id, principal.role)
    if not settings.teams_transcripts_enabled:
        return TranscriptList(
            enabled=False, message="Teams transcript import is disabled by the administrator."
        )
    if session.status != "ended":
        return TranscriptList(
            enabled=True, message="Finish the class and stop Teams transcription before importing."
        )
    context = await transcript_minutes.context_for(db, session, settings)
    await db.close()
    items = await transcript_minutes.fetch_transcripts(context, settings)
    return TranscriptList(
        enabled=True,
        items=items,
        message=None
        if items
        else "No transcript is available for this class yet. Try again after Teams processing.",
    )


@router.post(
    "/transcript-draft",
    response_model=TranscriptDraft,
    dependencies=[Depends(require_roles(Role.LECTURER, Role.ADMIN)), Depends(writable_session)],
)
@audit_action("DISCUSSION_TRANSCRIPT_DRAFTED", commit=True)
async def import_transcript(
    session_id: UUID,
    payload: TranscriptImport,
    principal: CurrentUser,
    db: DbSession,
    settings: AppSettings,
    request: Request,
) -> TranscriptDraft:
    if not payload.participant_notice_confirmed:
        raise ValidationError(
            "Confirm participants were informed and the institution's transcription "
            "and consent requirements were met."
        )
    session = await discussion.accessible_session(db, session_id, principal.user_id, principal.role)
    context = await transcript_minutes.context_for(db, session, settings)
    await db.close()  # No database connection/lock is held during Graph/model calls.
    transcript_minutes.limiter.admit(principal.user_id)

    async def generate() -> TranscriptDraft:
        item, content = await transcript_minutes.fetch_transcripts(
            context, settings, payload.transcript_id
        )
        notes = await transcript_minutes.draft_minutes(context, item, content)
        return TranscriptDraft(transcript_id=item.id, notes=notes)

    task = asyncio.create_task(generate())
    try:
        while not task.done():
            await asyncio.wait({task}, timeout=0.5)
            if await request.is_disconnected():
                raise HTTPException(status_code=499, detail="Draft request cancelled.")
        return await task
    except TimeoutError as exc:
        raise transcript_minutes.TranscriptUnavailable(
            "Drafting timed out. No minutes were published. Try again later."
        ) from exc
    finally:
        if not task.done():
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task
        transcript_minutes.limiter.running.discard(principal.user_id)
