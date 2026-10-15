"""A consent grant and its audit record are kept together, and a live class
acts on the grant only once both are committed.

Owner: General CS, Phase 6 (#59), from Cyber 2's review of #142.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from fastapi import Request
from sqlalchemy import delete, func, select

import app.core.audit as audit_module
from app.api.deps import Principal
from app.api.v1.identity import record_consent
from app.auth.store import STUDENT_ID
from app.models.audit_log import AuditLog
from app.models.consent import Consent
from app.realtime.classroom import classroom
from app.repositories.consent_repository import ConsentRepository
from app.schemas.identity import ConsentRequest, ConsentType, Role

MONITORING = ConsentType.ENGAGEMENT_MONITORING
PRODUCTION = SimpleNamespace(is_production=True)


def _request() -> Request:
    return Request(
        {
            "type": "http",
            "method": "POST",
            "path": "/api/v1/auth/consent",
            "headers": [],
            "query_string": b"",
            "scheme": "http",
            "server": ("testserver", 80),
            "client": ("203.0.113.10", 12345),
        }
    )


async def _grant(factory, break_session=None) -> None:  # noqa: ANN001
    """Grant monitoring through the route, in a request-scoped transaction
    as get_db runs it."""
    async with factory() as session:
        if break_session is not None:
            break_session(session)
        try:
            await record_consent(
                payload=ConsentRequest(consent_type=MONITORING, granted=True),
                request=_request(),
                principal=Principal(
                    user_id=STUDENT_ID, role=Role.STUDENT, email="student@clip.example.com"
                ),
                settings=PRODUCTION,
                db=session,
            )
            await session.commit()
        except Exception:
            await session.rollback()
            raise


async def _stored(factory) -> tuple[bool, int]:  # noqa: ANN001
    async with factory() as session:
        granted = MONITORING in await ConsentRepository(session).granted_for(STUDENT_ID)
        audits = await session.scalar(
            select(func.count()).select_from(AuditLog).where(AuditLog.user_id == STUDENT_ID)
        )
    return granted, audits or 0


@pytest.fixture
async def store(db):  # noqa: ANN001, ANN201
    _, factory, _ = db
    classroom.consents.set(STUDENT_ID, {ConsentType.TERMS})
    yield factory
    async with factory() as cleanup:
        await cleanup.execute(delete(Consent).where(Consent.user_id == STUDENT_ID))
        await cleanup.execute(delete(AuditLog).where(AuditLog.user_id == STUDENT_ID))
        await cleanup.commit()


async def test_a_grant_is_kept_with_its_audit_record_and_applies_at_once(store) -> None:  # noqa: ANN001
    await _grant(store)

    assert await _stored(store) == (True, 1)
    assert classroom.consents.monitored(STUDENT_ID)


async def test_a_grant_whose_audit_record_fails_is_neither_kept_nor_live(
    store,  # noqa: ANN001
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def audit_store_down(**_: object) -> AuditLog:
        raise RuntimeError("audit store down")

    monkeypatch.setattr(audit_module, "AuditLog", audit_store_down)

    with pytest.raises(RuntimeError, match="audit store down"):
        await _grant(store)

    assert await _stored(store) == (False, 0)
    assert not classroom.consents.monitored(STUDENT_ID)


async def test_a_grant_whose_commit_fails_is_neither_kept_nor_live(store) -> None:  # noqa: ANN001
    def failing_commit(session) -> None:  # noqa: ANN001
        async def commit() -> None:
            raise ConnectionError("database went away")

        session.commit = commit

    with pytest.raises(ConnectionError):
        await _grant(store, failing_commit)

    assert await _stored(store) == (False, 0)
    assert not classroom.consents.monitored(STUDENT_ID)
