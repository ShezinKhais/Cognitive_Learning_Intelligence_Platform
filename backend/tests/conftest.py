import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.deps import Principal, get_principal
from app.auth.store import (
    ADMIN_ID,
    LECTURER_ID,
    STUDENT_ID,
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
def client(app: FastAPI):
    """Keep one AnyIO portal and event loop for the shared async DB engine.

    Using TestClient outside its context manager creates a fresh portal for
    each request.  The cached SQLAlchemy engine can then return an asyncpg
    connection that belongs to a portal which has already closed, making the
    readiness check intermittently report 503 in CI.
    """
    with TestClient(app) as test_client:
        yield test_client


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
def as_student(app: FastAPI):
    """Authenticated student with required terms consent."""

    settings = get_settings()

    def _principal() -> Principal:
        return Principal(
            user_id=STUDENT_ID,
            role=Role.STUDENT,
            email="student@clip.example.com",
        )

    get_consent_repository(settings).record(
        STUDENT_ID,
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
