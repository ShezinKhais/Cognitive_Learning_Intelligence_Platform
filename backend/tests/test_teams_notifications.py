"""Outbound requests use a fake connector; no tenant or credentials required."""

import asyncio
import json
import time
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import httpx
import pytest

from app.core.config import Settings
from app.schemas.meetings import TeamsActivity
from app.services import teams_notifications as module
from app.services.teams_notifications import (
    CheckpointNotice,
    TeamsNotifications,
    checkpoint_card,
    connector_url,
    panel_url,
    remember_reference,
)


def configured() -> Settings:
    return Settings(
        client_id="bot",
        client_secret="test-secret",
        tenant_id="tenant",
        teams_notifications_enabled=True,
        teams_app_base_url="https://clip.example",
        teams_app_id="00000000-0000-0000-0000-000000000051",
    )


@pytest.mark.parametrize(
    "url",
    [
        "http://smba.trafficmanager.net/teams",
        "https://evil.example/",
        "https://smba.trafficmanager.net.evil.example/",
        "https://smba.trafficmanager.net@evil.example/",
        "https://smba.trafficmanager.net:8443/",
        "https://smba.trafficmanager.net/../evil",
        "https://smba.trafficmanager.net/%2e%2e/",
        "https://smba.trafficmanager.net/?redirect=x",
    ],
)
def test_untrusted_connector_destinations_are_refused(url) -> None:
    with pytest.raises(ValueError):
        connector_url(url)


def test_card_contains_only_session_context_and_panel_link() -> None:
    session = uuid4()
    target = panel_url("https://clip.example", session)
    card = checkpoint_card(target, "CS101", "Class")
    assert card["actions"][0]["url"] == f"https://clip.example/teams/meeting?sessionId={session}"
    assert card["type"] == "AdaptiveCard"
    assert "CS101 — Class" in json.dumps(card, ensure_ascii=False)


async def test_reference_is_optional_and_rejects_arbitrary_destinations() -> None:
    db = AsyncMock()
    activity = TeamsActivity(
        type="event",
        serviceUrl="https://evil.example/",
        channelData={"meeting": {"id": "meeting"}, "tenant": {"id": "tenant"}},
        conversation={"id": "chat"},
    )
    await remember_reference(db, activity, configured())
    db.execute.assert_not_awaited()
    activity.service_url = "https://smba.trafficmanager.net/emea/"
    await remember_reference(db, activity, configured())
    db.execute.assert_awaited_once()
    db.commit.assert_awaited_once()


async def test_token_is_cached_and_secrets_do_not_enter_connector_payloads() -> None:
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(200, json={"access_token": "bot-token", "expires_in": 3600})

    sender = TeamsNotifications()
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        assert await sender.access_token(client, configured()) == "bot-token"
        assert await sender.access_token(client, configured()) == "bot-token"
    assert len(calls) == 1
    assert calls[0].url.host == "login.microsoftonline.com"
    assert b"scope=https%3A%2F%2Fapi.botframework.com%2F.default" in calls[0].content


async def test_send_targets_only_mapped_students_and_batches_fifty(monkeypatch, caplog) -> None:
    session_id = uuid4()
    link = SimpleNamespace(
        bot_service_url="https://smba.trafficmanager.net/emea/",
        bot_conversation_id="chat/id",
        bot_tenant_id="tenant",
        meeting_id="meeting/id",
    )
    session = SimpleNamespace(title="Class", course_id=uuid4())

    class Db:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            pass

        async def execute(self, statement):
            return SimpleNamespace(first=lambda: (link, session, SimpleNamespace(code="CS101")))

        async def scalars(self, statement):
            return SimpleNamespace(all=lambda: [f"aad-{i}" for i in range(51)])

    monkeypatch.setattr(module, "get_session_factory", lambda: Db)
    requests = []

    def handler(request):
        requests.append(request)
        if request.url.host == "login.microsoftonline.com":
            return httpx.Response(200, json={"access_token": "bot-token", "expires_in": 3600})
        assert request.headers["Authorization"] == "Bearer bot-token"
        assert "test-secret" not in request.content.decode()
        if request.method == "GET":
            members = [{"id": f"29:student-{i}", "aadObjectId": f"aad-{i}"} for i in range(51)]
            members += [
                {"id": "29:lecturer", "aadObjectId": "other"},
                {"id": "aad-0", "aadObjectId": "aad-0"},
            ]
            if request.url.params.get("continuationToken"):
                return httpx.Response(200, json={"members": members[25:]})
            return httpx.Response(200, json={"members": members[:25], "continuationToken": "next"})
        return httpx.Response(
            207 if request.url.path.endswith("/notification") else 202, json={"id": "message"}
        )

    client_type = httpx.AsyncClient
    monkeypatch.setattr(
        module.httpx,
        "AsyncClient",
        lambda **kwargs: client_type(transport=httpx.MockTransport(handler), **kwargs),
    )
    await TeamsNotifications().send(
        CheckpointNotice(session_id, time.time() + 30, uuid4()), configured()
    )
    posts = [
        r for r in requests if r.method == "POST" and r.url.host != "login.microsoftonline.com"
    ]
    assert len(posts) == 3
    assert json.loads(posts[0].content)["attachments"][0]["content"]["type"] == "AdaptiveCard"
    batches = [json.loads(r.content)["value"]["recipients"] for r in posts[1:]]
    assert [len(batch) for batch in batches] == [50, 1]
    assert set(sum(batches, [])) == {f"29:student-{i}" for i in range(51)}
    assert "%2F" in str(posts[0].url)
    assert "partially delivered" in caplog.text


