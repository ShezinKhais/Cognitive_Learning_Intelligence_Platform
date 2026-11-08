"""Opt-in lecturer microphone chunks, isolated from student sensor telemetry."""

import asyncio
import time
from datetime import datetime
from uuid import UUID, uuid5

from fastapi import APIRouter, Depends, Request
from sqlalchemy import select

from app.api.deps import AppSettings, CurrentUser, DbSession, require_consents, require_roles
from app.core.audit import audit_action
from app.core.errors import ConflictError, RateLimitedError, ValidationError
from app.models.discussion_note import DiscussionNote
from app.schemas.discussion import (
    DiscussionNoteOut,
    LiveCaptureStart,
    LiveCaptureStatus,
    LiveChunkOut,
)
from app.schemas.identity import ConsentType, Role
from app.services import discussion, local_speech
from app.services import live_transcription as live

router = APIRouter(
    prefix="/sessions/{session_id}/live-transcription",
    tags=["live-transcription"],
    dependencies=[
        Depends(require_consents(ConsentType.TERMS)),
        Depends(require_roles(Role.LECTURER, Role.ADMIN)),
    ],
)


async def owned_session(session_id: UUID, principal: CurrentUser, db: DbSession):
    return await discussion.accessible_session(db, session_id, principal.user_id, principal.role)


@router.get("", response_model=LiveCaptureStatus)
async def status(
    session_id: UUID, principal: CurrentUser, db: DbSession, settings: AppSettings
) -> LiveCaptureStatus:
    row = await owned_session(session_id, principal, db)
    running = row.status == "active" and row.paused_at is None
    capture = live.captures.active(session_id)
    if capture and not running:
        live.captures.stop(session_id, capture.id)
        capture = None
    return LiveCaptureStatus(
        configured=local_speech.configured(settings),
        running=capture is not None,
        session_running=running,
        capture_id=capture.id if capture else None,
        language=settings.live_transcription_language,
    )


@router.post("/start", response_model=LiveCaptureStatus, dependencies=[Depends(owned_session)])
@audit_action("LIVE_TRANSCRIPTION_STARTED", commit=True)
async def start(
    session_id: UUID,
    payload: LiveCaptureStart,
    principal: CurrentUser,
    db: DbSession,
    settings: AppSettings,
    request: Request,
) -> LiveCaptureStatus:
    await live.running_session(db, session_id, principal, lock=True)
    if not payload.automatic_sharing_confirmed:
        raise ValidationError(
            "Confirm participant notice, consent requirements and automatic sharing "
            "of microphone speech with this course."
        )
    if not local_speech.configured(settings):
        raise local_speech.SpeechUnavailable(
            "Ask the administrator to install and enable the local speech model first."
        )
    item = live.captures.start(session_id, principal.user_id)
    return LiveCaptureStatus(
        configured=True,
        running=True,
        session_running=True,
        capture_id=item.id,
        language=settings.live_transcription_language,
    )


@router.post("/{capture_id}/stop", dependencies=[Depends(owned_session)])
@audit_action("LIVE_TRANSCRIPTION_STOPPED", commit=True)
async def stop(
    session_id: UUID,
    capture_id: UUID,
    principal: CurrentUser,
    db: DbSession,
    settings: AppSettings,
    request: Request,
) -> dict[str, bool]:
    live.captures.stop(session_id, capture_id)
    return {"stopped": True}


@router.post(
    "/{capture_id}/chunks/{sequence}",
    response_model=LiveChunkOut,
    dependencies=[Depends(owned_session)],
    openapi_extra={
        "requestBody": {
            "required": True,
            "content": {"audio/wav": {"schema": {"type": "string", "format": "binary"}}},
        }
    },
)
@audit_action("LIVE_TRANSCRIPTION_SEGMENT", commit=True)
async def chunk(
    session_id: UUID,
    capture_id: UUID,
    sequence: int,
    started_at: datetime,
    principal: CurrentUser,
    db: DbSession,
    settings: AppSettings,
    request: Request,
) -> LiveChunkOut:
    if sequence < 0 or sequence >= live.MAX_LIVE_SEGMENTS:
        raise ValidationError("Live capture sequence is outside its limit.")
    if started_at.tzinfo is None:
        raise ValidationError("The capture timestamp needs a timezone.")
    if not local_speech.configured(settings):
        raise local_speech.SpeechUnavailable("Live transcription is disabled or unavailable.")
    await live.running_session(db, session_id, principal)
    item = live.captures.require(session_id, capture_id, principal.user_id)
    if sequence <= item.last_sequence:
        note = await db.scalar(
            select(DiscussionNote).where(
                DiscussionNote.note_id == uuid5(capture_id, str(sequence)),
                DiscussionNote.session_id == session_id,
            )
        )
        return LiveChunkOut(
            sequence=sequence, note=DiscussionNoteOut.model_validate(note) if note else None
        )
    if item.busy or sequence != item.last_sequence + 1:
        raise ConflictError("Live chunks must arrive one at a time and in order.")
    if time.monotonic() < item.next_allowed:
        raise RateLimitedError("Live audio chunks are arriving too quickly. Capture stopped.")
    await db.close()
    item.busy = True
    item.expires = time.monotonic() + live.LEASE_SECONDS
    try:
        data = bytearray()
        async with asyncio.timeout(15):
            async for part in request.stream():
                if len(data) + len(part) > local_speech.MAX_WAV_BYTES:
                    raise ValidationError("The live audio chunk is too large.")
                data.extend(part)
        duration = local_speech.validate_wav(bytes(data))
        item.next_allowed = time.monotonic() + duration * 0.8
        text = await local_speech.speech.transcribe(bytes(data), settings)
        note = await live.publish(db, principal, item, sequence, started_at, duration, text)
        return LiveChunkOut(
            sequence=sequence, note=DiscussionNoteOut.model_validate(note) if note else None
        )
    except TimeoutError as exc:
        live.captures.stop(session_id, capture_id)
        raise local_speech.SpeechUnavailable(
            "Audio upload timed out. Capture stopped; check the connection."
        ) from exc
    except BaseException:
        live.captures.stop(session_id, capture_id)
        raise
    finally:
        item.busy = False
