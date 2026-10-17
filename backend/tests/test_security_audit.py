"""Cyber 1, Phase 8: the final security audit, as tests.

Not unit tests of one guard: these walk the whole API as it is published and
fail when a route is added, or changed, without meeting the rules.

* Authentication: every route in the OpenAPI document rejects an anonymous
  caller, except a short, named list.
* RBAC: every route has a declared audience, and a student reaches no staff
  route; a lecturer reaches none of another lecturer's sessions.
* Consent: a signed-in user without terms consent reaches nothing but the
  consent route itself.
* The error envelope never leaks a stack trace, a path or a SQL fragment.
"""

from __future__ import annotations

import asyncio
import re
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient

from app.auth.store import ADMIN_ID, LECTURER_ID, STUDENT_ID
from app.main import app as application
from app.schemas.identity import Role

from .session_support import add_course, create_session, sign_in_as

METHODS = ("get", "post", "put", "patch", "delete")

# Reachable without signing in, and why.
PUBLIC = {
    ("POST", "/api/v1/auth/login"): "how a user signs in",
    ("POST", "/api/v1/auth/refresh"): "the httpOnly refresh cookie is the credential",
    ("POST", "/api/v1/auth/logout"): "clears the refresh cookie, and does nothing without one",
    ("GET", "/api/v1/health"): "liveness for a load balancer",
    ("GET", "/api/v1/ready"): "readiness for a load balancer",
    ("POST", "/api/v1/teams/messages"): "Teams bot endpoint, authenticated by Microsoft's token",
}

# Who each route is for. Anything not named here fails the audit, so a new
# route has to say who it is for.
ANY_USER = "any signed-in user"
STUDENT_ONLY = "students"
STAFF = "lecturers and admins"
ADMIN_ONLY = "admins"
MEMBER = "a member of the session, decided in the handler"

AUDIENCE = {
    ("POST", "/api/v1/auth/consent"): ANY_USER,
    ("GET", "/api/v1/auth/me"): ANY_USER,
    ("POST", "/api/v1/admin/roster"): ADMIN_ONLY,
    ("POST", "/api/v1/admin/timetable"): ADMIN_ONLY,
    ("POST", "/api/v1/materials"): STAFF,
    ("GET", "/api/v1/materials"): STAFF,
    ("GET", "/api/v1/materials/{material_id}"): STAFF,
    ("PATCH", "/api/v1/materials/{material_id}"): STAFF,
    ("DELETE", "/api/v1/materials/{material_id}"): STAFF,
    ("GET", "/api/v1/materials/{material_id}/questions"): STAFF,
    ("PATCH", "/api/v1/materials/{material_id}/questions/{question_id}"): STAFF,
    ("POST", "/api/v1/materials/{material_id}/questions/{question_id}:regenerate"): STAFF,
    ("POST", "/api/v1/materials/{material_id}/questions:bulk"): STAFF,
    ("POST", "/api/v1/meetings/events"): STAFF,
    ("GET", "/api/v1/meetings/{meeting_id}"): STAFF,
    ("PUT", "/api/v1/meetings/{meeting_id}"): STAFF,
    ("POST", "/api/v1/sessions"): STAFF,
    ("GET", "/api/v1/sessions"): ANY_USER,
    ("GET", "/api/v1/sessions/{session_id}"): MEMBER,
    ("GET", "/api/v1/sessions/{session_id}/alerts"): STAFF,
    ("POST", "/api/v1/sessions/{session_id}/alerts/{alert_id}/acknowledge"): STAFF,
    ("POST", "/api/v1/sessions/{session_id}/chat"): STUDENT_ONLY,
    ("POST", "/api/v1/sessions/{session_id}/end"): STAFF,
    ("GET", "/api/v1/sessions/{session_id}/engagement"): STAFF,
    ("POST", "/api/v1/sessions/{session_id}/pause"): STAFF,
    ("GET", "/api/v1/sessions/{session_id}/questions"): STAFF,
    ("POST", "/api/v1/sessions/{session_id}/questions/{question_id}:deliver"): STAFF,
    ("GET", "/api/v1/sessions/{session_id}/readiness"): STAFF,
    ("GET", "/api/v1/sessions/{session_id}/responses"): MEMBER,
    ("POST", "/api/v1/sessions/{session_id}/resume"): STAFF,
    ("POST", "/api/v1/sessions/{session_id}/start"): STAFF,
    ("GET", "/api/v1/sessions/{session_id}/summary/{student_id}"): MEMBER,
    ("GET", "/api/v1/sessions/{session_id}/topics"): STAFF,
    ("POST", "/api/v1/sessions/{session_id}/reports"): STAFF,
    ("GET", "/api/v1/reports/{report_id}"): STAFF,
    ("GET", "/api/v1/reports/{report_id}/pdf"): STAFF,
    ("GET", "/api/v1/student-reviews"): STUDENT_ONLY,
    ("GET", "/api/v1/student-reviews/{session_id}"): STUDENT_ONLY,
    ("GET", "/api/v1/student-reviews/{session_id}/responses/{response_id}/sources"): STUDENT_ONLY,
}

