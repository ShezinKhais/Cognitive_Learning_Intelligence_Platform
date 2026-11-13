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
    AlertNotice,
    CheckpointNotice,
    TeamsNotifications,
    checkpoint_card,
    checkpoint_dialog_for,
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
    # A dialog over the meeting, through task/fetch, never a link that opens
    # the app's tab and takes the student out of the meeting view.
    action = card["actions"][0]
    assert action["type"] == "Action.Submit"
    assert action["data"]["msteams"] == {"type": "task/fetch"}
    assert action["data"]["target"] == f"https://clip.example/teams/meeting?sessionId={session}"
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


async def test_a_developer_portal_bot_takes_its_token_from_botframework_com() -> None:
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(200, json={"access_token": "bot-token", "expires_in": 3600})

    settings = configured().model_copy(update={"teams_bot_token_tenant": "botframework.com"})
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        await TeamsNotifications().access_token(client, settings)
    assert calls[0].url.path == "/botframework.com/oauth2/v2.0/token"
    assert calls[0].url.path != "/tenant/oauth2/v2.0/token"


async def test_send_targets_only_mapped_students_and_batches_fifty(monkeypatch, caplog) -> None:
    session_id = uuid4()
    link = SimpleNamespace(meeting_id="meeting/id")
    reference = SimpleNamespace(
        service_url="https://smba.trafficmanager.net/emea/",
        conversation_id="chat/id",
        tenant_id="tenant",
    )
    session = SimpleNamespace(title="Class", course_id=uuid4())

    class Db:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            pass

        async def execute(self, statement):
            return SimpleNamespace(
                first=lambda: (link, session, SimpleNamespace(code="CS101"), reference)
            )

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
    # Only the pop-up: no chat message beside it.
    assert len(posts) == 2
    assert all(r.url.path.endswith("/notification") for r in posts)
    batches = [json.loads(r.content)["value"]["recipients"] for r in posts]
    assert [len(batch) for batch in batches] == [50, 1]
    assert set(sum(batches, [])) == {f"29:student-{i}" for i in range(51)}
    surface = json.loads(posts[0].content)["value"]["surfaces"][0]
    assert surface["content"]["value"]["url"].endswith("&view=dialog")
    assert (surface["content"]["value"]["width"], surface["content"]["value"]["height"]) == (
        "480",
        "520",
    )
    assert "%2F" in str(posts[0].url)
    assert "partially delivered" in caplog.text


async def test_an_alert_pops_up_for_the_lecturer_alone(monkeypatch) -> None:
    session_id = uuid4()
    link = SimpleNamespace(meeting_id="meeting-1")
    reference = SimpleNamespace(
        service_url="https://smba.trafficmanager.net/emea/",
        conversation_id="chat-1",
        tenant_id="tenant",
    )
    mapping = SimpleNamespace(teams_user_id="aad-lecturer")

    class Db:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            pass

        async def execute(self, statement):
            return SimpleNamespace(first=lambda: (link, reference, mapping))

    monkeypatch.setattr(module, "get_session_factory", lambda: Db)
    requests = []

    def handler(request):
        requests.append(request)
        if request.url.host == "login.microsoftonline.com":
            return httpx.Response(200, json={"access_token": "bot-token", "expires_in": 3600})
        if request.method == "GET":
            return httpx.Response(
                200,
                json={
                    "members": [
                        {"id": "29:lecturer", "aadObjectId": "aad-lecturer"},
                        {"id": "29:student", "aadObjectId": "aad-student"},
                    ]
                },
            )
        return httpx.Response(202, json={})

    client_type = httpx.AsyncClient
    monkeypatch.setattr(
        module.httpx,
        "AsyncClient",
        lambda **kwargs: client_type(transport=httpx.MockTransport(handler), **kwargs),
    )
    await TeamsNotifications().send_alert(AlertNotice(session_id, time.time() + 30), configured())
    posts = [
        r for r in requests if r.method == "POST" and r.url.host != "login.microsoftonline.com"
    ]
    # No message in the meeting chat, which every participant reads.
    assert [r.url.path.rsplit("/", 1)[-1] for r in posts] == ["notification"]
    body = json.loads(posts[0].content)
    assert body["value"]["recipients"] == ["29:lecturer"]
    popup = body["value"]["surfaces"][0]["content"]["value"]
    # The update page, which lists the alert and lets the lecturer mute updates.
    assert popup["url"] == f"https://clip.example/lecturer/teams/update?sessionId={session_id}"


