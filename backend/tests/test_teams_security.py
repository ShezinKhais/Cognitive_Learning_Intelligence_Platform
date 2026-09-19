"""Signature verification for the Teams meeting-event webhook.

Owner: Cyber 1, Phase 4.
"""

from types import SimpleNamespace

from app.core.config import Settings
from app.services.teams_security import sign, verify_teams_signature

BODY = b'{"event": "meeting.started"}'


def test_development_without_a_secret_allows_the_mock_adapter():
    settings = Settings(clip_env="development", teams_webhook_secret="")
    assert verify_teams_signature(BODY, None, settings) is True


def test_production_without_a_secret_configured_fails_closed():
    # A stand-in rather than a real Settings(clip_env="production", ...):
    # Settings itself refuses to construct an insecure production config, and
    # this test is about verify_teams_signature's own fail-closed behaviour,
    # not about that separate startup guard.
    settings = SimpleNamespace(is_production=True, teams_webhook_secret="")
    assert verify_teams_signature(BODY, None, settings) is False


def test_missing_signature_is_rejected_once_a_secret_is_configured():
    settings = Settings(teams_webhook_secret="a-real-secret")
    assert verify_teams_signature(BODY, None, settings) is False


def test_wrong_signature_is_rejected():
    settings = Settings(teams_webhook_secret="a-real-secret")
    assert verify_teams_signature(BODY, "0" * 64, settings) is False


def test_correct_signature_is_accepted():
    settings = Settings(teams_webhook_secret="a-real-secret")
    signature = sign(BODY, "a-real-secret")
    assert verify_teams_signature(BODY, signature, settings) is True


def test_a_signature_for_a_different_body_is_rejected():
    settings = Settings(teams_webhook_secret="a-real-secret")
    signature = sign(b"different body", "a-real-secret")
    assert verify_teams_signature(BODY, signature, settings) is False