# Routes with a published contract and no handler, so far. Each answers 501 to a
# signed-in caller. Whoever implements one decides its audience, and this audit
# then checks it like the rest. The summary route is implemented on its own
# branch, so it may or may not be a stub here.
STUBS = {
    ("GET", "/api/v1/sessions"),
    ("GET", "/api/v1/sessions/{session_id}"),
    ("GET", "/api/v1/sessions/{session_id}/responses"),
    ("GET", "/api/v1/sessions/{session_id}/summary/{student_id}"),
}

SECRETS = re.compile(
    r"Traceback|File \"|\.py\"|sqlalchemy|asyncpg|psycopg|SELECT |INSERT |UPDATE .* SET|"
    r"password_hash|clip_secret_key|/home/|site-packages",
    flags=re.IGNORECASE,
)


def routes() -> list[tuple[str, str]]:
    found = []
    for path, operations in application.openapi()["paths"].items():
        for method in operations:
            if method in METHODS:
                found.append((method.upper(), path))
    return sorted(found)


def filled(path: str, **ids: UUID) -> str:
    return re.sub(r"\{([^}]+)\}", lambda m: str(ids.get(m.group(1), uuid4())), path)


def call(client: TestClient, method: str, path: str, **ids: UUID):  # noqa: ANN201
    body = {} if method != "GET" else None
    return client.request(method, filled(path, **ids), json=body)


# -- the inventory ------------------------------------------------------------------------


def test_every_route_is_either_public_for_a_reason_or_has_an_audience() -> None:
    unclassified = [r for r in routes() if r not in PUBLIC and r not in AUDIENCE]
    assert unclassified == [], "name who each new route is for in AUDIENCE (or PUBLIC)"


def test_nothing_listed_here_has_been_removed_without_updating_the_audit() -> None:
    known = set(routes())
    assert [r for r in (*PUBLIC, *AUDIENCE) if r not in known] == []


# -- authentication ----------------------------------------------------------------------------


@pytest.mark.parametrize(("method", "path"), [r for r in routes() if r not in PUBLIC])
def test_an_anonymous_caller_is_refused_everywhere(
    client: TestClient, method: str, path: str
) -> None:
    response = call(client, method, path)
    assert response.status_code == 401, (method, path, response.status_code)
    assert not SECRETS.search(response.text)


@pytest.mark.parametrize(
    "header",
    [
        "Bearer",
        "Bearer ",
        "Bearer not.a.jwt",
        "Basic dXNlcjpwYXNz",
        # unsigned, alg none
        "bearer eyJhbGciOiJub25lIn0.eyJzdWIiOiIxMTExMTExMS0xMTExLTExMTEtMTExMS0xMTExMTEifQ.",
        "Token abc",
    ],
)
def test_a_bad_credential_is_refused(client: TestClient, header: str) -> None:
    response = client.get("/api/v1/auth/me", headers={"Authorization": header})
    assert response.status_code == 401


def test_a_token_signed_with_another_key_is_refused(client: TestClient) -> None:
    from datetime import UTC, datetime, timedelta

    import jwt

    forged = jwt.encode(
        {
            "sub": str(ADMIN_ID),
            "role": "admin",
            "email": "admin@clip.example.com",
            "iat": datetime.now(UTC),
            "exp": datetime.now(UTC) + timedelta(hours=1),
        },
        "x" * 40,
        algorithm="HS256",
    )
    assert (
        client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {forged}"}).status_code
        == 401
    )


