from fastapi.testclient import TestClient

from app.core.config import Settings


def test_health(client: TestClient) -> None:
    response = client.get("/api/v1/health")
    assert response.status_code == 200

    body = response.json()
    assert body["status"] == "ok"
    assert body["version"]
    assert isinstance(body["teams_configured"], bool)


def test_readiness_reports_each_dependency(client: TestClient) -> None:
    """Readiness must name what is broken, not just fail.

    Returns 503 when Postgres is unreachable, which is why this passes with or
    without a database running.
    """
    response = client.get("/api/v1/ready")
    assert response.status_code in (200, 503)

    body = response.json()
    names = {d["name"] for d in body["dependencies"]}
    assert names == {"postgres", "ollama"}
    assert body["ready"] is (response.status_code == 200)

    for dependency in body["dependencies"]:
        if not dependency["ok"]:
            assert dependency["detail"], "a failed dependency must explain why"


def test_ollama_does_not_gate_readiness(client: TestClient) -> None:
    """The live session serves pre-generated questions, so a model being down
    degrades the service rather than stopping it."""
    body = client.get("/api/v1/ready").json()
    postgres = next(d for d in body["dependencies"] if d["name"] == "postgres")
    assert body["ready"] == postgres["ok"]


def test_teams_requires_all_three_credentials() -> None:
    # A partial set would register the bot endpoint against a broken identity.
    assert not Settings(client_id="", client_secret="", tenant_id="").teams_configured
    assert not Settings(client_id="a", client_secret="", tenant_id="c").teams_configured
    assert not Settings(client_id="a", client_secret="b", tenant_id="").teams_configured
    assert Settings(client_id="a", client_secret="b", tenant_id="c").teams_configured


def test_upload_extensions_are_parsed_and_normalised() -> None:
    settings = Settings(allowed_upload_extensions="PDF, pptx ,docx,txt,")
    assert settings.upload_extensions == {"pdf", "pptx", "docx", "txt"}


def test_session_defaults() -> None:
    # 30s comes from the design document; the SRS still says 50s.
    settings = Settings()
    assert settings.checkpoint_response_window_seconds == 30
    assert settings.comprehension_alert_threshold == 0.50
    assert settings.data_retention_days == 90
