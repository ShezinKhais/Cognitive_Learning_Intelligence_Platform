"""Graph notifications wake a durable, bounded, lecturer-private drafting queue.

Webhook payload URLs are never fetched. We re-list only the verified linked
meeting, filtering recurring occurrences through transcript_minutes. One server
worker runs the two non-overlapping scheduler jobs, separately from live classes.
"""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
from datetime import UTC, datetime, timedelta
from urllib.parse import quote
from uuid import UUID

import httpx
from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert

from app.core.config import get_settings
from app.core.database import get_session_factory
from app.core.errors import ClipError, ConflictError
from app.models.session import Session
from app.models.teams_meeting_link import TeamsMeetingLink
from app.models.transcript_automation import TranscriptAutomation, TranscriptDraftJob
from app.schemas.discussion import DraftMinute
from app.services import transcript_minutes as transcripts

WAITING = "Waiting for the meeting to end and Teams to generate its transcript."
SETUP_ERROR = "Graph access failed. Check tenant permissions, organizer policy and callback setup."


def now():
    return datetime.now(UTC)


def client_state(row, settings):
    return hmac.new(
        settings.clip_secret_key.encode(),
        f"clip-transcript:{row.session_id}:{row.meeting_id}".encode(),
        hashlib.sha256,
    ).hexdigest()


def eligible(row, session, meeting_id):
    return (
        row.enabled
        and meeting_id == row.meeting_id
        and (session.ended_at is None or session.ended_at > now() - timedelta(hours=48))
    )


async def subscription_request(row, settings, method, *, subscription_id=None):
    """Fixed Graph endpoint; no transcript content or resource data in callbacks."""
    async with httpx.AsyncClient(timeout=10, follow_redirects=False) as client:
        headers = {"Authorization": f"Bearer {await transcripts.graph_token(client, settings)}"}
        url = f"{transcripts.GRAPH}/subscriptions"
        if subscription_id:
            url += f"/{quote(subscription_id, safe='')}"
        if method == "DELETE":
            response = await client.delete(url, headers=headers)
            if response.status_code not in {204, 404, 410}:
                raise transcripts.TranscriptUnavailable(SETUP_ERROR)
            return None
        expiry = (now() + timedelta(days=2)).isoformat()
        body = {"expirationDateTime": expiry}
        if method == "POST":
            body.update(
                changeType="created",
                resource=(
                    f"communications/onlineMeetings/{quote(row.resource_id, safe='')}/transcripts"
                ),
                notificationUrl=settings.teams_transcript_callback_url,
                lifecycleNotificationUrl=settings.teams_transcript_callback_url,
                includeResourceData=False,
                clientState=client_state(row, settings),
            )
        async with asyncio.timeout(20):
            data = json.loads(
                await transcripts.bounded(client, method, url, headers=headers, json=body)
            )
        identity = str(UUID(data["id"]))
        expires = transcripts.timestamp(data["expirationDateTime"])
        if expires <= now():
            raise ValueError("Expired subscription")
        return identity, expires