def test_an_expired_token_is_refused(client: TestClient) -> None:
    from datetime import timedelta

    from app.core.config import get_settings
    from app.core.security import create_access_token

    token, _ = create_access_token(
        user_id=STUDENT_ID,
        role=Role.STUDENT,
        email="student@clip.example.com",
        settings=get_settings(),
        expires_delta=timedelta(seconds=-5),
    )
    assert (
        client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"}).status_code
        == 401
    )


def test_a_valid_token_whose_role_was_changed_is_refused(client: TestClient) -> None:
    from app.core.config import get_settings
    from app.core.security import create_access_token

    token, _ = create_access_token(
        user_id=STUDENT_ID,
        role=Role.ADMIN,  # the student is not an admin
        email="student@clip.example.com",
        settings=get_settings(),
    )
    assert (
        client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"}).status_code
        == 401
    )


# -- RBAC ----------------------------------------------------------------------------------------


STAFF_ROUTES = [r for r, who in AUDIENCE.items() if who in (STAFF, ADMIN_ONLY)]


@pytest.mark.parametrize(("method", "path"), STAFF_ROUTES)
def test_a_student_reaches_no_staff_route(db, app, method: str, path: str) -> None:  # noqa: ANN001
    client, _, _ = db
    sign_in_as(app, STUDENT_ID, Role.STUDENT)
    response = call(client, method, path)
    assert response.status_code == 403, (method, path, response.status_code)
    assert not SECRETS.search(response.text)


ADMIN_ROUTES = [r for r, who in AUDIENCE.items() if who == ADMIN_ONLY]


@pytest.mark.parametrize(("method", "path"), ADMIN_ROUTES)
def test_a_lecturer_reaches_no_admin_route(db, app, method: str, path: str) -> None:  # noqa: ANN001
    client, _, _ = db
    sign_in_as(app, LECTURER_ID, Role.LECTURER)
    assert call(client, method, path).status_code == 403


STUDENT_ROUTES = [r for r, who in AUDIENCE.items() if who == STUDENT_ONLY]


@pytest.mark.parametrize(("method", "path"), STUDENT_ROUTES)
def test_staff_do_not_use_the_students_routes(db, app, method: str, path: str) -> None:  # noqa: ANN001
    client, _, _ = db
    sign_in_as(app, LECTURER_ID, Role.LECTURER)
    assert call(client, method, path).status_code == 403


SESSION_ROUTES = [
    r for r in AUDIENCE if "{session_id}" in r[1] and not r[1].endswith("/chat") and r[0] != "GET"
] + [
    r
    for r in AUDIENCE
    if "{session_id}" in r[1] and r[0] == "GET" and not r[1].endswith("/responses")
]


@pytest.mark.parametrize(("method", "path"), sorted(set(SESSION_ROUTES)))
async def test_another_lecturer_cannot_touch_a_session_they_do_not_run(
    db,
    app,
    method: str,
    path: str,  # noqa: ANN001
) -> None:
    client, factory, created = db
    course = await add_course(factory, created)
    sign_in_as(app, LECTURER_ID, Role.LECTURER)
    session = UUID(create_session(client, course)["id"])

    sign_in_as(app, uuid4(), Role.LECTURER)
    response = call(client, method, path, session_id=session)

    if response.status_code == 501:
        # A route with a frozen contract and no handler yet serves nothing, to
        # anyone. test_unimplemented_routes_are_known makes whoever writes the
        # handler come back here.
        assert (method, path) in STUBS
    else:
        assert response.status_code in (403, 404), (method, path, response.status_code)
    assert not SECRETS.search(response.text)

    sign_in_as(app, LECTURER_ID, Role.LECTURER)
    client.post(f"/api/v1/sessions/{session}/end")


