"""What the API gives away before anyone authenticates.

Development is permissive on purpose. These pin what changes in production so a
convenience does not survive into deployment.
"""

from uuid import UUID

import pytest
from fastapi.testclient import TestClient

from app.core.config import Settings, get_settings
from app.main import create_app


@pytest.fixture
def production_client(monkeypatch: pytest.MonkeyPatch) -> TestClient:
    production = Settings(
        clip_env="production",
        clip_secret_key="a-real-key",
        database_url="postgresql+asyncpg://clip:s3cret@db:5432/clip",
    )
    monkeypatch.setattr("app.main.settings", production)
    monkeypatch.setattr("app.api.v1.health.get_settings", lambda: production)

    app = create_app()
    app.dependency_overrides[get_settings] = lambda: production
    return TestClient(app)


def test_docs_are_available_in_development(client: TestClient) -> None:
    assert client.get("/docs").status_code == 200
    assert client.get("/api/v1/openapi.json").status_code == 200


def test_docs_are_closed_in_production(production_client: TestClient) -> None:
    """Interactive docs are a complete inventory of every route and schema."""
    for path in ("/docs", "/redoc", "/api/v1/openapi.json"):
        assert production_client.get(path).status_code == 404, f"{path} is exposed"


def test_readiness_explains_failures_in_development(client: TestClient) -> None:
    body = client.get("/api/v1/ready").json()
    assert {d["name"] for d in body["dependencies"]} == {"postgres", "ollama"}
    assert any("detail" in d for d in body["dependencies"])


def test_readiness_hides_internals_in_production(production_client: TestClient) -> None:
    """Load balancers need the endpoint open, so it must not describe why it
    failed. Exception types and component detail belong in the logs."""
    response = production_client.get("/api/v1/ready")
    assert response.status_code in (200, 503)

    for dependency in response.json()["dependencies"]:
        assert dependency["detail"] is None, "production readiness leaks failure detail"
        assert dependency["latency_ms"] is None


def test_a_plausible_request_id_is_honoured(client: TestClient) -> None:
    """A trace started upstream should survive into our logs."""
    response = client.get("/api/v1/health", headers={"X-Request-ID": "teams-proxy-abc123"})
    assert response.headers["X-Request-ID"] == "teams-proxy-abc123"


@pytest.mark.parametrize(
    ("label", "value"),
    [
        ("newline", "ok\nLOG [forged] ADMIN LOGIN SUCCEEDED user=attacker"),
        ("carriage return", "ok\r\nSet-Cookie: session=stolen"),
        ("too long", "a" * 200),
        ("markup", "<script>alert(1)</script>"),
        ("empty", ""),
    ],
)
def test_a_hostile_request_id_is_replaced(client: TestClient, label: str, value: str) -> None:
    """The id is echoed in a header and formatted into every log line for the
    request, so an unvalidated one lets a caller forge log entries."""
    response = client.get("/api/v1/health", headers={"X-Request-ID": value})
    echoed = response.headers["X-Request-ID"]

    assert echoed != value, label
    assert UUID(echoed), f"{label}: expected a generated uuid"


def test_health_never_reveals_secrets(client: TestClient) -> None:
    body = client.get("/api/v1/health").json()
    assert set(body) == {"status", "env", "version", "teams_configured"}
    assert isinstance(body["teams_configured"], bool), "must be a flag, never the credential"
