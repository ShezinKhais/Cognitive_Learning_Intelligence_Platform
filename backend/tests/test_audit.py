"""Tests for the Cyber 1 audit decorator."""

from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi import Request

from app.core.audit import audit_action
from app.models.audit_log import AuditLog


class FakeSession:
    def __init__(self) -> None:
        self.added: list[AuditLog] = []
        self.flushed = False

    def add(self, record: AuditLog) -> None:
        self.added.append(record)

    async def flush(self) -> None:
        self.flushed = True


def make_request(ip_address: str = "203.0.113.10") -> Request:
    return Request(
        {
            "type": "http",
            "method": "POST",
            "path": "/test",
            "headers": [],
            "query_string": b"",
            "scheme": "http",
            "server": ("testserver", 80),
            "client": (ip_address, 12345),
        }
    )


@pytest.mark.asyncio
async def test_audit_action_persists_successful_production_change() -> None:
    user_id = uuid4()
    principal = SimpleNamespace(user_id=user_id)
    settings = SimpleNamespace(is_production=True)
    db = FakeSession()
    request = make_request()

    @audit_action("CONSENT_UPDATED")
    async def endpoint(*, principal, settings, db, request):
        return "success"

    result = await endpoint(
        principal=principal,
        settings=settings,
        db=db,
        request=request,
    )

    assert result == "success"
    assert db.flushed is True
    assert len(db.added) == 1

    record = db.added[0]

    assert record.user_id == user_id
    assert record.action_type == "CONSENT_UPDATED"
    assert record.ip_address == "203.0.113.10"


@pytest.mark.asyncio
async def test_audit_action_does_not_persist_development_change() -> None:
    principal = SimpleNamespace(user_id=uuid4())
    settings = SimpleNamespace(is_production=False)
    db = FakeSession()
    request = make_request()

    @audit_action("CONSENT_UPDATED")
    async def endpoint(*, principal, settings, db, request):
        return "success"

    result = await endpoint(
        principal=principal,
        settings=settings,
        db=db,
        request=request,
    )

    assert result == "success"
    assert db.added == []
    assert db.flushed is False


@pytest.mark.asyncio
async def test_audit_action_does_not_log_failed_change() -> None:
    principal = SimpleNamespace(user_id=uuid4())
    settings = SimpleNamespace(is_production=True)
    db = FakeSession()
    request = make_request()

    @audit_action("CONSENT_UPDATED")
    async def endpoint(*, principal, settings, db, request):
        raise ValueError("change failed")

    with pytest.raises(ValueError, match="change failed"):
        await endpoint(
            principal=principal,
            settings=settings,
            db=db,
            request=request,
        )

    assert db.added == []
    assert db.flushed is False


class CommittingSession(FakeSession):
    def __init__(self) -> None:
        super().__init__()
        self.committed_after_flush = False

    async def commit(self) -> None:
        self.committed_after_flush = self.flushed


@pytest.mark.asyncio
async def test_audit_action_can_commit_the_change_with_its_record() -> None:
    db = CommittingSession()

    @audit_action("CONSENT_UPDATED", commit=True)
    async def endpoint(*, principal, settings, db, request):
        return "success"

    await endpoint(
        principal=SimpleNamespace(user_id=uuid4()),
        settings=SimpleNamespace(is_production=True),
        db=db,
        request=make_request(),
    )

    assert len(db.added) == 1
    assert db.committed_after_flush is True


@pytest.mark.asyncio
async def test_audit_action_does_not_commit_a_failed_change() -> None:
    db = CommittingSession()

    @audit_action("CONSENT_UPDATED", commit=True)
    async def endpoint(*, principal, settings, db, request):
        raise ValueError("change failed")

    with pytest.raises(ValueError, match="change failed"):
        await endpoint(
            principal=SimpleNamespace(user_id=uuid4()),
            settings=SimpleNamespace(is_production=True),
            db=db,
            request=make_request(),
        )

    assert db.added == [] and db.committed_after_flush is False
