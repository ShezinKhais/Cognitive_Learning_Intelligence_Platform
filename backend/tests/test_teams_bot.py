"""The Teams bot endpoint: who may post to it, and what it does with a
meeting's start and end.

Owner: General CS, Phase 4. Tokens are signed here with a generated key in
place of Bot Framework's, so everything but the key download is exercised.
"""

from __future__ import annotations

import time
from uuid import uuid4

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa

from app.api.v1.teams import get_bot_authenticator
from app.auth.store import LECTURER_ID
from app.core.errors import AuthenticationError, ServiceUnavailableError
from app.schemas.identity import Role
from app.schemas.meetings import TeamsActivity
from app.services import teams_bot
from app.services.meeting_directory import InMemoryMeetingDirectory, meetings

from .session_support import add_course, add_question, create_session, sign_in_as

APP_ID = "00000000-0000-0000-0000-00000000b07"
SERVICE_URL = "https://smba.trafficmanager.net/emea/"
KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)


def _token(**overrides) -> str:  # noqa: ANN003
    now = int(time.time())
    claims = {
        "iss": teams_bot.BOT_FRAMEWORK_ISSUER,
        "aud": APP_ID,
        "exp": now + 600,
        "nbf": now - 10,
        "serviceUrl": SERVICE_URL,
        **overrides,
    }
    return jwt.encode(claims, KEY, algorithm="RS256", headers={"kid": "test"})


async def _public_key(token: str):  # noqa: ANN202
    return KEY.public_key()


def _authenticator() -> teams_bot.BotAuthenticator:
    return teams_bot.BotAuthenticator(APP_ID, key_for=_public_key)


def _activity(name: str, meeting_id: str | None, kind: str = "event") -> dict:
    return {
        "type": kind,
        "name": name,
        "serviceUrl": SERVICE_URL,
        "channelId": "msteams",
        "channelData": {"meeting": {"id": meeting_id}} if meeting_id else {},
    }


START = "application/vnd.microsoft.meetingStart"
END = "application/vnd.microsoft.meetingEnd"


# -- the token ------------------------------------------------------------------


async def test_a_token_from_bot_framework_for_this_bot_is_accepted() -> None:
    await _authenticator().verify(f"Bearer {_token()}", SERVICE_URL)


@pytest.mark.parametrize(
    "claims",
    [
        {"aud": "another-bot"},
        {"iss": "https://sts.windows.net/someone/"},
        {"exp": int(time.time()) - teams_bot.CLOCK_SKEW_SECONDS - 60},
        {"serviceUrl": "https://attacker.example/"},
    ],
    ids=["another bot", "another issuer", "expired", "another channel"],
)
async def test_a_token_meant_for_something_else_is_refused(claims: dict) -> None:
    with pytest.raises(AuthenticationError):
        await _authenticator().verify(f"Bearer {_token(**claims)}", SERVICE_URL)


async def test_a_token_signed_with_another_key_is_refused() -> None:
    other = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    forged = jwt.encode(
        {"iss": teams_bot.BOT_FRAMEWORK_ISSUER, "aud": APP_ID, "exp": int(time.time()) + 600},
        other,
        algorithm="RS256",
    )
    with pytest.raises(AuthenticationError):
        await _authenticator().verify(f"Bearer {forged}", SERVICE_URL)


async def test_no_token_is_refused() -> None:
    with pytest.raises(AuthenticationError):
        await _authenticator().verify(None, SERVICE_URL)


async def test_unreachable_keys_are_an_outage_not_a_bad_token() -> None:
    """Teams retries a 503. A 401 would drop the meeting's start for good."""

    async def unreachable(token: str):  # noqa: ANN202
        raise jwt.PyJWKClientConnectionError("no route to host")

    with pytest.raises(ServiceUnavailableError):
        await teams_bot.BotAuthenticator(APP_ID, key_for=unreachable).verify(
            f"Bearer {_token()}", SERVICE_URL
        )


# -- what an activity means -------------------------------------------------------


