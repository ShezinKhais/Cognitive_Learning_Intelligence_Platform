"""Every failure must leave the API in the same envelope.

The frontend has one error path, so an endpoint that returns a bare string or a
raw stack trace breaks it. These tests pin the shape.
"""

from fastapi.testclient import TestClient

from app.main import create_app


def _assert_envelope(body: dict) -> None:
    assert set(body) == {"error", "request_id"}
    assert set(body["error"]) == {"code", "message", "detail"}
    assert body["error"]["code"] == body["error"]["code"].upper()
    assert body["error"]["message"]


def test_unknown_route_returns_the_envelope(client: TestClient) -> None:
    response = client.get("/api/v1/does-not-exist")
    assert response.status_code == 404
    _assert_envelope(response.json())
    assert response.json()["error"]["code"] == "NOT_FOUND"


def test_validation_failure_is_serialisable(client: TestClient) -> None:
    """Pydantic's raw errors contain exception objects that json cannot encode.

    Sending an invalid body used to produce a 500 while trying to report a 422.
    """
    response = client.post("/api/v1/auth/login", json={"email": "not-an-email"})
    assert response.status_code == 422

    body = response.json()
    _assert_envelope(body)
    assert body["error"]["code"] == "VALIDATION_ERROR"
    assert body["error"]["detail"]["errors"]


def test_authentication_is_checked_before_anything_else(client: TestClient) -> None:
    """Unauthenticated callers must not learn which routes exist or are stubs.

    Every stub sits behind the auth dependency, so 401 comes first and 501 is
    unreachable until Cyber 1 lands token validation.
    """
    response = client.get("/api/v1/sessions", headers={"Authorization": "Bearer nonsense"})
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "UNAUTHENTICATED"


def test_unimplemented_route_names_its_owner(as_lecturer: TestClient) -> None:
    """Past the auth gate, a stub tells you who is building it and when."""
    response = as_lecturer.get("/api/v1/sessions")
    assert response.status_code == 501

    body = response.json()
    _assert_envelope(body)
    assert body["error"]["code"] == "NOT_IMPLEMENTED"
    assert body["error"]["detail"]["owner"] == "BBIS"
    assert body["error"]["detail"]["phase"] == "Phase 3"


def test_every_stub_reports_an_owner(as_lecturer: TestClient) -> None:
    """No route may 501 without saying who is responsible for it."""
    paths = {
        ("get", "/api/v1/materials"),
        ("get", "/api/v1/sessions"),
        ("get", "/api/v1/auth/me"),
    }
    for method, path in paths:
        response = as_lecturer.request(method.upper(), path)
        assert response.status_code == 501, f"{path} returned {response.status_code}"
        assert response.json()["error"]["detail"]["owner"], f"{path} has no owner"


def test_unauthenticated_requests_are_rejected(client: TestClient) -> None:
    """Every protected route must fail closed while auth is unimplemented."""
    for path in (
        "/api/v1/auth/me",
        "/api/v1/materials",
        "/api/v1/sessions",
    ):
        response = client.get(path)
        assert response.status_code == 401, f"{path} did not fail closed"
        assert response.json()["error"]["code"] == "UNAUTHENTICATED"


def test_request_id_is_returned_and_echoed(client: TestClient) -> None:
    generated = client.get("/api/v1/health")
    assert generated.headers["X-Request-ID"]

    supplied = client.get("/api/v1/health", headers={"X-Request-ID": "trace-me"})
    assert supplied.headers["X-Request-ID"] == "trace-me"


def test_request_id_appears_in_error_bodies(client: TestClient) -> None:
    """Without this a user reporting an error has nothing to quote."""
    response = client.get("/api/v1/nope", headers={"X-Request-ID": "trace-me"})
    assert response.json()["request_id"] == "trace-me"


def test_a_crash_is_traceable_and_says_nothing_else() -> None:
    """The 500 path runs in ServerErrorMiddleware, outside the middleware that
    stamps the header, so it has to carry the id itself. It is also the one
    response most likely to hold a driver message or a stack trace.

    Built on its own app rather than the session fixture: adding a route to the
    shared one would put it in the contract every later test checks.
    """
    crashing = create_app()

    @crashing.get("/api/v1/__crash")
    async def crash() -> None:
        raise RuntimeError("asyncpg: password authentication failed for user 'clip'")

    with TestClient(crashing, raise_server_exceptions=False) as client:
        response = client.get("/api/v1/__crash", headers={"X-Request-ID": "trace-me"})

    assert response.status_code == 500
    assert response.headers["X-Request-ID"] == "trace-me"
    assert response.json()["request_id"] == "trace-me"

    body = response.text
    for leak in ("asyncpg", "password", "Traceback", "RuntimeError"):
        assert leak not in body, f"a 500 leaked {leak!r}"
