"""Cyber 1, Phase 4: the Teams surfaces' permissions, identities and access.

Each section is a finding in CYBER1_PHASE4_TEAMS_SECURITY_REVIEW.md, tested
from the attacker's side: an activity from the wrong channel or tenant, a
lecturer the bot should no longer act for, a caller the meeting routes
should refuse, and a manifest asking for more than the app uses.
"""

from __future__ import annotations

import asyncio
import json
import time
from pathlib import Path
from uuid import UUID, uuid4

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from sqlalchemy import select

from app.api.deps import Principal, get_principal
from app.api.v1.teams import get_bot_authenticator
from app.auth.service import AuthenticatedUser
from app.auth.store import ADMIN_ID, LECTURER_ID, get_consent_repository
from app.core.config import get_settings
from app.core.errors import AuthenticationError, ServiceUnavailableError
from app.models.session import Session as SessionModel
from app.schemas.identity import ConsentType, Role
from app.services import session_lifecycle, teams_bot
from app.services.meeting_directory import InMemoryMeetingDirectory, meetings

from .session_support import add_course, create_session, sign_in_as
from .test_teams_bot import (
    APP_ID,
    END,
    KEY,
    SERVICE_URL,
    START,
    TENANT_ID,
    _activity,
    _linked,
    _token,
)

MANIFEST = Path(__file__).resolve().parents[2] / "teams-app" / "manifest.json"

# Bot Framework endorses its keys for many channels at once, so a real key
# vouches for a Web Chat activity as readily as for a Teams one.
EVERY_CHANNEL = frozenset({"msteams", "webchat", "directline", "emulator"})


def _endorsed_for(channels: frozenset[str] | None) -> teams_bot.BotAuthenticator:
    async def key(token: str) -> teams_bot.BotSigningKey:
        return teams_bot.BotSigningKey(KEY.public_key(), channels)

    return teams_bot.BotAuthenticator(APP_ID, TENANT_ID, key_for=key)


@pytest.fixture
def post(app, monkeypatch: pytest.MonkeyPatch):  # noqa: ANN001, ANN201
    """Posts an activity to the bot as Bot Framework would, with a key
    endorsed for every channel, so only the bot's own checks stand between."""
    monkeypatch.setattr(meetings, "directory", InMemoryMeetingDirectory())
    app.dependency_overrides[get_bot_authenticator] = lambda: _endorsed_for(EVERY_CHANNEL)
    return lambda client, activity: client.post(  # noqa: E731
        "/api/v1/teams/messages", json=activity, headers={"Authorization": f"Bearer {_token()}"}
    )


async def _status(factory, session_id: str) -> str:  # noqa: ANN001
    async with factory() as read:
        return await read.scalar(
            select(SessionModel.status).where(SessionModel.session_id == UUID(session_id))
        )


async def _running_class(db, app, post) -> tuple[str, str]:  # noqa: ANN001
    """A class its Teams meeting has started."""
    client, factory, _ = db
    session_id, meeting = await _linked(db, app)
    assert post(client, _activity(START, meeting)).status_code == 200
    assert await _status(factory, session_id) == "active"
    return session_id, meeting


# -- F1: only Teams, only this tenant, only endorsed keys ---------------------------


@pytest.mark.parametrize(
    ("channel", "refused_with"),
    # A channel the key is endorsed for gets past the token and is refused
    # as not Teams; an activity naming no channel is one no key vouches for.
    [("webchat", 403), ("directline", 403), ("emulator", 403), (None, 401)],
)
async def test_a_forged_meeting_end_from_another_channel_cannot_end_the_class(
    db, app, post, channel: str | None, refused_with: int
) -> None:
    """Every Azure bot has Web Chat on from the start, and Bot Framework signs
    what it delivers as validly as a Teams activity, with a body its client
    wrote. A meetingEnd typed into Web Chat must not end a real class."""
    client, factory, _ = db
    session_id, meeting = await _running_class(db, app, post)
    forged = {**_activity(END, meeting), "channelId": channel}

    assert post(client, forged).status_code == refused_with
    assert await _status(factory, session_id) == "active"
    client.post(f"/api/v1/sessions/{session_id}/end")


