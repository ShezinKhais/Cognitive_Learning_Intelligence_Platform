import json
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import httpx
import pytest
from sqlalchemy import delete, func, select

from app.auth.store import LECTURER_ID, STUDENT_ID
from app.core.config import get_settings
from app.core.errors import PermissionError_
from app.models.discussion_note import DiscussionNote
from app.models.session import Session
from app.models.teams_meeting_link import TeamsMeetingLink
from app.models.teams_meeting_reference import TeamsMeetingReference
from app.models.transcript_automation import TranscriptAutomation, TranscriptDraftJob
from app.schemas.discussion import DraftMinute, TranscriptItem
from app.schemas.identity import Role
from app.services import transcript_automation as service
from app.services import transcript_minutes

from .session_support import add_course, create_session, sign_in_as


@pytest.fixture
async def automation(db, app, monkeypatch):
    client, factory, created = db
    settings = get_settings()
    for key, value in {
        "teams_transcripts_enabled": True,
        "teams_transcripts_automatic_enabled": True,
        "teams_transcript_callback_url": "https://clip.example/api/v1/teams/transcript-notifications",
        "client_id": str(uuid4()),
        "tenant_id": str(uuid4()),
        "client_secret": "test-only",
    }.items():
        monkeypatch.setattr(settings, key, value)
    monkeypatch.setattr(service, "get_session_factory", lambda: factory)
    # Avoid the startup scheduler racing a test that explicitly runs each stage.
    monkeypatch.setattr("app.main.maintain_subscriptions", noop)
    monkeypatch.setattr("app.main.scan_transcripts", noop)
    monkeypatch.setattr("app.main.prepare_drafts", noop)
    sign_in_as(app, LECTURER_ID, Role.LECTURER)
    course = await add_course(factory, created)
    sid = UUID(create_session(client, course)["id"])
    meeting = f"bot-{uuid4()}"
    async with factory() as sql:
        session = await sql.get(Session, sid)
        session.status = "ended"
        session.start_time = datetime.now(UTC) - timedelta(hours=1)
        session.ended_at = datetime.now(UTC)
        sql.add(
            TeamsMeetingReference(
                meeting_id=meeting,
                service_url="https://smba.trafficmanager.net/emea/",
                conversation_id="chat",
                tenant_id=settings.tenant_id,
            )
        )
        sql.add(TeamsMeetingLink(meeting_id=meeting, session_id=sid))
        await sql.commit()

    async def resource(*_):
        return str(uuid4()), "verified-graph-meeting"

    monkeypatch.setattr(transcript_minutes, "meeting_resource", resource)
    yield client, factory, sid, settings
    async with factory() as sql:
        ref = await sql.get(TeamsMeetingReference, meeting)
        if ref:
            await sql.delete(ref)
            await sql.commit()


async def noop():
    pass


def path(sid):
    return f"/api/v1/sessions/{sid}/discussion/automatic-transcripts"


def enable(client, sid):
    result = client.put(path(sid), json={"enabled": True, "participant_notice_confirmed": True})
    assert result.status_code == 200, result.text
    assert result.json()["enabled"]


async def seed_subscription(factory, sid):
    async with factory() as sql:
        row = await sql.get(TranscriptAutomation, sid)
        row.subscription_id = str(uuid4())
        row.expires_at = service.now() + timedelta(days=1)
        row.next_scan_at = service.now() + timedelta(hours=1)
        await sql.commit()
        return row


async def seed_job(factory, sid, **overrides):
    async with factory() as sql:
        job = TranscriptDraftJob(
            session_id=sid,
            transcript_id="transcript",
            status="pending",
            attempts=0,
            next_attempt_at=service.now(),
            expires_at=service.now() + timedelta(days=1),
            **overrides,
        )
        sql.add(job)
        await sql.commit()


async def test_opt_in_requires_notice_owner_and_student_cannot_see_private_drafts(automation, app):
    client, factory, sid, settings = automation
    assert client.put(path(sid), json={"enabled": True}).status_code == 422
    enable(client, sid)
    row = await seed_subscription(factory, sid)
    body = client.get(path(sid)).text
    assert row.subscription_id not in body
    assert service.client_state(row, settings) not in body
    sign_in_as(app, STUDENT_ID, Role.STUDENT)
    assert client.get(path(sid)).status_code == 403
    assert client.put(path(sid), json={"enabled": False}).status_code == 403
    sign_in_as(app, uuid4(), Role.LECTURER)
    assert client.get(path(sid)).status_code in {403, 404}


