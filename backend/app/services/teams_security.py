"""Signature verification for the Teams meeting-event webhook.

Owner: Cyber 1, Phase 4. Real Teams infrastructure signs its callbacks; the
mock adapter this prototype runs against in development does not have that
infrastructure to hand, so the same endpoint has to support both without
becoming two different code paths. The rule is least privilege by
environment: production always requires a valid signature, development
allows an unsigned call only until a secret is actually configured, at which
point it holds the same caller to the same standard a deployment would.
"""

from __future__ import annotations

import hashlib
import hmac
import logging

from app.core.config import Settings

log = logging.getLogger("clip.teams")

SIGNATURE_HEADER = "X-Teams-Signature"


def sign(body: bytes, secret: str) -> str:
    """The signature a caller must send: hex HMAC-SHA256 of the raw body."""
    return hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()


def verify_teams_signature(
    body: bytes,
    signature: str | None,
    settings: Settings,
) -> bool:
    """Whether this webhook call is allowed to proceed.

    Fails closed: no secret configured and a production deployment means no
    caller can ever authenticate, which is the intended state until Teams
    credentials (and this secret) are actually provisioned -- see
    Settings._reject_unsafe_production_config, which refuses to boot with
    Teams credentials set but no webhook secret, so this branch should be
    unreachable in a real production deployment.
    """
    if not settings.teams_webhook_secret:
        if settings.is_production:
            log.warning(
                "security_event=ACCESS_DENIED transport=teams_webhook reason=no_secret_configured"
            )
            return False
        # Development/test without a configured secret: this is the mock
        # adapter path, and there is nothing to verify a signature against.
        return True

    if not signature:
        log.warning("security_event=ACCESS_DENIED transport=teams_webhook reason=missing_signature")
        return False

    expected = sign(body, settings.teams_webhook_secret)
    # compare_digest, not ==, so a wrong signature cannot be brute-forced one
    # byte at a time via response-timing differences.
    if not hmac.compare_digest(expected, signature):
        log.warning("security_event=ACCESS_DENIED transport=teams_webhook reason=invalid_signature")
        return False

    return True
