"""Only a meeting's organiser, or an admin, may link a session to it."""

from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import httpx
import pytest

from app.core.config import Settings
from app.core.errors import ConflictError, PermissionError_, ServiceUnavailableError
from app.schemas.identity import Role
from app.services import meeting_organiser
from app.services.meeting_organiser import organiser_of, require_organiser

OID = "11111111-2222-3333-4444-555555555555"


def live() -> Settings:
    return Settings(
        client_id="bot",
        client_secret="test-secret",
        tenant_id="tenant",
        teams_notifications_enabled=True,
        teams_app_base_url="https://clip.example",
        teams_app_id="00000000-0000-0000-0000-000000000051",
    )


def principal(role: Role = Role.LECTURER):
    return SimpleNamespace(user_id=uuid4(), is_=lambda wanted: wanted == role)


def db_with(reference):
    db = AsyncMock()
    db.scalar.return_value = reference
    return db


def mapped(monkeypatch, teams_user):
    class Repo:
        def __init__(self, _db):
            pass

        async def teams_user_for(self, **_):
            return teams_user

    monkeypatch.setattr(meeting_organiser, "TeamsUserMappingRepository", Repo)


REFERENCE = SimpleNamespace(service_url="https://smba.trafficmanager.net/emea/", tenant_id="tenant")


def details(oid):
    async def fetch(*_):
        return {"organizer": {"aadObjectId": oid}}

    return fetch


def test_organiser_is_read_from_the_meeting_details() -> None:
    assert organiser_of({"organizer": {"aadObjectId": OID.upper()}}) == OID
    assert organiser_of({"organizer": {}}) is None
    assert organiser_of([]) is None


async def test_the_organiser_may_link(monkeypatch) -> None:
    mapped(monkeypatch, OID)
    await require_organiser(
        db_with(REFERENCE), principal(), "m", live(), fetch=details(OID.upper())
    )


async def test_another_lecturer_in_the_meeting_is_refused(monkeypatch, caplog) -> None:
    mapped(monkeypatch, OID)
    with pytest.raises(PermissionError_, match="organiser"):
        await require_organiser(
            db_with(REFERENCE), principal(), "m", live(), fetch=details(str(uuid4()))
        )
    assert "MEETING_LINK_NOT_ORGANISER" in caplog.text


async def test_details_without_an_organiser_are_refused(monkeypatch) -> None:
    mapped(monkeypatch, OID)
    with pytest.raises(PermissionError_):
        await require_organiser(db_with(REFERENCE), principal(), "m", live(), fetch=details(None))


async def test_an_unlinked_teams_account_is_told_to_open_clip_in_teams(monkeypatch) -> None:
    mapped(monkeypatch, None)
    with pytest.raises(PermissionError_, match="Open C.L.I.P in Teams"):
        await require_organiser(db_with(REFERENCE), principal(), "m", live(), fetch=details(OID))


async def test_a_meeting_the_bot_is_not_in_cannot_be_checked(monkeypatch) -> None:
    mapped(monkeypatch, OID)
    with pytest.raises(ConflictError, match="Add it from Apps"):
        await require_organiser(db_with(None), principal(), "m", live(), fetch=details(OID))
    other = SimpleNamespace(service_url=REFERENCE.service_url, tenant_id="elsewhere")
    with pytest.raises(ConflictError):
        await require_organiser(db_with(other), principal(), "m", live(), fetch=details(OID))


async def test_teams_failing_to_answer_refuses_rather_than_allows(monkeypatch) -> None:
    mapped(monkeypatch, OID)

    async def broken(*_):
        raise httpx.ConnectTimeout("slow")

    with pytest.raises(ServiceUnavailableError):
        await require_organiser(db_with(REFERENCE), principal(), "m", live(), fetch=broken)


async def test_admins_and_development_skip_the_check() -> None:
    async def never(*_):
        raise AssertionError("must not ask Teams")

    db = AsyncMock()
    await require_organiser(db, principal(Role.ADMIN), "m", live(), fetch=never)
    await require_organiser(db, principal(), "m", Settings(), fetch=never)
    db.scalar.assert_not_awaited()