async def test_an_unlinked_lecturer_gets_no_alert_pop_up(monkeypatch) -> None:
    class Db:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            pass

        async def execute(self, statement):
            return SimpleNamespace(first=lambda: None)

    monkeypatch.setattr(module, "get_session_factory", lambda: Db)
    monkeypatch.setattr(
        module.httpx, "AsyncClient", lambda **kwargs: pytest.fail("nothing should be sent")
    )
    await TeamsNotifications().send_alert(AlertNotice(uuid4(), time.time() + 30), configured())


async def test_a_burst_of_alerts_is_one_pop_up_a_minute(monkeypatch) -> None:
    monkeypatch.setattr(module, "get_settings", configured)
    sender = TeamsNotifications()
    sent = []

    async def record(notice):
        sent.append(notice)

    monkeypatch.setattr(sender, "_run", record)
    one, other = uuid4(), uuid4()
    for _ in range(3):
        sender.enqueue_alert(one)
    sender.enqueue_alert(other)
    await asyncio.gather(*sender.tasks)
    assert sorted(str(n.session_id) for n in sent) == sorted([str(one), str(other)])
    sender.alerted_at[one] -= module.ALERT_COOLDOWN_SECONDS
    sender.enqueue_alert(one)
    await asyncio.gather(*sender.tasks)
    assert len(sent) == 3


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


def test_any_verified_meeting_activity_saves_the_reference(app, client, monkeypatch) -> None:
    """A lecturer who links the session after the meeting started has missed
    its start event; the bot's next message from the meeting still counts."""
    from app.api.v1 import teams

    auth = SimpleNamespace(verify=AsyncMock(), authorize=lambda activity: None)
    reference = AsyncMock()
    monkeypatch.setattr(teams, "remember_reference", reference)
    monkeypatch.setattr(teams.teams_bot, "handle_activity", AsyncMock())
    app.dependency_overrides[teams.get_bot_authenticator] = lambda: auth
    message = {
        "type": "message",
        "text": "hello",
        "serviceUrl": "https://smba.trafficmanager.net/emea/",
        "channelId": "msteams",
        "channelData": {"tenant": {"id": "tenant"}, "meeting": {"id": "meeting"}},
        "conversation": {"id": "chat"},
    }
    try:
        assert client.post("/api/v1/teams/messages", json=message).status_code == 200
        reference.assert_awaited_once()
    finally:
        app.dependency_overrides.pop(teams.get_bot_authenticator, None)


def test_a_teams_app_id_that_is_not_a_uuid_is_named_in_the_error() -> None:
    from pydantic import ValidationError

    settings = configured().model_dump()
    settings["teams_app_id"] = "not-a-uuid"
    with pytest.raises(ValidationError, match="TEAMS_APP_ID"):
        Settings(**settings)


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


async def test_a_raised_alert_reaches_the_teams_notifier_and_survives_its_failure() -> None:
    from .classroom_support import make_room

    room, _ = make_room()
    session_id = uuid4()
    told = []
    room.alert_notifier = lambda sid, message: told.append((sid, message))
    await room._raise_alert(session_id, {"alert_id": "a", "message": "Much of the class is lost."})
    assert told == [(session_id, "Much of the class is lost.")]

    def broken(*args):
        raise RuntimeError("unavailable")

    room.alert_notifier = broken
    await room._raise_alert(session_id, {"alert_id": "b"})
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
    from app.models.teams_meeting_reference import TeamsMeetingReference
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
    # The bot hears from the meeting before the lecturer links it, as when the
    # meeting has already started, and the link is made afterwards.
    async with factory() as session:
        await remember_reference(session, activity, configured())
    async with factory() as seed:
        seed.add(TeamsMeetingLink(meeting_id=meeting_id, session_id=session_id))
        await seed.commit()
    async with factory() as session:
        saved = await session.get(TeamsMeetingReference, meeting_id)
        assert saved.conversation_id == "chat"
        assert saved.service_url == "https://smba.trafficmanager.net/emea/"
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