async def test_an_activity_from_another_tenant_is_refused(db, app, post) -> None:
    """Anyone can sideload a manifest carrying this bot's id into their own
    tenant, and Teams will deliver that tenant's activities here."""
    client, factory, _ = db
    session_id, meeting = await _running_class(db, app, post)
    foreign = _activity(END, meeting)
    foreign["channelData"]["tenant"] = {"id": "99999999-9999-9999-9999-999999999999"}

    assert post(client, foreign).status_code == 403
    assert await _status(factory, session_id) == "active"
    client.post(f"/api/v1/sessions/{session_id}/end")


@pytest.mark.parametrize("tenant", [None, {}, {"id": ""}, {"id": 7}, "not-an-object"])
async def test_an_activity_that_names_no_tenant_is_refused(db, app, post, tenant) -> None:  # noqa: ANN001
    client, factory, _ = db
    session_id, meeting = await _running_class(db, app, post)
    unnamed = _activity(END, meeting)
    unnamed["channelData"]["tenant"] = tenant

    assert post(client, unnamed).status_code == 403
    assert await _status(factory, session_id) == "active"
    client.post(f"/api/v1/sessions/{session_id}/end")


async def test_the_tenant_is_matched_without_regard_to_case(db, app, post) -> None:
    client, factory, _ = db
    session_id, meeting = await _running_class(db, app, post)
    shouted = _activity(END, meeting)
    shouted["channelData"]["tenant"] = {"id": TENANT_ID.upper()}

    assert post(client, shouted).status_code == 200
    assert await _status(factory, session_id) == "ended"


async def test_a_key_not_endorsed_for_teams_cannot_vouch_for_a_teams_activity() -> None:
    with pytest.raises(AuthenticationError):
        await _endorsed_for(frozenset({"webchat"})).verify(
            f"Bearer {_token()}", SERVICE_URL, "msteams"
        )


async def test_a_key_bot_framework_has_not_published_is_refused() -> None:
    with pytest.raises(AuthenticationError):
        await _endorsed_for(None).verify(f"Bearer {_token()}", SERVICE_URL, "msteams")


async def test_a_key_endorsed_for_nothing_in_particular_is_judged_on_the_rest() -> None:
    """Bot Framework's SDKs skip the check for a key with no endorsements."""
    await _endorsed_for(frozenset()).verify(f"Bearer {_token()}", SERVICE_URL, "msteams")


OTHER_KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)


def _published(*keys: tuple[object, str, list[str]]) -> dict:
    """A key set as Bot Framework publishes it: (private key, kid, endorsements)."""
    return {
        "keys": [
            {
                **json.loads(jwt.algorithms.RSAAlgorithm.to_jwk(key.public_key())),  # type: ignore[attr-defined]
                "kid": kid,
                "use": "sig",
                "endorsements": endorsements,
            }
            for key, kid, endorsements in keys
        ]
    }


def _signed(key, kid: str) -> str:  # noqa: ANN001
    claims = {"iss": teams_bot.BOT_FRAMEWORK_ISSUER, "aud": APP_ID, "exp": time.time() + 60}
    return jwt.encode(claims, key, algorithm="RS256", headers={"kid": kid})


class _KeySource:
    """Bot Framework's key endpoint: counts fetches, and can be made to fail."""

    def __init__(self, *sets: dict) -> None:
        self.sets = list(sets)
        self.fetches = 0
        self.failing = False

    def __call__(self) -> dict:
        self.fetches += 1
        if self.failing:
            raise jwt.PyJWKClientConnectionError("no route to host")
        return self.sets[min(self.fetches, len(self.sets)) - 1]


class _Clock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


def _keys(source: _KeySource, clock: _Clock) -> teams_bot.BotFrameworkKeys:
    return teams_bot.BotFrameworkKeys("https://login.example.invalid/keys", source, clock)


async def test_the_published_keys_keep_their_endorsements() -> None:
    """PyJWK drops everything but the key, so the endorsements are read from
    the raw set Bot Framework publishes."""
    source = _KeySource(
        _published((KEY, "teams-key", ["msteams", "webchat"]), (OTHER_KEY, "chat-key", ["webchat"]))
    )
    keys = _keys(source, _Clock())

    teams = await keys.key_for(_signed(KEY, "teams-key"))
    chat = await keys.key_for(_signed(OTHER_KEY, "chat-key"))

    assert teams.endorsements == {"msteams", "webchat"}
    assert chat.endorsements == {"webchat"}
    assert source.fetches == 1


