from uuid import UUID

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.deps import Principal, get_principal
from app.auth.store import get_consent_repository, get_user_repository
from app.core.config import get_settings
from app.main import create_app
from app.schemas.identity import ConsentType, Role


@pytest.fixture(scope="session")
def app() -> FastAPI:
    return create_app()


@pytest.fixture(scope="session")
def client(app: FastAPI) -> TestClient:
    return TestClient(app)


@pytest.fixture(autouse=True)
def reset_dev_identity_state():
    settings = get_settings()
    get_user_repository(settings).reset_security_state()
    get_consent_repository().clear()
    yield
    get_user_repository(settings).reset_security_state()
    get_consent_repository().clear()


@pytest.fixture
def as_lecturer(app: FastAPI):
    user_id = UUID("11111111-1111-1111-1111-111111111111")

    def _principal() -> Principal:
        return Principal(
            user_id=user_id,
            role=Role.LECTURER,
            email="lecturer@uni.test",
        )

    get_consent_repository().record(user_id, ConsentType.TERMS, True)
    app.dependency_overrides[get_principal] = _principal
    with TestClient(app) as client:
        yield client
    app.dependency_overrides.clear()


@pytest.fixture
def as_admin(app: FastAPI):
    user_id = UUID("22222222-2222-2222-2222-222222222222")

    def _principal() -> Principal:
        return Principal(
            user_id=user_id,
            role=Role.ADMIN,
            email="admin@uni.test",
        )

    get_consent_repository().record(user_id, ConsentType.TERMS, True)
    app.dependency_overrides[get_principal] = _principal
    with TestClient(app) as client:
        yield client
    app.dependency_overrides.clear()