async def test_webhook_validation_and_authenticated_duplicate_hints(automation):
    client, factory, sid, settings = automation
    enable(client, sid)
    row = await seed_subscription(factory, sid)
    url = "/api/v1/teams/transcript-notifications"
    response = client.post(url + "?validationToken=test%20challenge")
    assert response.status_code == 200 and response.text == "test challenge"
    assert response.headers["content-type"].startswith("text/plain")
    valid = {
        "subscriptionId": row.subscription_id,
        "tenantId": settings.tenant_id,
        "clientState": service.client_state(row, settings),
        "resource": "https://evil.example/ignored",
    }
    assert (
        client.post(
            url,
            json={
                "value": [{**valid, "clientState": "forged"}, {**valid, "tenantId": str(uuid4())}]
            },
        ).status_code
        == 202
    )
    async with factory() as sql:
        assert (await sql.get(TranscriptAutomation, sid)).next_scan_at == row.next_scan_at
    assert client.post(url, json={"value": [valid, valid]}).status_code == 202
    async with factory() as sql:
        assert (await sql.get(TranscriptAutomation, sid)).next_scan_at < row.next_scan_at
    assert client.post(url, content=b"x" * 64001).status_code == 413
    assert client.post(url, json={"value": [valid] * 101}).status_code == 400
    assert client.post(url, content="not json").status_code == 400
    assert (
        client.post(
            url, json={"value": [{**valid, "lifecycleEvent": "subscriptionRemoved"}]}
        ).status_code
        == 202
    )
    async with factory() as sql:
        assert (await sql.get(TranscriptAutomation, sid)).subscription_id is None


async def test_scan_deduplicates_and_recovered_job_produces_private_drafts(automation, monkeypatch):
    client, factory, sid, _ = automation
    enable(client, sid)

    async def fetch(context, settings, transcript_id=None):
        item = TranscriptItem(id="transcript", created_at=context.starts_at)
        return [item] if transcript_id is None else (item, "temporary VTT")

    async def draft(context, item, content):
        return [
            DraftMinute(
                note_id=uuid4(),
                occurred_at=item.created_at,
                text="Normalization reduces duplicate values.",
                source_excerpt="Normalization reduces duplicate values.",
                source_offset_seconds=0,
            )
        ]

    monkeypatch.setattr(transcript_minutes, "fetch_transcripts", fetch)
    monkeypatch.setattr(transcript_minutes, "draft_minutes", draft)
    await service.scan_transcripts()
    async with factory() as sql:
        (await sql.get(TranscriptAutomation, sid)).next_scan_at = service.now()
        job = await sql.get(TranscriptDraftJob, (sid, "transcript"))
        job.status = "processing"  # Simulate restart after claim but before completion.
        job.next_attempt_at = service.now() - timedelta(seconds=1)
        await sql.commit()
    await service.scan_transcripts()
    await service.prepare_drafts()
    async with factory() as sql:
        assert (
            await sql.scalar(
                select(func.count())
                .select_from(TranscriptDraftJob)
                .where(TranscriptDraftJob.session_id == sid)
            )
            == 1
        )
        assert (
            await sql.scalar(
                select(func.count())
                .select_from(DiscussionNote)
                .where(DiscussionNote.session_id == sid)
            )
            == 0
        )
        job = await sql.get(TranscriptDraftJob, (sid, "transcript"))
        assert job.status == "ready" and len(job.drafts) == 1
    status = client.get(path(sid)).json()
    assert status["drafts"][0]["notes"][0]["text"] == "Normalization reduces duplicate values."
    assert client.delete(path(sid) + "/drafts/transcript").status_code == 200
    async with factory() as sql:
        (await sql.get(TranscriptAutomation, sid)).next_scan_at = service.now()
        await sql.commit()
    await service.scan_transcripts()
    await service.prepare_drafts()
    assert client.get(path(sid)).json()["drafts"] == []


