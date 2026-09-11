"""The upload route, end to end over HTTP.

Owner: General CS, Phase 2.

Storage is redirected at a temporary directory for these, because the route
otherwise writes into the real upload root and the point of the test is the
route, not where the bytes landed. Everything else is the running application:
real tokens, the real role guard, the real pipeline.

The client is entered as a context manager rather than shared, because the
whole point of a 202 is that the work outlives the request. A TestClient that
is not entered runs an event loop only for the duration of one call, so the
background job would be abandoned the moment the response came back and the
tests below would be asserting against a pipeline that never ran.
"""

from __future__ import annotations

import asyncio
import time
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.v1 import content
from app.core.config import Settings
from app.main import lifespan
from app.realtime.hub import SessionHub
from app.schemas.content import MaterialStatus
from app.schemas.events import MaterialStage
from app.services.jobs import BackgroundProcessor, JobRegistry
from app.services.pipeline import MaterialPipeline
from app.services.storage import LocalDiskStorage
from app.services.uploads import get_background_processor, material_extensions

from .dev_credentials import LECTURER_PASSWORD, STUDENT_PASSWORD

LECTURE_NOTES = ("Third normal form removes transitive dependencies. " * 40).encode()

# Long enough that the parse is over well before this, short enough that a
# genuine hang fails the run rather than stalling it.
PROCESSING_TIMEOUT_SECONDS = 10.0


def login(client: TestClient, email: str, password: str) -> dict[str, str]:
    response = client.post("/api/v1/auth/login", json={"email": email, "password": password})
    assert response.status_code == 200
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


def upload(client: TestClient, headers: dict[str, str], name: str, data: bytes):
    return client.post(
        "/api/v1/materials",
        headers=headers,
        files={"file": (name, data, "application/octet-stream")},
    )


def await_terminal_state(registry: JobRegistry, material_id: str):
    """Block until the background job reports an end state."""
    deadline = time.monotonic() + PROCESSING_TIMEOUT_SECONDS
    while time.monotonic() < deadline:
        status = registry.get(UUID(material_id))
        if status is not None and status.is_finished:
            return status
        time.sleep(0.05)
    pytest.fail(f"material {material_id} never reached a terminal state")


@pytest.fixture
def live_client(app: FastAPI):
    """A client whose event loop stays up between calls."""
    with TestClient(app) as running:
        yield running