async def maintain_subscriptions():
    settings = get_settings()
    if not settings.teams_transcripts_automatic_enabled:
        return
    factory = get_session_factory()
    async with factory() as db:
        rows = list(
            await db.scalars(
                select(TranscriptAutomation).order_by(TranscriptAutomation.next_scan_at)
            )
        )
    # Modest linked-class workload, not a tenant-wide subscription or fetch.
    for row in rows:
        async with factory() as db:
            session = await db.get(Session, row.session_id)
            meeting_id = await db.scalar(
                select(TeamsMeetingLink.meeting_id).where(
                    TeamsMeetingLink.session_id == row.session_id
                )
            )
        if not session:
            continue
        try:
            if not eligible(row, session, meeting_id):
                if row.subscription_id:
                    await subscription_request(
                        row, settings, "DELETE", subscription_id=row.subscription_id
                    )
                async with factory() as db:
                    current = await db.get(TranscriptAutomation, row.session_id)
                    if current:
                        current.enabled = False
                        current.subscription_id = None
                        current.expires_at = None
                        current.message = (
                            "Automatic fetching stopped. Existing drafts remain private "
                            "until expiry or discard."
                        )
                        await db.commit()
                continue
            if (
                not row.subscription_id
                or not row.expires_at
                or row.expires_at < now() + timedelta(hours=6)
            ):
                try:
                    identity, expiry = await subscription_request(
                        row,
                        settings,
                        "PATCH" if row.subscription_id else "POST",
                        subscription_id=row.subscription_id,
                    )
                except ConflictError:  # Graph no longer has the stored subscription.
                    identity, expiry = await subscription_request(row, settings, "POST")
                async with factory() as db:
                    current = await db.get(TranscriptAutomation, row.session_id)
                    if current and current.enabled and current.meeting_id == row.meeting_id:
                        current.subscription_id, current.expires_at = identity, expiry
                        current.message = WAITING
                        await db.commit()
                    else:
                        # Disabled/deleted while Graph was creating the subscription.
                        await subscription_request(
                            row, settings, "DELETE", subscription_id=identity
                        )
        except (ClipError, httpx.HTTPError, TimeoutError, ValueError, KeyError, TypeError):
            async with factory() as db:
                await db.execute(
                    update(TranscriptAutomation)
                    .where(TranscriptAutomation.session_id == row.session_id)
                    .values(message=SETUP_ERROR)
                )
                await db.commit()


async def accept_notifications(db, values, settings):
    """Authenticate hints with subscription ID, tenant and constant-time state.

    Resource identifiers are deliberately ignored: the worker re-lists the
    stored meeting and can never use a notification as an arbitrary URL.
    """
    for value in values:
        if not isinstance(value, dict):
            continue
        identity, state = value.get("subscriptionId"), value.get("clientState")
        if (
            not isinstance(identity, str)
            or len(identity) > 36
            or not isinstance(state, str)
            or len(state) > 128
        ):
            continue
        if str(value.get("tenantId", "")).lower() != settings.tenant_id.lower():
            continue
        row = await db.scalar(
            select(TranscriptAutomation)
            .where(TranscriptAutomation.subscription_id == identity)
            .with_for_update()
        )
        if (
            row is None
            or not row.enabled
            or not hmac.compare_digest(state, client_state(row, settings))
        ):
            continue
        row.next_scan_at = now()
        lifecycle = value.get("lifecycleEvent")
        if lifecycle == "subscriptionRemoved":
            row.subscription_id = None
            row.expires_at = None
        elif lifecycle == "reauthorizationRequired":
            row.expires_at = now()  # PATCH renews and reauthorizes the subscription.
    await db.commit()


async def scan_transcripts():
    settings = get_settings()
    factory = get_session_factory()
    async with factory() as db:
        # Clear evidence even if a worker crashed; tombstones prevent re-import.
        await db.execute(
            update(TranscriptDraftJob)
            .where(TranscriptDraftJob.expires_at <= now())
            .values(drafts=None, status="expired")
        )
        await db.commit()
        if not settings.teams_transcripts_automatic_enabled:
            return
        rows = list(
            await db.scalars(
                select(TranscriptAutomation)
                .join(Session)
                .where(
                    Session.status == "ended",
                    TranscriptAutomation.enabled.is_(True),
                    TranscriptAutomation.next_scan_at <= now(),
                )
                .order_by(TranscriptAutomation.next_scan_at)
                .limit(10)
            )
        )
        await db.commit()
    for row in rows:
        try:
            async with factory() as db:
                session = await db.get(Session, row.session_id)
                link = await db.scalar(
                    select(TeamsMeetingLink.meeting_id).where(
                        TeamsMeetingLink.session_id == row.session_id
                    )
                )
                if not session or not eligible(row, session, link) or session.status != "ended":
                    continue
                context = await transcripts.context_for(db, session, settings)
            items = await transcripts.fetch_transcripts(context, settings)
            async with factory() as db:
                current = await db.get(TranscriptAutomation, row.session_id)
                if current and current.enabled:
                    # Cap the durable queue for an abusive or unusually long meeting.
                    for item in items[:24]:
                        await db.execute(
                            insert(TranscriptDraftJob)
                            .values(
                                session_id=row.session_id,
                                transcript_id=item.id,
                                status="pending",
                                attempts=0,
                                next_attempt_at=now(),
                                expires_at=min(
                                    now() + timedelta(days=7),
                                    context.ended_at + timedelta(days=settings.data_retention_days),
                                ),
                            )
                            .on_conflict_do_nothing()
                        )
                    current.next_scan_at = now() + timedelta(minutes=5)
                    current.message = (
                        "Transcripts queued for private draft review."
                        if items
                        else "Waiting for Teams processing; checking again automatically."
                    )
                    await db.commit()
        except (ClipError, httpx.HTTPError, TimeoutError, ValueError, TypeError):
            async with factory() as db:
                await db.execute(
                    update(TranscriptAutomation)
                    .where(TranscriptAutomation.session_id == row.session_id)
                    .values(message=SETUP_ERROR, next_scan_at=now() + timedelta(minutes=5))
                )
                await db.commit()