# -- the lecturer updates, welcomes and the end of class ---------------------------


async def test_lecturer_updates_are_kept_spaced_out_and_mutable(monkeypatch) -> None:
    monkeypatch.setattr(module, "get_settings", configured)
    sender = TeamsNotifications()
    sent = []

    async def record(notice):
        sent.append(notice)

    monkeypatch.setattr(sender, "_run", record)
    session_id = uuid4()
    sender.update_lecturer(session_id, "checkpoint", "Checkpoint closed: 3 of 4 students answered.")
    sender.update_lecturer(session_id, "checkpoint", "Checkpoint closed: 4 of 4 students answered.")
    # An alert is never held back by an update that is not one.
    sender.enqueue_alert(session_id, "Much of the class is struggling with recursion.")
    await asyncio.gather(*sender.tasks)

    assert [(n.title, n.delay) for n in sent] == [
        ("Checkpoint closed: 3 of 4 students answered.", module.UPDATE_DELAY_SECONDS),
        ("Much of the class is struggling with recursion.", 0),
    ]
    muted, recent = sender.recent_updates(session_id)
    assert not muted
    assert [u.kind for u in recent] == ["alert", "checkpoint", "checkpoint"]

    sender.mute(session_id, True)
    sender.alerted_at.clear()
    sender.enqueue_alert(session_id, "Room 2 has been quiet for 3 minutes.")
    await asyncio.gather(*sender.tasks)
    assert len(sent) == 2
    assert sender.recent_updates(session_id)[1][0].text == "Room 2 has been quiet for 3 minutes."

    sender.enqueue_class_ended(session_id)
    assert sender.recent_updates(session_id) == (False, [])


async def test_an_update_is_dropped_when_another_pop_up_went_out_while_it_waited(
    monkeypatch,
) -> None:
    monkeypatch.setattr(module, "get_settings", configured)
    sender = TeamsNotifications()
    sender.send_alert = AsyncMock()
    session_id = uuid4()
    held = sender._held(session_id)
    queued = time.monotonic()
    held.popped_at = queued + 1
    notice = AlertNotice(session_id, time.time() + 30, "Checkpoint closed", 0.01, queued)
    await sender._run(notice)
    sender.send_alert.assert_not_awaited()

    held.popped_at = None
    await sender._run(notice)
    sender.send_alert.assert_awaited_once()


def test_a_long_update_is_shortened_for_the_pop_up_title() -> None:
    assert len(module._title("x" * 500)) == module.MAX_TITLE


async def test_someone_rejoining_soon_after_is_not_popped_up_again(monkeypatch) -> None:
    monkeypatch.setattr(module, "get_settings", configured)
    sender = TeamsNotifications()
    sent = []

    async def record(notice):
        sent.append(notice)

    monkeypatch.setattr(sender, "_run", record)
    session_id = uuid4()
    sender.enqueue_welcome(session_id, {"aad-1": "29:one"})
    sender.enqueue_welcome(session_id, {"aad-1": "29:one", "aad-2": "29:two"})
    sender.enqueue_welcome(session_id, {"aad-2": "29:two"})
    await asyncio.gather(*sender.tasks)
    assert [n.people for n in sent] == [{"aad-1": "29:one"}, {"aad-2": "29:two"}]


def _fake_db(first, scalar=None):  # noqa: ANN001, ANN202
    class Db:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            pass

        async def execute(self, statement):
            return SimpleNamespace(first=lambda: first)

        async def scalar(self, statement):
            return scalar

    return Db