# -- consent ------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("method", "path"),
    [
        r
        for r in AUDIENCE
        if r != ("POST", "/api/v1/auth/consent") and r != ("GET", "/api/v1/auth/me")
    ],
)
def test_without_terms_consent_nothing_is_served(db, app, method: str, path: str) -> None:  # noqa: ANN001
    from app.api.deps import Principal, get_principal
    from app.auth.store import get_consent_repository
    from app.core.config import get_settings
    from app.schemas.identity import ConsentType

    client, _, _ = db
    role = {STUDENT_ONLY: Role.STUDENT, ADMIN_ONLY: Role.ADMIN}.get(
        AUDIENCE[(method, path)], Role.LECTURER
    )
    user = uuid4()
    app.dependency_overrides[get_principal] = lambda: Principal(
        user_id=user, role=role, email=f"{role.value}@clip.example.com"
    )
    get_consent_repository(get_settings()).record(user, ConsentType.TERMS, False)
    response = call(client, method, path)
    assert response.status_code == 403, (method, path, response.status_code)
    assert response.json()["error"]["code"] in {"consent_required", "CONSENT_REQUIRED"} or (
        "consent" in response.text.lower()
    )


def test_unimplemented_routes_are_known(db, app) -> None:  # noqa: ANN001
    """A route that answers 501 must be on the list; one that stops answering
    501 has been implemented and needs its audience checked above."""
    client, factory, created = db
    sign_in_as(app, LECTURER_ID, Role.LECTURER)
    answering = {
        (method, path) for method, path in AUDIENCE if call(client, method, path).status_code == 501
    }
    assert answering <= STUBS, sorted(answering - STUBS)


# -- startup refuses an unknown environment ------------------------------------------------


@pytest.mark.parametrize("name", ["staging", "prod-eu", "Prod ", "produciton", "", "live", "qa"])
def test_an_unrecognised_environment_is_refused_not_treated_as_development(name: str) -> None:
    from pydantic import ValidationError

    from app.core.config import Settings

    if name.strip().lower() in {"prod"}:
        assert Settings(clip_env=name, **_production_settings()).is_production
        return
    with pytest.raises(ValidationError):
        Settings(clip_env=name)


@pytest.mark.parametrize("name", ["Production", " production ", "PROD", "prod\n"])
def test_a_production_name_with_odd_spacing_or_case_is_still_production(name: str) -> None:
    from app.core.config import Settings

    assert Settings(clip_env=name, **_production_settings()).is_production


@pytest.mark.parametrize("name", ["development", "dev", "local", "test", " Testing "])
def test_the_development_names_are_not_production(name: str) -> None:
    from app.core.config import Settings

    assert not Settings(clip_env=name).is_production


def _production_settings() -> dict:
    return {
        "clip_secret_key": "k" * 48,
        "database_url": "postgresql+asyncpg://clip:Zq8vN2mXr4Lp9TwY@db.internal:5432/clip",
    }


# -- headers --------------------------------------------------------------------


def test_every_response_carries_the_basic_hardening_headers(client: TestClient) -> None:
    for path in ("/api/v1/health", "/api/v1/auth/me", "/does-not-exist"):
        response = client.get(path)
        assert response.headers["X-Content-Type-Options"] == "nosniff", path
        assert response.headers["Referrer-Policy"] == "no-referrer", path


def test_api_replies_are_not_cached_but_other_paths_are_left_alone(client: TestClient) -> None:
    assert client.get("/api/v1/auth/me").headers["Cache-Control"] == "no-store"
    assert "Cache-Control" not in client.get("/does-not-exist").headers


def test_a_route_that_sets_its_own_cache_control_keeps_it() -> None:
    from fastapi.responses import JSONResponse

    from app.main import create_app

    app = create_app()

    @app.get("/api/v1/_probe")
    def probe() -> JSONResponse:
        return JSONResponse({}, headers={"Cache-Control": "max-age=5"})

    assert TestClient(app).get("/api/v1/_probe").headers["Cache-Control"] == "max-age=5"


def test_the_app_can_still_be_framed_because_teams_frames_it(client: TestClient) -> None:
    response = client.get("/api/v1/health")
    assert "X-Frame-Options" not in response.headers
    assert "frame-ancestors" not in response.headers.get("Content-Security-Policy", "")


# -- a socket cannot flood the server or hoard connections --------------------------


def test_the_event_limit_counts_a_window() -> None:
    from app.realtime.event_limit import EventLimit

    now = [0.0]
    limit = EventLimit(max_events=3, window=10.0, clock=lambda: now[0])
    assert [limit.allow() for _ in range(4)] == [True, True, True, False]
    now[0] = 10.5
    assert limit.allow()  # the window has moved on