async def test_queue_is_bounded_and_expired_notices_do_not_send(monkeypatch) -> None:
    monkeypatch.setattr(module, "get_settings", configured)
    sender = TeamsNotifications()
    sender.send = AsyncMock()
    await sender._run(CheckpointNotice(uuid4(), time.time() - 1, uuid4()))
    sender.send.assert_not_awaited()
    gate = asyncio.Event()

    async def blocked(*args):
        await gate.wait()

    monkeypatch.setattr(sender, "_run", blocked)
    for _ in range(101):
        sender.enqueue(uuid4(), uuid4(), time.time() + 30)
    assert len(sender.tasks) == 100
    await sender.shutdown()
    assert not sender.tasks


async def test_failure_is_sanitized_and_does_not_escape(caplog, monkeypatch) -> None:
    monkeypatch.setattr(module, "get_settings", configured)
    sender = TeamsNotifications()
    sender.send = AsyncMock(side_effect=RuntimeError("test-secret bot-token"))
    await sender._run(CheckpointNotice(uuid4(), time.time() + 30, uuid4()))
    assert "failed" in caplog.text
    assert "test-secret" not in caplog.text
    assert "bot-token" not in caplog.text


async def test_rejected_token_is_invalidated_without_retrying_message(monkeypatch) -> None:
    monkeypatch.setattr(module, "get_settings", configured)
    sender = TeamsNotifications()
    sender.token_until = time.monotonic() + 3600
    request = httpx.Request("POST", "https://smba.trafficmanager.net/emea/")
    response = httpx.Response(401, request=request)
    sender.send = AsyncMock(
        side_effect=httpx.HTTPStatusError("refused", request=request, response=response)
    )
    await sender._run(CheckpointNotice(uuid4(), time.time() + 30, uuid4()))
    assert sender.token_until == 0
    sender.send.assert_awaited_once()


def test_enabled_notifications_require_credentials_and_frontend_configuration() -> None:
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        Settings(teams_notifications_enabled=True, client_id="", client_secret="", tenant_id="")
    settings = configured().model_dump()
    settings["teams_app_base_url"] = "http://clip.example"
    with pytest.raises(ValidationError):
        Settings(**settings)


def test_endpoint_saves_no_reference_before_authentication(app, client, monkeypatch) -> None:
    from app.api.v1 import teams
    from app.core.errors import AuthenticationError, PermissionError_

    auth = SimpleNamespace(
        verify=AsyncMock(side_effect=AuthenticationError("refused")),
        authorize=lambda activity: None,
    )
    reference = AsyncMock()
    monkeypatch.setattr(teams, "remember_reference", reference)
    monkeypatch.setattr(teams.teams_bot, "handle_activity", AsyncMock())
    app.dependency_overrides[teams.get_bot_authenticator] = lambda: auth
    activity = {
        "type": "event",
        "name": "application/vnd.microsoft.meetingStart",
        "serviceUrl": "https://smba.trafficmanager.net/emea/",
        "channelId": "msteams",
        "channelData": {"tenant": {"id": "tenant"}, "meeting": {"id": "meeting"}},
        "conversation": {"id": "chat"},
    }
    try:
        assert client.post("/api/v1/teams/messages", json=activity).status_code == 401
        reference.assert_not_awaited()
        auth.verify = AsyncMock()

        def wrong_tenant(activity):
            raise PermissionError_("refused")

        auth.authorize = wrong_tenant
        assert client.post("/api/v1/teams/messages", json=activity).status_code == 403
        reference.assert_not_awaited()
        auth.authorize = lambda activity: None
        assert client.post("/api/v1/teams/messages", json=activity).status_code == 200
        reference.assert_awaited_once()
    finally:
        app.dependency_overrides.pop(teams.get_bot_authenticator, None)


@pytest.mark.usefixtures("fake_session_repository")
async def test_delivery_enqueues_after_commit_for_manual_and_scheduled_path() -> None:
    from .classroom_support import FakeDb, FakeRepository, deliver_next, make_room, make_row

    room, _ = make_room()
    row = make_row()
    notices = []

    def notify(session_id, question_id, closes_at):
        assert FakeRepository.deliveries  # Claim precedes notification.
        notices.append((session_id, question_id, closes_at))

    room.checkpoint_notifier = notify
    question = await deliver_next(room, row)
    assert len(notices) == 1
    assert notices[0][:2] == (row.session_id, question.question_id)
    from app.core.errors import ConflictError

    with pytest.raises(ConflictError):
        await room.deliver(FakeDb(), row)
    assert len(notices) == 1
    await room.shutdown()