@pytest.fixture
def uploads(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    """Point the route at a throwaway storage root and a fresh registry."""
    # allowed_upload_extensions is left at the shipped default, spreadsheets
    # included, so the narrowing the route relies on is actually exercised.
    settings = Settings(_env_file=None, upload_storage_dir=str(tmp_path))
    storage = LocalDiskStorage(settings, allowed=material_extensions(settings))
    registry = JobRegistry()
    pipeline = MaterialPipeline(
        storage=storage,
        registry=registry,
        settings=settings,
        hub=SessionHub(),
    )

    # The processor is replaced along with the registry: submit() records the
    # queued state, so a processor built on the real singleton would write the
    # status somewhere this test cannot see.
    processor = BackgroundProcessor(registry, max_concurrent=2)

    monkeypatch.setattr(content, "get_material_storage", lambda: storage)
    monkeypatch.setattr(content, "get_material_pipeline", lambda: pipeline)
    monkeypatch.setattr(content, "get_background_processor", lambda: processor)
    return registry


def test_a_student_cannot_upload_lecture_material(live_client: TestClient, uploads) -> None:
    headers = login(live_client, "student@clip.example.com", STUDENT_PASSWORD)

    response = upload(live_client, headers, "notes.txt", LECTURE_NOTES)

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "FORBIDDEN"


def test_an_upload_without_a_token_is_refused(live_client: TestClient, uploads) -> None:
    response = live_client.post(
        "/api/v1/materials",
        files={"file": ("notes.txt", LECTURE_NOTES, "text/plain")},
    )

    assert response.status_code == 401


def test_a_lecturer_upload_is_accepted_without_waiting_for_the_parse(
    live_client: TestClient, uploads
) -> None:
    headers = login(live_client, "lecturer@clip.example.com", LECTURER_PASSWORD)

    response = upload(live_client, headers, "Week 3 Notes.txt", LECTURE_NOTES)

    assert response.status_code == 202
    body = response.json()
    assert body["status"] == MaterialStatus.PENDING
    assert body["filename"] == "Week 3 Notes.txt"
    assert body["size_bytes"] == len(LECTURE_NOTES)
    # Nothing has run yet, so claiming a page or chunk count would be a guess.
    assert body["page_count"] is None
    assert body["chunk_count"] is None


def test_the_material_is_queued_before_the_response_is_returned(
    live_client: TestClient, uploads
) -> None:
    """A status read between the 202 and the worker must not report nothing."""
    headers = login(live_client, "lecturer@clip.example.com", LECTURER_PASSWORD)

    material_id = upload(live_client, headers, "notes.txt", LECTURE_NOTES).json()["id"]

    assert uploads.get(UUID(material_id)) is not None


def test_the_upload_is_processed_after_the_response(live_client: TestClient, uploads) -> None:
    headers = login(live_client, "lecturer@clip.example.com", LECTURER_PASSWORD)

    material_id = upload(live_client, headers, "notes.txt", LECTURE_NOTES).json()["id"]

    status = await_terminal_state(uploads, material_id)
    assert status.stage is MaterialStage.DONE
    assert status.status is MaterialStatus.COMPLETED


def test_an_unreadable_file_finishes_as_failed_rather_than_never(
    live_client: TestClient, uploads
) -> None:
    """The 202 already went out, so the only way to report this is the job."""
    headers = login(live_client, "lecturer@clip.example.com", LECTURER_PASSWORD)

    material_id = upload(live_client, headers, "broken.pdf", b"this is not a PDF").json()["id"]

    status = await_terminal_state(uploads, material_id)
    assert status.stage is MaterialStage.FAILED
    assert "could not be read" in status.message


@pytest.mark.parametrize("name", ["notes.exe", "notes.pdf.exe", "notes"])
def test_an_unsupported_format_is_refused_while_there_is_still_a_response(
    live_client: TestClient, uploads, name: str
) -> None:
    """Rejecting a format the parser cannot read is worth the wait for a 422;
    the lecturer learns now instead of watching a job fail a minute later."""
    headers = login(live_client, "lecturer@clip.example.com", LECTURER_PASSWORD)

    response = upload(live_client, headers, name, b"MZ")

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"


def test_an_empty_upload_is_refused(live_client: TestClient, uploads) -> None:
    headers = login(live_client, "lecturer@clip.example.com", LECTURER_PASSWORD)

    response = upload(live_client, headers, "notes.txt", b"")

    assert response.status_code == 422


async def test_shutdown_waits_for_a_job_that_is_still_running(app: FastAPI) -> None:
    """A deploy that does not wait kills a parse halfway, and the lecturer is
    left watching a bar stuck at twenty per cent with no record of why."""
    processor = get_background_processor()
    running = asyncio.Event()

    async def slow() -> None:
        running.set()
        await asyncio.sleep(0.2)

    processor.submit(uuid4(), slow)
    await running.wait()
    assert processor.in_flight == 1

    async with lifespan(app):
        pass

    assert processor.in_flight == 0


@pytest.mark.parametrize("name", ["grades.xlsx", "roster.csv"])
def test_a_spreadsheet_is_refused_rather_than_accepted_and_failed(
    live_client: TestClient, uploads, name: str
) -> None:
    """CSV and XLSX are in the shipped upload list for the administrator
    importers, and no lecture parser reads either. Accepting one here would
    answer 202 for a file that can only fail a minute later."""
    headers = login(live_client, "lecturer@clip.example.com", LECTURER_PASSWORD)

    response = live_client.post(
        "/api/v1/materials",
        headers=headers,
        files={"file": (name, b"a,b\n1,2\n", "text/csv")},
    )

    assert response.status_code == 422
    assert name.rsplit(".", 1)[1] in response.json()["error"]["message"]
