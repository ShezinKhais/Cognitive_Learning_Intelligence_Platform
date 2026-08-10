import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.deps import Principal, get_principal
from app.auth.store import (
    ADMIN_ID,
    LECTURER_ID,
    get_consent_repository,
    get_user_repository,
)
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
    def _principal() -> Principal:
        return Principal(
            user_id=LECTURER_ID,
            role=Role.LECTURER,
            email="lecturer@clip.example.com",
        )

    get_consent_repository().record(
        LECTURER_ID,
        ConsentType.TERMS,
        True,
    )

    app.dependency_overrides[get_principal] = _principal

    with TestClient(app) as client:
        yield client

    app.dependency_overrides.clear()


@pytest.fixture
def as_admin(app: FastAPI):
    def _principal() -> Principal:
        return Principal(
            user_id=ADMIN_ID,
            role=Role.ADMIN,
            email="admin@clip.example.com",
        )

    get_consent_repository().record(
        ADMIN_ID,
        ConsentType.TERMS,
        True,
    )

    app.dependency_overrides[get_principal] = _principal

    with TestClient(app) as client:
        yield client

    app.dependency_overrides.clear()
