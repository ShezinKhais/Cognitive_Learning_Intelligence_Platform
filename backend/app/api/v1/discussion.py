from uuid import UUID

from fastapi import APIRouter, Depends, Request
from sqlalchemy import delete

from app.api.deps import AppSettings, CurrentUser, DbSession, require_consents, require_roles
from app.core.audit import audit_action
from app.models.discussion_note import DiscussionNote
from app.schemas.discussion import DiscussionNoteOut, DiscussionOut, DiscussionWrite
from app.schemas.identity import ConsentType, Role
from app.services import discussion

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