def test_a_refused_event_does_not_extend_the_window() -> None:
    from app.realtime.event_limit import EventLimit

    now = [0.0]
    limit = EventLimit(max_events=2, window=10.0, clock=lambda: now[0])
    assert limit.allow() and limit.allow()
    for i in range(1, 9):
        now[0] = float(i)
        assert not limit.allow()
    now[0] = 10.5
    assert limit.allow()


def test_the_limits_leave_room_for_a_real_client() -> None:
    from app.realtime.event_limit import MAX_EVENTS, WINDOW_SECONDS

    # An attention reading every 2 seconds, a ping every 5, answers: well under.
    assert MAX_EVENTS / WINDOW_SECONDS >= 5


async def test_a_socket_that_floods_is_closed(db, app, monkeypatch) -> None:  # noqa: ANN001
    from fastapi.websockets import WebSocketDisconnect

    from app.api.v1 import ws as ws_module
    from app.realtime import event_limit

    from .dev_credentials import STUDENT_PASSWORD
    from .session_support import add_question, enrol, token_for

    client, factory, created = db
    course = await add_course(factory, created)
    await enrol(factory, course)
    await add_question(db, course, LECTURER_ID)
    sign_in_as(app, LECTURER_ID, Role.LECTURER)
    session = create_session(client, course)
    assert client.post(f"/api/v1/sessions/{session['id']}/start").status_code == 200
    token = token_for(client, "student@clip.example.com", STUDENT_PASSWORD)
    monkeypatch.setattr(
        ws_module, "EventLimit", lambda: event_limit.EventLimit(max_events=5, window=60)
    )

    try:
        with pytest.raises(WebSocketDisconnect) as closed:  # noqa: PT012
            with client.websocket_connect("/ws/session") as ws:
                ws.send_json(
                    {"type": "auth", "data": {"token": token, "session_id": session["id"]}}
                )
                assert ws.receive_json()["type"] == "ready"
                for _ in range(20):
                    ws.send_json({"type": "ping"})
                for _ in range(40):
                    ws.receive_json()
    finally:
        client.post(f"/api/v1/sessions/{session['id']}/end")
    assert closed.value.code == ws_module.CLOSE_RATE_LIMITED


async def test_too_many_open_sockets_for_one_user_are_refused(db, app, monkeypatch) -> None:  # noqa: ANN001
    from fastapi.websockets import WebSocketDisconnect

    from app.api.v1 import ws as ws_module

    from .dev_credentials import STUDENT_PASSWORD
    from .session_support import add_question, enrol, token_for

    client, factory, created = db
    course = await add_course(factory, created)
    await enrol(factory, course)
    await add_question(db, course, LECTURER_ID)
    sign_in_as(app, LECTURER_ID, Role.LECTURER)
    session = create_session(client, course)
    assert client.post(f"/api/v1/sessions/{session['id']}/start").status_code == 200
    token = token_for(client, "student@clip.example.com", STUDENT_PASSWORD)
    monkeypatch.setattr(ws_module, "MAX_SOCKETS_PER_USER", 2)
    auth = {"type": "auth", "data": {"token": token, "session_id": session["id"]}}

    try:
        with (
            client.websocket_connect("/ws/session") as first,
            client.websocket_connect("/ws/session") as second,
        ):
            for ws in (first, second):
                ws.send_json(auth)
                assert ws.receive_json()["type"] == "ready"
                assert ws.receive_json()["type"] == "session.state"
            with pytest.raises(WebSocketDisconnect) as closed:  # noqa: PT012
                with client.websocket_connect("/ws/session") as third:
                    third.send_json(auth)
                    third.receive_json()
            assert closed.value.code == ws_module.CLOSE_RATE_LIMITED
            # The two that were open are unaffected.
            first.send_json({"type": "ping"})
            assert first.receive_json()["type"] == "pong"
    finally:
        client.post(f"/api/v1/sessions/{session['id']}/end")


# -- the cap holds when connections arrive together, and on a user's own channel -------------


class _Closing:
    """A socket that records how it was closed."""

    def __init__(self) -> None:
        self.closed: list[int] = []
        self.sent: list[dict] = []

    async def send_json(self, payload: dict) -> None:
        # Yield, as a real socket does: without it each connect finishes before
        # the next starts and no race could ever show.
        await asyncio.sleep(0)
        self.sent.append(payload)

    async def close(self, code: int, reason: str = "") -> None:
        await asyncio.sleep(0)
        self.closed.append(code)