@pytest.mark.parametrize("action", ["disable", "discard", "unlink"])
async def test_changes_during_drafting_cannot_restore_text(automation, monkeypatch, action):
    client, factory, sid, _ = automation
    enable(client, sid)
    await seed_job(factory, sid)

    async def fetch(context, *_):
        return TranscriptItem(id="transcript", created_at=context.starts_at), "temporary VTT"

    async def draft(*_):
        if action == "disable":
            assert client.put(path(sid), json={"enabled": False}).status_code == 200
        elif action == "discard":
            assert client.delete(path(sid) + "/drafts/transcript").status_code == 200
        else:
            async with factory() as sql:
                await sql.execute(
                    delete(TeamsMeetingLink).where(TeamsMeetingLink.session_id == sid)
                )
                await sql.commit()
        return [
            DraftMinute(
                note_id=uuid4(),
                occurred_at=service.now(),
                text="Private point",
                source_excerpt="Private point",
                source_offset_seconds=0,
            )
        ]

    monkeypatch.setattr(transcript_minutes, "fetch_transcripts", fetch)
    monkeypatch.setattr(transcript_minutes, "draft_minutes", draft)
    await service.prepare_drafts()
    async with factory() as sql:
        job = await sql.get(TranscriptDraftJob, (sid, "transcript"))
        assert job.status != "ready" and job.drafts is None


async def test_failed_jobs_retry_and_expired_evidence_is_erased(automation, monkeypatch):
    client, factory, sid, settings = automation
    enable(client, sid)
    await seed_job(factory, sid)

    async def refused(*_):
        raise PermissionError_("private upstream detail")

    monkeypatch.setattr(transcript_minutes, "fetch_transcripts", refused)
    await service.prepare_drafts()
    async with factory() as sql:
        job = await sql.get(TranscriptDraftJob, (sid, "transcript"))
        assert job.status == "pending" and job.attempts == 1
        assert job.next_attempt_at > service.now()
        job.status = "ready"
        job.drafts = [{"private": "evidence"}]
        job.expires_at = service.now() - timedelta(seconds=1)
        await sql.commit()
    monkeypatch.setattr(settings, "teams_transcripts_automatic_enabled", False)
    await service.scan_transcripts()
    async with factory() as sql:
        job = await sql.get(TranscriptDraftJob, (sid, "transcript"))
        assert job.status == "expired" and job.drafts is None


async def test_graph_subscription_scope_renew_and_delete_use_fixed_host(automation, monkeypatch):
    client, factory, sid, settings = automation
    enable(client, sid)
    calls = []
    identity = str(uuid4())

    def respond(request):
        calls.append(request)
        if request.url.host == "login.microsoftonline.com":
            return httpx.Response(200, json={"access_token": "token"})
        assert request.url.host == "graph.microsoft.com"
        if request.method == "DELETE":
            return httpx.Response(204)
        body = json.loads(request.content)
        if request.method == "POST":
            assert (
                body["resource"]
                == "communications/onlineMeetings/verified-graph-meeting/transcripts"
            )
            assert body["includeResourceData"] is False
            assert body["lifecycleNotificationUrl"] == settings.teams_transcript_callback_url
        return httpx.Response(
            201,
            json={
                "id": identity,
                "expirationDateTime": (service.now() + timedelta(days=2)).isoformat(),
            },
        )

    original = httpx.AsyncClient
    monkeypatch.setattr(
        service.httpx,
        "AsyncClient",
        lambda **kwargs: original(transport=httpx.MockTransport(respond), **kwargs),
    )
    await service.maintain_subscriptions()
    async with factory() as sql:
        row = await sql.get(TranscriptAutomation, sid)
        assert row.subscription_id == identity
        row.expires_at = service.now()
        await sql.commit()
    await service.maintain_subscriptions()
    assert any(r.method == "PATCH" for r in calls)
    assert client.put(path(sid), json={"enabled": False}).status_code == 200
    await service.maintain_subscriptions()
    assert any(r.method == "DELETE" for r in calls)


async def test_session_deletion_cascades_private_queue_and_subscription(automation):
    client, factory, sid, _ = automation
    enable(client, sid)
    await seed_job(factory, sid)
    async with factory() as sql:
        await sql.execute(delete(Session).where(Session.session_id == sid))
        await sql.commit()
        assert await sql.get(TranscriptAutomation, sid) is None
        assert await sql.get(TranscriptDraftJob, (sid, "transcript")) is None
