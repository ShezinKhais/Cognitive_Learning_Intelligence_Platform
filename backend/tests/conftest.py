import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.deps import Principal, get_principal
from app.auth.store import (
    ADMIN_ID,
    LECTURER_ID,
    get_consent_repository,
    get_login_security_store,
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
    """Keep temporary authentication state isolated between tests."""

    settings = get_settings()

    get_login_security_store().reset()
    get_consent_repository(settings).clear()

    yield

    get_login_security_store().reset()
    get_consent_repository(settings).clear()


@pytest.fixture
def as_lecturer(app: FastAPI):
    """Authenticated lecturer with required terms consent."""

    settings = get_settings()

    def _principal() -> Principal:
        return Principal(
            user_id=LECTURER_ID,
            role=Role.LECTURER,
            email="lecturer@clip.example.com",
        )

    get_consent_repository(settings).record(
        LECTURER_ID,
        ConsentType.TERMS,
        True,
    )

    app.dependency_overrides[get_principal] = _principal

    with TestClient(app) as test_client:
        yield test_client

    app.dependency_overrides.clear()


@pytest.fixture
def as_admin(app: FastAPI):
    """Authenticated administrator with required terms consent."""

    settings = get_settings()

    def _principal() -> Principal:
        return Principal(
            user_id=ADMIN_ID,
            role=Role.ADMIN,
            email="admin@clip.example.com",
        )

    get_consent_repository(settings).record(
        ADMIN_ID,
        ConsentType.TERMS,
        True,
    )

    app.dependency_overrides[get_principal] = _principal

    with TestClient(app) as test_client:
        yield test_client

    app.dependency_overrides.clear()


@pytest.fixture
def as_admin(app: FastAPI):
    """Same pattern as as_lecturer, for /admin routes which require Role.ADMIN."""

    def _principal() -> Principal:
        return Principal(
            user_id=UUID("22222222-2222-2222-2222-222222222222"),
            role=Role.ADMIN,
            email="admin@uni.test",
        )

    app.dependency_overrides[get_principal] = _principal
    with TestClient(app) as client:
        yield client
    app.dependency_overrides.clear()
