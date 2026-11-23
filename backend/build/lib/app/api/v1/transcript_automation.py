"""Lecturer controls and a bounded, authenticated-by-clientState Graph webhook."""

import asyncio
import json
from datetime import timedelta
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import PlainTextResponse, Response
from sqlalchemy import select, update

from app.api.deps import AppSettings, CurrentUser, DbSession, require_consents, require_roles
from app.api.v1.discussion import writable_session
from app.core.audit import audit_action
from app.core.errors import ConflictError, ValidationError
from app.models.teams_meeting_link import TeamsMeetingLink
from app.models.teams_meeting_reference import TeamsMeetingReference
from app.models.transcript_automation import TranscriptAutomation, TranscriptDraftJob
from app.schemas.discussion import (
    AutomaticTranscriptOut,
    AutomaticTranscriptWrite,
    PrivateTranscriptDraft,
)
from app.schemas.identity import ConsentType, Role
from app.services import discussion, transcript_minutes
from app.services import transcript_automation as service

router = APIRouter(
    prefix="/sessions/{session_id}/discussion/automatic-transcripts",
    tags=["discussion"],
    dependencies=[
        Depends(require_roles(Role.LECTURER, Role.ADMIN)),
        Depends(require_consents(ConsentType.TERMS)),
    ],
)
webhook_router = APIRouter(tags=["teams"])


@webhook_router.post("/teams/transcript-notifications", status_code=202)
async def graph_notifications(
    request: Request,
    db: DbSession,
    settings: AppSettings,
    validationToken: str | None = Query(default=None, max_length=1024),
) -> Response:
    if not settings.teams_transcripts_automatic_enabled:
        raise HTTPException(404)
    if validationToken is not None:
        return PlainTextResponse(validationToken, headers={"Cache-Control": "no-store"})
    data = bytearray()
    try:
        async with asyncio.timeout(3):
            async for chunk in request.stream():
                data.extend(chunk)
                if len(data) > 64_000:
                    raise HTTPException(413, "Notification payload too large.")
        payload = json.loads(data)
        values = payload.get("value")
        if not isinstance(values, list) or len(values) > 100:
            raise ValueError("Invalid batch")
    except (ValueError, TypeError, AttributeError, TimeoutError) as exc:
        raise HTTPException(400, "Invalid notification batch.") from exc
    await service.accept_notifications(db, values, settings)
    return Response(status_code=202)


@router.get("", response_model=AutomaticTranscriptOut)
async def read_automation(
    session_id: UUID, principal: CurrentUser, db: DbSession, settings: AppSettings
):
    await discussion.accessible_session(
        db, session_id, principal.user_id, principal.role, write=True
    )
    row = await db.get(TranscriptAutomation, session_id)
    jobs = (
        list(
            await db.scalars(
                select(TranscriptDraftJob)
                .where(
                    TranscriptDraftJob.session_id == session_id,
                    TranscriptDraftJob.expires_at > service.now(),
                )
                .order_by(TranscriptDraftJob.transcript_id)
            )
        )
        if row
        else []
    )
    return AutomaticTranscriptOut(
        configured=settings.teams_transcripts_automatic_enabled,
        enabled=bool(row and row.enabled),
        subscribed=bool(
            row and row.subscription_id and row.expires_at and row.expires_at > service.now()
        ),
        message=row.message
        if row
        else "Enable automatic fetching before starting Teams transcription.",
        drafts=[
            PrivateTranscriptDraft(
                transcript_id=job.transcript_id,
                notes=service.private_notes(job),
                expires_at=job.expires_at,
            )
            for job in jobs
            if job.status == "ready"
        ],
        pending=sum(job.status in {"pending", "processing"} for job in jobs),
        failed=sum(job.status == "failed" for job in jobs),
    )


@router.put("", response_model=AutomaticTranscriptOut, dependencies=[Depends(writable_session)])
@audit_action("DISCUSSION_AUTOMATIC_TRANSCRIPTS_CHANGED")
async def configure_automation(
    session_id: UUID,
    payload: AutomaticTranscriptWrite,
    principal: CurrentUser,
    db: DbSession,
    settings: AppSettings,
    request: Request,
):
    session = await discussion.accessible_session(
        db, session_id, principal.user_id, principal.role, write=True
    )
    row = await db.get(TranscriptAutomation, session_id, with_for_update=True)
    if not payload.enabled:
        if row:
            row.enabled = False
            row.message = "Automatic fetching disabled. Unpublished drafts discarded."
            await db.execute(
                update(TranscriptDraftJob)
                .where(TranscriptDraftJob.session_id == session_id)
                .values(status="discarded", drafts=None)
            )
            await db.commit()
        return await read_automation(session_id, principal, db, settings)
    if not settings.teams_transcripts_automatic_enabled:
        raise ConflictError("Automatic transcript fetching is disabled by the administrator.")
    if not payload.participant_notice_confirmed:
        raise ValidationError(
            "Confirm participants were informed and institutional transcription "
            "and consent requirements were met."
        )
    if session.ended_at and session.ended_at < service.now() - timedelta(hours=48):
        raise ConflictError(
            "Automatic fetching is available until 48 hours after class. Use manual import."
        )
    meeting_id = await db.scalar(
        select(TeamsMeetingLink.meeting_id).where(TeamsMeetingLink.session_id == session_id)
    )
    reference = await db.get(TeamsMeetingReference, meeting_id) if meeting_id else None
    if not reference or reference.tenant_id.lower() != settings.tenant_id.lower():
        raise ConflictError(
            "Link this class to its Teams meeting and add C.L.I.P to the meeting first."
        )
    if row and row.meeting_id != meeting_id:
        raise ConflictError("This class was relinked. Use manual import for the new meeting.")
    context = transcript_minutes.MeetingContext(
        session_id,
        meeting_id,
        reference.service_url,
        session.start_time,
        session.ended_at or service.now(),
    )
    await db.close()  # No row lock/connection during trusted Bot Framework lookup.
    organizer, resource = await transcript_minutes.meeting_resource(context, settings)
    # Recheck access and link after the network lookup, before committing consent.
    await discussion.accessible_session(
        db, session_id, principal.user_id, principal.role, write=True
    )
    if (
        await db.scalar(
            select(TeamsMeetingLink.meeting_id).where(TeamsMeetingLink.session_id == session_id)
        )
        != meeting_id
    ):
        raise ConflictError("Meeting link changed. Try again.")
    row = await db.get(TranscriptAutomation, session_id, with_for_update=True)
    if row is None:
        row = TranscriptAutomation(
            session_id=session_id,
            meeting_id=meeting_id,
            organizer_id=organizer,
            resource_id=resource,
            enabled=True,
            next_scan_at=service.now(),
            message="Waiting for Graph subscription.",
        )
        db.add(row)
    else:
        row.enabled = True
        row.next_scan_at = service.now()
    await db.commit()
    return await read_automation(session_id, principal, db, settings)


@router.delete("/drafts/{transcript_id}")
@audit_action("DISCUSSION_AUTOMATIC_DRAFT_DISCARDED")
async def discard_draft(
    session_id: UUID,
    transcript_id: str,
    principal: CurrentUser,
    db: DbSession,
    settings: AppSettings,
    request: Request,
):
    await discussion.accessible_session(
        db, session_id, principal.user_id, principal.role, write=True
    )
    await db.execute(
        update(TranscriptDraftJob)
        .where(
            TranscriptDraftJob.session_id == session_id,
            TranscriptDraftJob.transcript_id == transcript_id,
        )
        .values(status="discarded", drafts=None)
    )
    await db.commit()
    return {"discarded": True}