async def test_a_burst_of_made_up_key_ids_causes_one_fetch() -> None:
    """A kid is read before anything is verified, so anyone can send any.
    Each unknown one used to refetch the whole set from Bot Framework."""
    source = _KeySource(_published((KEY, "teams-key", ["msteams"])))
    keys = _keys(source, _Clock())
    authenticator = teams_bot.BotAuthenticator(APP_ID, TENANT_ID, key_for=keys.key_for)

    for n in range(50):
        with pytest.raises(AuthenticationError):
            await authenticator.verify(f"Bearer {_signed(OTHER_KEY, f'made-up-{n}')}", SERVICE_URL)

    assert source.fetches == 1


async def test_concurrent_unknown_key_ids_share_one_fetch() -> None:
    source = _KeySource(_published((KEY, "teams-key", ["msteams"])))
    keys = _keys(source, _Clock())

    results = await asyncio.gather(
        *(keys.key_for(_signed(OTHER_KEY, f"made-up-{n}")) for n in range(20)),
        return_exceptions=True,
    )

    assert all(isinstance(r, jwt.InvalidTokenError) for r in results)
    assert source.fetches == 1


async def test_a_known_key_needs_no_fetch_until_the_set_is_due_a_refresh() -> None:
    source = _KeySource(_published((KEY, "teams-key", ["msteams"])))
    clock = _Clock()
    keys = _keys(source, clock)
    token = _signed(KEY, "teams-key")

    for _ in range(20):
        await keys.key_for(token)
    assert source.fetches == 1

    clock.now += teams_bot.BotFrameworkKeys.REFRESH_AFTER_SECONDS
    await keys.key_for(token)
    assert source.fetches == 2


async def test_a_key_bot_framework_rotates_in_is_found_after_the_interval() -> None:
    """Refusing unknown kids between refreshes cannot lock out a key Bot
    Framework has since published: the next refresh allowed finds it."""
    source = _KeySource(
        _published((KEY, "old-key", ["msteams"])),
        _published((KEY, "old-key", ["msteams"]), (OTHER_KEY, "new-key", ["msteams"])),
    )
    clock = _Clock()
    keys = _keys(source, clock)
    await keys.key_for(_signed(KEY, "old-key"))

    with pytest.raises(jwt.InvalidTokenError):
        await keys.key_for(_signed(OTHER_KEY, "new-key"))
    clock.now += teams_bot.BotFrameworkKeys.MIN_REFRESH_SECONDS

    assert (await keys.key_for(_signed(OTHER_KEY, "new-key"))).endorsements == {"msteams"}
    assert source.fetches == 2


async def test_a_failed_refresh_keeps_the_keys_already_held() -> None:
    source = _KeySource(_published((KEY, "teams-key", ["msteams"])))
    clock = _Clock()
    keys = _keys(source, clock)
    token = _signed(KEY, "teams-key")
    await keys.key_for(token)

    source.failing = True
    clock.now += teams_bot.BotFrameworkKeys.REFRESH_AFTER_SECONDS

    assert (await keys.key_for(token)).endorsements == {"msteams"}


async def test_keys_that_cannot_be_loaded_are_an_outage_not_a_bad_token() -> None:
    """Teams retries a 503. A 401 would drop the meeting's start for good.
    And the attempt is rate limited like any other."""
    source = _KeySource()
    source.failing = True
    keys = _keys(source, _Clock())
    authenticator = teams_bot.BotAuthenticator(APP_ID, TENANT_ID, key_for=keys.key_for)

    for _ in range(5):
        with pytest.raises(ServiceUnavailableError):
            await authenticator.verify(f"Bearer {_signed(KEY, 'teams-key')}", SERVICE_URL)
    assert source.fetches == 1


# -- F4: the bot holds no more than the lecturer it acts for ------------------------