@pytest.mark.usefixtures("fake_session_repository")
async def test_notifier_failure_does_not_break_question_or_close_timer() -> None:
    from .classroom_support import deliver_next, make_room, make_row

    room, _ = make_room()
    row = make_row()

    def broken(*args):
        raise RuntimeError("unavailable")

    room.checkpoint_notifier = broken
    await deliver_next(room, row)
    assert room._live[row.session_id].open.closer is not None
    await room.shutdown()


async def test_persisted_reference_and_course_recipient_filter_against_database(
    db, app, monkeypatch
) -> None:
    from datetime import UTC, date, datetime, timedelta

    from app.auth.store import LECTURER_ID
    from app.models.delivered_question import DeliveredQuestion
    from app.models.session import Session
    from app.models.student import Student
    from app.models.teams_meeting_link import TeamsMeetingLink
    from app.models.teams_user_mapping import TeamsUserMapping
    from app.models.user import User
    from app.schemas.identity import Role

    from .session_support import add_course, add_question, create_session, sign_in_as

    client, factory, created = db
    course = await add_course(factory, created)
    other_course = await add_course(factory, created)
    question = await add_question(db, course, LECTURER_ID)
    sign_in_as(app, LECTURER_ID, Role.LECTURER)
    session_id = module.UUID(create_session(client, course)["id"])
    meeting_id = f"meeting-{uuid4()}"
    now = datetime.now(UTC)
    async with factory() as seed:
        session = await seed.get(Session, session_id)
        session.status = "active"
        seed.add(
            DeliveredQuestion(
                session_id=session_id,
                question_id=question,
                delivered_at=now,
                closes_at=now + timedelta(seconds=30),
                window_seconds=30,
            )
        )
        seed.add(TeamsMeetingLink(meeting_id=meeting_id, session_id=session_id))
        for name, role, active, course_id in [
            ("eligible", "student", True, course.id),
            ("inactive", "student", False, course.id),
            ("staff", "lecturer", True, course.id),
            ("other-course", "student", True, other_course.id),
        ]:
            user_id = uuid4()
            created["user"].append(user_id)
            seed.add(
                User(
                    user_id=user_id,
                    name=name,
                    email=f"{user_id}@example.test",
                    role=role,
                    active=active,
                )
            )
            await seed.flush()
            seed.add(
                Student(
                    user_id=user_id,
                    course_id=course_id,
                    consent_status="granted",
                    enrolled_at=date.today(),
                )
            )
            seed.add(
                TeamsUserMapping(user_id=user_id, tenant_id="tenant", teams_user_id=f"aad-{name}")
            )
        await seed.commit()
    activity = TeamsActivity(
        type="event",
        serviceUrl="https://smba.trafficmanager.net/emea/",
        channelData={"meeting": {"id": meeting_id}, "tenant": {"id": "tenant"}},
        conversation={"id": "chat"},
    )
    async with factory() as session:
        await remember_reference(session, activity, configured())
    async with factory() as session:
        saved = await session.get(TeamsMeetingLink, meeting_id)
        assert saved.bot_conversation_id == "chat"
        assert saved.bot_service_url == "https://smba.trafficmanager.net/emea/"
    monkeypatch.setattr(module, "get_session_factory", lambda: factory)
    sent = []

    def handler(request):
        if request.url.host == "login.microsoftonline.com":
            return httpx.Response(200, json={"access_token": "token", "expires_in": 3600})
        if request.method == "GET":
            return httpx.Response(
                200,
                json={
                    "members": [
                        {"id": f"29:{name}", "aadObjectId": f"aad-{name}"}
                        for name in ("eligible", "inactive", "staff", "other-course", "unknown")
                    ]
                },
            )
        sent.append(json.loads(request.content))
        return httpx.Response(202, json={})

    client_type = httpx.AsyncClient
    monkeypatch.setattr(
        module.httpx,
        "AsyncClient",
        lambda **kwargs: client_type(transport=httpx.MockTransport(handler), **kwargs),
    )
    sender = TeamsNotifications()
    notice = CheckpointNotice(session_id, time.time() + 30, question)
    await sender.send(notice, configured())
    assert len(sent) == 2
    assert sent[1]["value"]["recipients"] == ["29:eligible"]
    async with factory() as session:
        from sqlalchemy import update

        await session.execute(
            update(DeliveredQuestion)
            .where(DeliveredQuestion.session_id == session_id)
            .values(closed_at=now)
        )
        await session.commit()
    await sender.send(notice, configured())
    assert len(sent) == 2  # A queued notification cannot revive a closed checkpoint.