def _connector(monkeypatch, requests, members=()):  # noqa: ANN001, ANN202
    def handler(request):
        requests.append(request)
        if request.url.host == "login.microsoftonline.com":
            return httpx.Response(200, json={"access_token": "bot-token", "expires_in": 3600})
        if request.method == "GET":
            return httpx.Response(200, json={"members": list(members)})
        return httpx.Response(202, json={})

    client_type = httpx.AsyncClient
    monkeypatch.setattr(
        module.httpx,
        "AsyncClient",
        lambda **kwargs: client_type(transport=httpx.MockTransport(handler), **kwargs),
    )


async def test_the_welcome_pop_up_skips_the_lecturer(monkeypatch) -> None:
    session_id = uuid4()
    link = SimpleNamespace(meeting_id="meeting-1")
    reference = SimpleNamespace(
        service_url="https://smba.trafficmanager.net/emea/",
        conversation_id="chat-1",
        tenant_id="tenant",
    )
    session = SimpleNamespace(instructor_id=uuid4())
    monkeypatch.setattr(
        module, "get_session_factory", lambda: _fake_db((link, reference, session), "AAD-L")
    )
    requests = []
    _connector(
        monkeypatch,
        requests,
        [{"id": "29:l", "aadObjectId": "aad-l"}, {"id": "29:s", "aadObjectId": "aad-s"}],
    )
    # Everyone in the meeting chat, when the class has just started.
    await TeamsNotifications().send_welcome(
        module.WelcomeNotice(session_id, time.time() + 30), configured()
    )
    # Only those who joined, when someone joins.
    await TeamsNotifications().send_welcome(
        module.WelcomeNotice(session_id, time.time() + 30, {"aad-l": "29:l", "aad-x": "29:x"}),
        configured(),
    )
    popups = [json.loads(r.content) for r in requests if r.url.path.endswith("/notification")]
    assert [p["value"]["recipients"] for p in popups] == [["29:s"], ["29:x"]]
    url = popups[0]["value"]["surfaces"][0]["content"]["value"]["url"]
    assert url == f"https://clip.example/teams/meeting?sessionId={session_id}"


async def test_the_end_of_class_card_links_to_the_review(monkeypatch) -> None:
    session_id = uuid4()
    reference = SimpleNamespace(
        service_url="https://smba.trafficmanager.net/emea/",
        conversation_id="chat-1",
        tenant_id="tenant",
    )
    found = (reference, SimpleNamespace(title="Week 5"), SimpleNamespace(code="CS101"))
    monkeypatch.setattr(module, "get_session_factory", lambda: _fake_db(found))
    requests = []
    _connector(monkeypatch, requests)
    await TeamsNotifications().send_ended(
        module.EndedNotice(session_id, time.time() + 30), configured()
    )
    [post] = [
        r for r in requests if r.method == "POST" and r.url.host != "login.microsoftonline.com"
    ]
    card = json.loads(post.content)["attachments"][0]["content"]
    assert card["body"][1]["text"] == "CS101: Week 5"
    assert card["actions"][0]["url"] == f"https://clip.example/student/reviews/{session_id}"


def test_the_checkpoint_card_says_how_long_is_left() -> None:
    card = checkpoint_card("https://clip.example/x", "CS101", "Class", 45)
    assert "closes in about 45 seconds" in json.dumps(card)


def test_answer_now_opens_our_own_checkpoint_dialog() -> None:
    session = uuid4()
    settings = configured()
    target = panel_url(settings.teams_app_base_url, session)

    dialog = checkpoint_dialog_for({"data": {"clip": "checkpoint", "target": target}}, settings)

    value = dialog["task"]["value"]
    assert dialog["task"]["type"] == "continue"
    assert value["url"] == f"{target}&view=dialog"
    assert (value["width"], value["height"]) == (480, 520)


@pytest.mark.parametrize(
    "value",
    [
        None,
        {"data": {"clip": "something-else"}},
        {"data": {"clip": "checkpoint"}},
        {"data": {"clip": "checkpoint", "target": "https://evil.example/x?sessionId=nope"}},
    ],
)
def test_other_presses_open_no_dialog(value) -> None:
    assert checkpoint_dialog_for(value, configured()) is None