async def prepare_drafts():
    """Claim one durable job; a ten-minute lease recovers after process restart."""
    settings = get_settings()
    if not settings.teams_transcripts_automatic_enabled:
        return
    factory = get_session_factory()
    async with factory() as db:
        await db.execute(
            update(TranscriptDraftJob)
            .where(
                TranscriptDraftJob.status == "processing",
                TranscriptDraftJob.attempts >= 6,
                TranscriptDraftJob.next_attempt_at <= now(),
            )
            .values(status="failed")
        )
        job = await db.scalar(
            select(TranscriptDraftJob)
            .join(TranscriptAutomation)
            .where(
                TranscriptAutomation.enabled.is_(True),
                TranscriptDraftJob.status.in_(["pending", "processing"]),
                TranscriptDraftJob.attempts < 6,
                TranscriptDraftJob.next_attempt_at <= now(),
                TranscriptDraftJob.expires_at > now(),
            )
            .order_by(TranscriptDraftJob.next_attempt_at)
            .with_for_update(skip_locked=True, of=TranscriptDraftJob)
            .limit(1)
        )
        if job is None:
            await db.commit()
            return
        job.status = "processing"
        job.attempts += 1
        job.next_attempt_at = now() + timedelta(minutes=10)
        sid, tid = job.session_id, job.transcript_id
        await db.commit()
    try:
        async with factory() as db:
            row = await db.get(TranscriptAutomation, sid)
            session = await db.get(Session, sid)
            link = await db.scalar(
                select(TeamsMeetingLink.meeting_id).where(TeamsMeetingLink.session_id == sid)
            )
            if not row or not session or not eligible(row, session, link):
                return
            context = await transcripts.context_for(db, session, settings)
        item, content = await transcripts.fetch_transcripts(context, settings, tid)
        notes = await transcripts.draft_minutes(context, item, content)
        async with factory() as db:
            job = await db.get(TranscriptDraftJob, (sid, tid), with_for_update=True)
            row = await db.get(TranscriptAutomation, sid)
            link = await db.scalar(
                select(TeamsMeetingLink.meeting_id).where(TeamsMeetingLink.session_id == sid)
            )
            # Discard/disable/expiry during Graph/model calls must not resurrect text.
            if (
                job
                and row
                and row.enabled
                and row.meeting_id == link
                and job.status == "processing"
                and job.expires_at > now()
            ):
                job.drafts = [note.model_dump(mode="json") for note in notes]
                job.status = "ready"
                await db.commit()
    except (ClipError, httpx.HTTPError, TimeoutError, ValueError, KeyError, TypeError):
        async with factory() as db:
            job = await db.get(TranscriptDraftJob, (sid, tid), with_for_update=True)
            if job and job.status == "processing":
                job.status = "failed" if job.attempts >= 6 else "pending"
                job.next_attempt_at = now() + timedelta(minutes=min(30, 2**job.attempts))
                await db.commit()


def private_notes(job):
    return [DraftMinute.model_validate(note) for note in (job.drafts or [])]
