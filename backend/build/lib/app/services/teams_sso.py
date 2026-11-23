"""Teams single sign-on: a Microsoft Entra token in, the C.L.I.P account out.

Inside Teams the tab asks Teams for a token (authentication.getAuthToken) and
sends it here. It is an access token Entra issued for this app's API, so it is
checked against Entra's published keys, this deployment's tenant and this
app's Application ID URI before anything in it is believed.

The account is found by the validated tid and oid first. The first time, it
is found by the token's sign-in name, the user's UPN, and the pair is then
recorded in teams_user_mapping, which is how the bot later knows who in a
meeting roster is which C.L.I.P user. Nobody is created here: an account must
already exist, so a Microsoft account in the tenant is not by itself a way in.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from functools import lru_cache
from urllib.parse import urlparse

import jwt

from app.core.config import Settings
from app.core.errors import AuthenticationError, ServiceUnavailableError
from app.services.teams_bot import BotFrameworkKeys

log = logging.getLogger("clip.security")

# The delegated scope the Teams tab is pre-authorised for.
SSO_SCOPE = "access_as_user"

# Entra allows a few minutes of clock skew either way.
CLOCK_SKEW_SECONDS = 300

GENERIC_SSO_ERROR = "Microsoft sign-in could not be checked. Try again from Teams."


@dataclass(frozen=True)
class EntraIdentity:
    tenant_id: str
    object_id: str
    sign_in_name: str


def application_id_uri(settings: Settings) -> str:
    """api://<host>/<client id>, as set under Expose an API."""
    host = urlparse(settings.teams_app_base_url).hostname or ""
    return f"api://{host}/{settings.client_id}"


def sso_ready(settings: Settings) -> bool:
    return bool(settings.client_id and settings.tenant_id and settings.teams_app_base_url)


@lru_cache
def _entra_keys(tenant_id: str) -> BotFrameworkKeys:
    # The same bounded, rate-limited key cache the bot uses, on Entra's set.
    return BotFrameworkKeys(f"https://login.microsoftonline.com/{tenant_id}/discovery/v2.0/keys")


async def verify_entra_token(token: str, settings: Settings) -> EntraIdentity:
    """The validated identity in a Teams SSO token, or AuthenticationError."""
    if not sso_ready(settings):
        raise ServiceUnavailableError("Teams sign-in is not configured on this server.")
    tenant = settings.tenant_id.strip().lower()
    try:
        signing = await _entra_keys(tenant).key_for(token)
        claims = jwt.decode(
            token,
            signing.key,
            algorithms=["RS256"],
            # v2 tokens name the app by client id, v1 by Application ID URI.
            audience=[settings.client_id, application_id_uri(settings)],
            leeway=CLOCK_SKEW_SECONDS,
            options={"require": ["exp", "iss", "aud", "tid", "oid"]},
        )
    except jwt.PyJWKClientConnectionError as exc:
        raise ServiceUnavailableError("Microsoft's signing keys are unreachable.") from exc
    except jwt.PyJWTError as exc:
        log.warning("security_event=TEAMS_SSO_REFUSED reason=token detail=%s", exc)
        raise AuthenticationError(GENERIC_SSO_ERROR) from exc

    token_tenant = str(claims.get("tid", "")).lower()
    issuers = {
        f"https://login.microsoftonline.com/{tenant}/v2.0",
        f"https://sts.windows.net/{tenant}/",
    }
    if token_tenant != tenant or str(claims.get("iss", "")).lower() not in issuers:
        log.warning("security_event=TEAMS_SSO_REFUSED reason=tenant")
        raise AuthenticationError(GENERIC_SSO_ERROR)
    if SSO_SCOPE not in str(claims.get("scp", "")).split():
        log.warning("security_event=TEAMS_SSO_REFUSED reason=scope")
        raise AuthenticationError(GENERIC_SSO_ERROR)

    sign_in_name = str(claims.get("preferred_username") or claims.get("upn") or "").strip().lower()
    object_id = str(claims["oid"]).strip().lower()
    if not object_id:
        raise AuthenticationError(GENERIC_SSO_ERROR)
    return EntraIdentity(tenant_id=token_tenant, object_id=object_id, sign_in_name=sign_in_name)