def test_a_meeting_start_and_end_become_meeting_events() -> None:
    started = teams_bot.meeting_event(TeamsActivity.model_validate(_activity(START, "m1")))
    ended = teams_bot.meeting_event(TeamsActivity.model_validate(_activity(END, "m1")))

    assert (started.kind, started.meeting_id) == ("started", "m1")
    assert (ended.kind, ended.meeting_id) == ("ended", "m1")


@pytest.mark.parametrize(
    "activity",
    [
        _activity(START, "m1", kind="message"),
        _activity("application/vnd.microsoft.meetingParticipantJoin", "m1"),
        _activity(START, None),
        _activity(START, "m" * 257),
    ],
    ids=["a message", "a participant joining", "no meeting id", "a meeting id too long"],
)
def test_anything_else_is_not_a_meeting_event(activity: dict) -> None:
    assert teams_bot.meeting_event(TeamsActivity.model_validate(activity)) is None


# -- the endpoint -----------------------------------------------------------------


@pytest.fixture
def bot(app, monkeypatch: pytest.MonkeyPatch):  # noqa: ANN001, ANN201
    monkeypatch.setattr(meetings, "directory", InMemoryMeetingDirectory())
    app.dependency_overrides[get_bot_authenticator] = _authenticator
    return lambda client, activity, token=None: client.post(  # noqa: E731
        "/api/v1/teams/messages",
        json=activity,
        headers={"Authorization": f"Bearer {token or _token()}"},
    )


async def _linked(db, app) -> tuple[str, str]:  # noqa: ANN001
    client, factory, created = db
    course = await add_course(factory, created)
    await add_question(db, course, LECTURER_ID)
    sign_in_as(app, LECTURER_ID, Role.LECTURER)
    session = create_session(client, course)
    meeting = f"meeting-{uuid4().hex}"
    client.put(f"/api/v1/meetings/{meeting}", json={"session_id": session["id"]})
    return session["id"], meeting


async def test_teams_starting_and_ending_the_meeting_runs_the_class(db, app, bot) -> None:
    client, _, _ = db
    session_id, meeting = await _linked(db, app)

    assert bot(client, _activity(START, meeting)).status_code == 200
    started = client.post(f"/api/v1/sessions/{session_id}/pause")
    assert started.status_code == 200, "the meeting's start should have started the class"

    assert bot(client, _activity(END, meeting)).status_code == 200
    ended = client.post(f"/api/v1/sessions/{session_id}/resume")
    assert ended.json()["error"]["detail"]["current_status"] == "ended"


async def test_a_start_teams_cannot_apply_is_acknowledged_not_retried(db, app, bot) -> None:
    """Nothing staged: the start is refused. Answering Teams with an error
    would only make it redeliver an event that will be refused again."""
    client, factory, created = db
    course = await add_course(factory, created)
    sign_in_as(app, LECTURER_ID, Role.LECTURER)
    session = create_session(client, course)
    meeting = f"meeting-{uuid4().hex}"
    client.put(f"/api/v1/meetings/{meeting}", json={"session_id": session["id"]})

    assert bot(client, _activity(START, meeting)).status_code == 200
    # Still prepared, so the meeting's end cancels it.
    assert bot(client, _activity(END, meeting)).status_code == 200
    after = client.post(f"/api/v1/sessions/{session['id']}/start")
    assert after.json()["error"]["detail"]["current_status"] == "cancelled"


async def test_an_unlinked_meeting_is_acknowledged_and_left_alone(db, bot) -> None:
    client, _, _ = db

    assert bot(client, _activity(START, f"meeting-{uuid4().hex}")).status_code == 200


async def test_the_endpoint_refuses_a_bad_token(db, bot) -> None:
    client, _, _ = db

    refused = bot(client, _activity(START, "m1"), token=_token(aud="another-bot"))
    assert refused.status_code == 401


async def test_without_teams_credentials_the_bot_is_off(db) -> None:
    client, _, _ = db

    off = client.post("/api/v1/teams/messages", json=_activity(START, "m1"))
    assert off.status_code == 503