async def test_concurrent_connections_cannot_all_slip_under_the_cap() -> None:
    import asyncio

    from app.realtime.event_limit import CLOSE_RATE_LIMITED
    from app.realtime.hub import Connection, SessionHub

    hub = SessionHub()
    user, session = uuid4(), uuid4()
    sockets = [_Closing() for _ in range(8)]
    results = await asyncio.gather(
        *(
            hub.connect(Connection(s, user, session, Role.STUDENT), max_per_user=3)  # type: ignore[arg-type]
            for s in sockets
        )
    )
    assert sum(results) == 3
    assert hub.connection_count(session, user) == 3
    refused = [s for s, ok in zip(sockets, results, strict=True) if not ok]
    assert len(refused) == 5
    assert all(s.closed == [CLOSE_RATE_LIMITED] for s in refused)


async def test_the_cap_applies_to_a_users_own_channel_too() -> None:
    import asyncio

    from app.realtime.hub import Connection, SessionHub

    hub = SessionHub()
    user = uuid4()
    results = await asyncio.gather(
        *(
            hub.connect(Connection(_Closing(), user, None, Role.STUDENT), max_per_user=2)  # type: ignore[arg-type]
            for _ in range(5)
        )
    )
    assert sum(results) == 2


async def test_one_users_sockets_do_not_use_up_anothers_allowance() -> None:
    from app.realtime.hub import Connection, SessionHub

    hub = SessionHub()
    session = uuid4()
    a, b = uuid4(), uuid4()
    for user in (a, a, b, b):
        assert await hub.connect(
            Connection(_Closing(), user, session, Role.STUDENT),  # type: ignore[arg-type]
            max_per_user=2,
        )
    assert not await hub.connect(
        Connection(_Closing(), a, session, Role.STUDENT),  # type: ignore[arg-type]
        max_per_user=2,
    )


def test_a_user_channel_socket_over_the_cap_is_closed_over_the_real_endpoint(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    from fastapi.websockets import WebSocketDisconnect

    from app.api.v1 import ws as ws_module

    from .dev_credentials import STUDENT_PASSWORD

    login = client.post(
        "/api/v1/auth/login",
        json={"email": "student@clip.example.com", "password": STUDENT_PASSWORD},
    )
    token = login.json()["access_token"]
    monkeypatch.setattr(ws_module, "MAX_SOCKETS_PER_USER", 1)
    auth = {"type": "auth", "data": {"token": token}}
    with client.websocket_connect("/ws/session") as first:
        first.send_json(auth)
        assert first.receive_json()["type"] == "ready"
        with pytest.raises(WebSocketDisconnect) as closed:  # noqa: PT012
            with client.websocket_connect("/ws/session") as second:
                second.send_json(auth)
                second.receive_json()
        assert closed.value.code == ws_module.CLOSE_RATE_LIMITED
        first.send_json({"type": "ping"})
        assert first.receive_json()["type"] == "pong"


async def test_another_lecturer_cannot_read_a_report_by_its_id(db, app) -> None:  # noqa: ANN001
    client, factory, created = db
    course = await add_course(factory, created)
    sign_in_as(app, LECTURER_ID, Role.LECTURER)
    session = create_session(client, course)
    asked = client.post(f"/api/v1/sessions/{session['id']}/reports")
    assert asked.status_code == 202
    report_id = asked.json()["report_id"]
    assert client.get(f"/api/v1/reports/{report_id}").status_code == 200

    sign_in_as(app, uuid4(), Role.LECTURER)
    missing = client.get(f"/api/v1/reports/{uuid4()}")
    for path in (f"/api/v1/reports/{report_id}", f"/api/v1/reports/{report_id}/pdf"):
        response = client.get(path)
        # The same answer as a report that does not exist.
        assert response.status_code == missing.status_code == 404, path
        assert response.json()["error"]["message"] == missing.json()["error"]["message"]

    sign_in_as(app, STUDENT_ID, Role.STUDENT)
    assert client.get(f"/api/v1/reports/{report_id}").status_code == 403