def test_a_foreign_target_still_opens_our_own_page() -> None:
    """The page is rebuilt from the session id, so a card naming another site
    cannot send the student there."""
    session = uuid4()
    settings = configured()
    dialog = checkpoint_dialog_for(
        {"data": {"clip": "checkpoint", "target": f"https://evil.example/x?sessionId={session}"}},
        settings,
    )
    assert dialog["task"]["value"]["url"].startswith(settings.teams_app_base_url)


async def test_a_refused_pop_up_falls_back_to_the_answer_now_card(monkeypatch) -> None:
    session_id = uuid4()
    link = SimpleNamespace(meeting_id="meeting-1")
    reference = SimpleNamespace(
        service_url="https://smba.trafficmanager.net/emea/",
        conversation_id="chat-1",
        tenant_id="tenant",
    )

    class Db:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            pass

        async def execute(self, statement):
            return SimpleNamespace(
                first=lambda: (
                    link,
                    SimpleNamespace(title="Class", course_id=uuid4()),
                    SimpleNamespace(code="CS101"),
                    reference,
                )
            )

        async def scalars(self, statement):
            return SimpleNamespace(all=lambda: ["aad-1"])

    async def members(*args, **kwargs):
        return {"29:student-1"}

    async def refused(*args, **kwargs):
        request = httpx.Request("POST", "https://smba.trafficmanager.net/emea/v1/x")
        raise httpx.HTTPStatusError(
            "no", request=request, response=httpx.Response(403, request=request)
        )

    async def token(self, client, settings):
        return "bot-token"

    posted = []

    def handler(request):
        posted.append(json.loads(request.content))
        return httpx.Response(201, json={"id": "message"})

    client_type = httpx.AsyncClient
    monkeypatch.setattr(module, "get_session_factory", lambda: Db)
    monkeypatch.setattr(module, "_meeting_members", members)
    monkeypatch.setattr(module, "_targeted_popup", refused)
    monkeypatch.setattr(TeamsNotifications, "access_token", token)
    monkeypatch.setattr(
        module.httpx,
        "AsyncClient",
        lambda **kwargs: client_type(transport=httpx.MockTransport(handler), **kwargs),
    )

    await TeamsNotifications().send(
        CheckpointNotice(session_id, time.time() + 30, uuid4()), configured()
    )

    [message] = posted
    action = message["attachments"][0]["content"]["actions"][0]
    assert action["type"] == "Action.Submit"
    assert action["data"]["target"].endswith("&view=dialog")


async def test_a_last_call_pops_the_checkpoint_up_for_those_still_to_answer(monkeypatch) -> None:
    from app.services.teams_notifications import LastCallNotice

    link = SimpleNamespace(meeting_id="meeting-1")
    reference = SimpleNamespace(
        service_url="https://smba.trafficmanager.net/emea/",
        conversation_id="chat-1",
        tenant_id="tenant",
    )

    class Db:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            pass

        async def execute(self, statement):
            return SimpleNamespace(first=lambda: (link, reference))

        async def scalars(self, statement):
            return SimpleNamespace(all=lambda: ["aad-quiet"])

    async def members(client, base, headers, conversation_id, wanted):
        assert wanted == {"aad-quiet"}
        return {"29:quiet"}

    popped = []

    async def popup(*args, **kwargs):
        popped.append((args[4], kwargs))

    async def token(self, client, settings):
        return "bot-token"

    monkeypatch.setattr(module, "get_session_factory", lambda: Db)
    monkeypatch.setattr(module, "_meeting_members", members)
    monkeypatch.setattr(module, "_targeted_popup", popup)
    monkeypatch.setattr(TeamsNotifications, "access_token", token)

    session_id = uuid4()
    await TeamsNotifications().send_last_call(
        LastCallNotice(session_id, uuid4(), frozenset({uuid4()}), time.time() + 10), configured()
    )

    [(recipients, kwargs)] = popped
    assert recipients == {"29:quiet"}
    assert kwargs["title"].startswith("Last call:")
    assert kwargs["url"].endswith("&view=dialog")
