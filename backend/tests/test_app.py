from fastapi.testclient import TestClient

from app.core.config import Settings
from app.main import app

client = TestClient(app)


def test_app_boots_and_reports_health() -> None:
    response = client.get("/health")
    assert response.status_code == 200

    body = response.json()
    assert body["status"] == "ok"
    assert isinstance(body["teams_configured"], bool)


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