async def test_the_bot_does_not_act_for_a_lecturer_who_withdrew_terms(db, app, post) -> None:
    """The meetings routes would refuse that lecturer; the bot, acting for
    them, refuses too, and acknowledges so Teams does not retry."""
    client, factory, _ = db
    session_id, meeting = await _linked(db, app)
    get_consent_repository(get_settings()).record(LECTURER_ID, ConsentType.TERMS, False)

    assert post(client, _activity(START, meeting)).status_code == 200
    assert await _status(factory, session_id) == "prepared"


@pytest.mark.parametrize(
    "account",
    [None, AuthenticatedUser(LECTURER_ID, "lecturer@clip.example.com", Role.STUDENT)],
    ids=["disabled", "no longer staff"],
)
async def test_the_bot_does_not_act_for_an_account_that_cannot_run_a_class(
    db, app, post, monkeypatch: pytest.MonkeyPatch, account: AuthenticatedUser | None
) -> None:
    client, factory, _ = db
    session_id, meeting = await _linked(db, app)

    async def now(*args: object) -> AuthenticatedUser | None:
        return account

    monkeypatch.setattr(session_lifecycle, "active_user", now)

    assert post(client, _activity(START, meeting)).status_code == 200
    assert await _status(factory, session_id) == "prepared"


async def test_the_bot_acts_for_an_admins_class_as_a_lecturer_only(db, app) -> None:
    """Running one session needs ownership, not the admin's wider reach."""
    client, factory, created = db
    course = await add_course(factory, created)
    sign_in_as(app, ADMIN_ID, Role.ADMIN)
    session = create_session(client, course)
    meeting = f"meeting-{uuid4().hex}"
    directory = InMemoryMeetingDirectory()
    await directory.link(meeting, UUID(session["id"]))
    original, meetings.directory = meetings.directory, directory
    try:
        async with factory() as read:
            owner = await session_lifecycle.meeting_owner(read, meeting, get_settings())
    finally:
        meetings.directory = original

    assert owner is not None
    assert (owner.user_id, owner.role) == (ADMIN_ID, Role.LECTURER)


# -- unauthorised meeting access through the mock adapter's routes ----------------


@pytest.mark.parametrize(
    ("method", "path", "body"),
    [
        ("put", "/api/v1/meetings/m1", {"session_id": str(LECTURER_ID)}),
        ("post", "/api/v1/meetings/events", {"kind": "started", "meeting_id": "m1"}),
    ],
    ids=["link", "event"],
)
async def test_the_meeting_routes_refuse_a_caller_who_is_not_signed_in(
    db, method: str, path: str, body: dict
) -> None:
    client, _, _ = db

    assert getattr(client, method)(path, json=body).status_code == 401


@pytest.mark.parametrize(
    ("method", "path", "body"),
    [
        ("put", "/api/v1/meetings/m1", {"session_id": str(LECTURER_ID)}),
        ("post", "/api/v1/meetings/events", {"kind": "started", "meeting_id": "m1"}),
    ],
    ids=["link", "event"],
)
async def test_the_meeting_routes_refuse_a_lecturer_without_terms_consent(
    db, app, method: str, path: str, body: dict
) -> None:
    client, _, _ = db
    app.dependency_overrides[get_principal] = lambda: Principal(
        user_id=LECTURER_ID, role=Role.LECTURER, email="lecturer@clip.example.com"
    )

    refused = getattr(client, method)(path, json=body)

    assert refused.status_code == 403
    assert refused.json()["error"]["code"] == "CONSENT_REQUIRED"


# -- F5: the manifest asks for what the app uses and nothing more -----------------


def test_the_manifest_asks_only_for_what_the_app_uses() -> None:
    """A permission added here is a change to what the app may do in every
    tenant that installs it, so it should fail this test until reviewed."""
    manifest = json.loads(MANIFEST.read_text("utf-8"))

    assert manifest["permissions"] == ["identity"]
    assert "devicePermissions" not in manifest
    assert [bot["scopes"] for bot in manifest["bots"]] == [["groupChat"]]
    assert {
        (p["name"], p["type"]) for p in manifest["authorization"]["permissions"]["resourceSpecific"]
    } == {
        ("OnlineMeeting.ReadBasic.Chat", "Application"),
        ("OnlineMeetingParticipant.Read.Chat", "Application"),
        ("OnlineMeetingNotification.Send.Chat", "Application"),
    }
    assert manifest["validDomains"] == ["${{BASE_DOMAIN}}"]
