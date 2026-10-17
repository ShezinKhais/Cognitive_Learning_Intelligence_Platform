"""Every route that changes state on a signed-in user's behalf leaves an
audit record (Cyber 1, Phase 1 #34), and one really is written.

Owner: Cyber 1 for the rule, General CS for wiring it, in Phase 8. Before
this, @audit_action was on the consent route alone.
"""

from __future__ import annotations

from types import SimpleNamespace

from fastapi import FastAPI, Request
from fastapi.routing import APIRoute
from sqlalchemy import delete, select

from app.api.deps import Principal
from app.api.v1.sessions import create_session as create_session_route
from app.auth.store import LECTURER_ID
from app.main import create_app
from app.models.audit_log import AuditLog
from app.schemas.identity import Role
from app.schemas.session import SessionCreateRequest

from .session_support import add_course

# State-changing routes left unaudited, and why.
NOT_AUDITED = {
    # Nobody is signed in yet. Failed attempts and lockouts are logged and
    # counted by the login itself.
    ("POST", "/api/v1/auth/login"),
    # A student asking for their own data to be erased. The deletion request
    # service writes the audit entry itself (DELETION_REQUESTED).
    ("POST", "/api/v1/me/deletion-request"),
    # Renews the caller's own token and changes nothing that is kept. Every
    # refresh and refusal is in the security log, and an audit row an hour
    # per signed-in user would bury the changes the log is for.
    ("POST", "/api/v1/auth/refresh"),
    # Authenticated by Bot Framework, not a user; acts through the meeting
    # routes' service, and each activity is logged.
    ("POST", "/api/v1/teams/messages"),
    # Asks the tutor a question and changes nothing that is kept.
    ("POST", "/api/v1/sessions/{session_id}/chat"),
    # Streams the upload to disk outside any database transaction, so there
    # is none for the record to join. The material row it creates records
    # who uploaded it and when.
    ("POST", "/api/v1/materials"),
    # Governance routes (BBIS, Phase 7). Not unaudited: each one's service writes
    # its own audit entry in the same transaction, with the target and counts
    # (docs/governance.md), always and not only in production. The decorator
    # would add a second, poorer row for the same action.
    ("POST", "/api/v1/governance/deletion-requests"),
    ("POST", "/api/v1/governance/deletion-requests/{request_id}/approve"),
    ("POST", "/api/v1/governance/deletion-requests/{request_id}/reject"),
    ("POST", "/api/v1/governance/deletion-requests/{request_id}/execute"),
    ("POST", "/api/v1/governance/retention/run"),
}


def _routes(app: FastAPI):  # noqa: ANN202
    seen: set[int] = set()

    def walk(router):  # noqa: ANN001, ANN202
        for route in getattr(router, "routes", None) or []:
            if isinstance(route, APIRoute):
                yield route
                continue
            for attr in ("router", "original_router", "app"):
                inner = getattr(route, attr, None)
                if inner is not None and id(inner) not in seen:
                    seen.add(id(inner))
                    yield from walk(inner)

    return walk(app.router)


def test_every_state_changing_route_is_audited_or_says_why_not() -> None:
    app = create_app()
    prefix = "/api/v1"
    unaudited = sorted(
        (method, path)
        for route in _routes(app)
        for method in route.methods & {"POST", "PUT", "PATCH", "DELETE"}
        for path in [route.path if route.path.startswith(prefix) else prefix + route.path]
        if not hasattr(route.endpoint, "audit_action_type") and (method, path) not in NOT_AUDITED
    )
    assert unaudited == []


def test_the_exemptions_name_routes_that_still_exist() -> None:
    app = create_app()
    prefix = "/api/v1"
    present = {
        (method, route.path if route.path.startswith(prefix) else prefix + route.path)
        for route in _routes(app)
        for method in route.methods
    }
    assert present >= NOT_AUDITED


async def test_an_audited_route_writes_its_record_in_production(db) -> None:  # noqa: ANN001
    _, factory, created = db
    course = await add_course(factory, created)
    request = Request(
        {
            "type": "http",
            "method": "POST",
            "path": "/api/v1/sessions",
            "headers": [],
            "query_string": b"",
            "scheme": "http",
            "server": ("testserver", 80),
            "client": ("203.0.113.20", 1),
        }
    )
    async with factory() as session:
        before = set(
            await session.scalars(select(AuditLog.log_id).where(AuditLog.user_id == LECTURER_ID))
        )
        made = await create_session_route(
            payload=SessionCreateRequest(course_code=course.code, title="Audited"),
            principal=Principal(
                user_id=LECTURER_ID, role=Role.LECTURER, email="lecturer@clip.example.com"
            ),
            request=request,
            settings=SimpleNamespace(is_production=True),
            db=session,
        )
        await session.commit()

    async with factory() as session:
        rows = (
            await session.scalars(
                select(AuditLog).where(
                    AuditLog.user_id == LECTURER_ID, AuditLog.log_id.not_in(before)
                )
            )
        ).all()
        assert [(r.action_type, r.ip_address) for r in rows] == [
            ("SESSION_CREATED", "203.0.113.20")
        ]
        await session.execute(delete(AuditLog).where(AuditLog.log_id.in_([r.log_id for r in rows])))
        await session.commit()
    assert made.title == "Audited"
