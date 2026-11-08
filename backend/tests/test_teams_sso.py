"""Teams single sign-on: Entra token checks and the /auth/teams route."""

from __future__ import annotations

import time
import uuid

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi.testclient import TestClient

from app.api.v1 import identity
from app.auth.store import STUDENT_ID
from app.core.config import Settings
from app.core.errors import AuthenticationError
from app.services import teams_sso
from app.services.teams_bot import BotSigningKey
from app.services.teams_sso import EntraIdentity, application_id_uri, verify_entra_token

TENANT = "8f3a1c2e-0000-4000-8000-00000000c11b"
CLIENT = "5b0e6a44-0000-4000-8000-0000000000a1"
BASE = "https://clip-5173.uks1.devtunnels.ms"
KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)
OTHER_KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)


def _settings(**overrides) -> Settings:
    values = {"client_id": CLIENT, "tenant_id": TENANT, "teams_app_base_url": BASE}
    return Settings(**(values | overrides))


def _token(key=KEY, **claims) -> str:
    now = int(time.time())
    body = {
        "aud": CLIENT,
        "iss": f"https://login.microsoftonline.com/{TENANT}/v2.0",
        "tid": TENANT,
        "oid": "0a1b2c3d-0000-4000-8000-000000000001",
        "preferred_username": "Student1@CLIP736.onmicrosoft.com",
        "scp": "access_as_user",
        "iat": now,
        "nbf": now,
        "exp": now + 3600,
    } | claims
    return jwt.encode(
        {k: v for k, v in body.items() if v is not None}, key, "RS256", headers={"kid": "k1"}
    )


@pytest.fixture(autouse=True)
def entra_keys(monkeypatch):
    class Keys:
        async def key_for(self, token):
            return BotSigningKey(KEY.public_key(), frozenset())

    monkeypatch.setattr(teams_sso, "_entra_keys", lambda tenant: Keys())


async def test_a_valid_token_gives_the_identity():
    found = await verify_entra_token(_token(), _settings())
    assert found == EntraIdentity(
        tenant_id=TENANT,
        object_id="0a1b2c3d-0000-4000-8000-000000000001",
        sign_in_name="student1@clip736.onmicrosoft.com",
    )


async def test_the_application_id_uri_is_accepted_as_audience():
    settings = _settings()
    assert application_id_uri(settings) == f"api://clip-5173.uks1.devtunnels.ms/{CLIENT}"
    await verify_entra_token(_token(aud=application_id_uri(settings)), settings)


async def test_a_v1_issuer_is_accepted():
    await verify_entra_token(_token(iss=f"https://sts.windows.net/{TENANT}/"), _settings())


@pytest.mark.parametrize(
    "claims",
    [
        {"aud": "some-other-app"},
        {"tid": "00000000-0000-4000-8000-000000000bad"},
        {"iss": "https://login.microsoftonline.com/00000000-0000-4000-8000-000000000bad/v2.0"},
        {"scp": "User.Read"},
        {"scp": None},
        {"oid": None},
        {"exp": int(time.time()) - 3600},
    ],
    ids=["audience", "tenant", "issuer", "scope", "no-scope", "no-oid", "expired"],
)
async def test_a_token_for_something_else_is_refused(claims):
    with pytest.raises(AuthenticationError):
        await verify_entra_token(_token(**claims), _settings())


async def test_a_token_signed_by_another_key_is_refused():
    with pytest.raises(AuthenticationError):
        await verify_entra_token(_token(key=OTHER_KEY), _settings())


async def test_sign_in_needs_the_registration():
    from app.core.errors import ServiceUnavailableError

    with pytest.raises(ServiceUnavailableError):
        await verify_entra_token(_token(), _settings(teams_app_base_url=""))


class FakeMappings:
    """teams_user_mapping without a database."""

    links: dict[tuple[str, str], uuid.UUID] = {}

    def __init__(self, session):
        pass

    async def user_for(self, *, tenant_id, teams_user_id):
        return self.links.get((tenant_id, teams_user_id))

    async def link_user(self, *, tenant_id, teams_user_id, user_id):
        self.links[(tenant_id, teams_user_id)] = user_id


@pytest.fixture
def sso_route(monkeypatch):
    FakeMappings.links = {}
    monkeypatch.setattr(identity, "TeamsUserMappingRepository", FakeMappings)

    def sign_in(identity_found: EntraIdentity):
        async def verify(token, settings):
            return identity_found

        monkeypatch.setattr(identity, "verify_entra_token", verify)

    return sign_in


def _post(client: TestClient):
    return client.post("/api/v1/auth/teams", json={"token": "from-teams"})


def test_a_known_account_signs_in_and_is_linked(client: TestClient, sso_route):
    sso_route(EntraIdentity(TENANT, "oid-student", "student@clip.example.com"))
    response = _post(client)
    assert response.status_code == 200
    assert response.json()["role"] == "student"
    assert "clip_refresh" in response.headers.get("set-cookie", "")
    assert FakeMappings.links == {(TENANT, "oid-student"): STUDENT_ID}


def test_a_linked_account_is_found_by_oid_even_if_the_name_changes(client: TestClient, sso_route):
    FakeMappings.links[(TENANT, "oid-student")] = STUDENT_ID
    sso_route(EntraIdentity(TENANT, "oid-student", "renamed@clip736.onmicrosoft.com"))
    assert _post(client).json()["role"] == "student"


def test_a_microsoft_account_without_a_clip_account_is_refused(client: TestClient, sso_route):
    sso_route(EntraIdentity(TENANT, "oid-stranger", "stranger@clip736.onmicrosoft.com"))
    response = _post(client)
    assert response.status_code == 403
    assert "no C.L.I.P account" in response.json()["error"]["message"]
    assert FakeMappings.links == {}
