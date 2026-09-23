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
from app.core.database import get_engine
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


@pytest.fixture(autouse=True)
def forget_pooled_connections():
    """Drop the app engine's pooled connections after every test.

    A TestClient used without `with` runs each request on an event loop of its
    own that closes afterwards, and a connection the request left in the pool
    is tied to that loop. The next request to be handed it failed on "Event
    loop is closed" and the readiness check reported 503, depending on garbage
    collection timing. A server has one loop for its lifetime, so this is a
    property of the tests, not of the app. close=False forgets the connections
    without trying to close them on a loop that no longer exists.
    """
    yield
    if get_engine.cache_info().currsize:
        get_engine().sync_engine.dispose(close=False)


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
