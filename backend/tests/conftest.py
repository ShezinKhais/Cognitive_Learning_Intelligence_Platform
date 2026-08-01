from uuid import UUID

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.deps import Principal, get_principal
from app.main import create_app
from app.schemas.identity import Role


@pytest.fixture(scope="session")
def app() -> FastAPI:
    return create_app()


@pytest.fixture(scope="session")
def client(app: FastAPI) -> TestClient:
    return TestClient(app)


@pytest.fixture
def as_lecturer(app: FastAPI):
    """A client that is past the authentication gate.

    Auth is owned by Cyber 1 and is not implemented yet, so without this every
    route returns 401 and the handlers behind it are unreachable. Overriding the
    dependency lets routes be tested before auth lands, and is the pattern other
    workstreams should copy.
    """

    def _principal() -> Principal:
        return Principal(
            user_id=UUID("11111111-1111-1111-1111-111111111111"),
            role=Role.LECTURER,
            email="lecturer@uni.test",
        )

    app.dependency_overrides[get_principal] = _principal
    with TestClient(app) as client:
        yield client
    app.dependency_overrides.clear()
