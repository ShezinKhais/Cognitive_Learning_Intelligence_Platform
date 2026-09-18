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

from app import main as main_module
from app.auth.store import LECTURER_ID
from app.core.config import Settings
from app.main import lifespan
from app.schemas.content import MaterialStatus
from app.schemas.events import MaterialStage
from app.services import uploads as uploads_module
from app.services.jobs import BackgroundProcessor
from app.services.pipeline import MaterialPipeline
from app.services.storage import LocalDiskStorage
from app.services.uploads import get_background_processor, material_extensions

from .dev_credentials import LECTURER_PASSWORD, STUDENT_PASSWORD
from .pipeline_support import Embedder, Generator, ProgressLog

LECTURE_NOTES = ("Third normal form removes transitive dependencies. " * 40).encode()

# Long enough that the parse is over well before this, short enough that a
# genuine hang fails the run rather than stalling it.
PROCESSING_TIMEOUT_SECONDS = 10.0


def login(
    client: TestClient, email: str, password: str, *, accept_terms: bool = True
) -> dict[str, str]:
    response = client.post("/api/v1/auth/login", json={"email": email, "password": password})
    assert response.status_code == 200
    headers = {"Authorization": f"Bearer {response.json()['access_token']}"}
    if accept_terms:
        consent = client.post(
            "/api/v1/auth/consent",
            headers=headers,
            json={"consent_type": "terms", "granted": True},
        )
        assert consent.status_code == 201
    return headers


def upload(client: TestClient, headers: dict[str, str], name: str, data: bytes):
    return client.post(
        "/api/v1/materials",
        headers=headers,
        files={"file": (name, data, "application/octet-stream")},
    )


def await_terminal_state(progress: ProgressLog, material_id: str) -> dict:
    """Block until the lecturer has been told the job ended, and return that frame."""
    deadline = time.monotonic() + PROCESSING_TIMEOUT_SECONDS
    while time.monotonic() < deadline:
        frames = [f for f in progress.frames if f["material_id"] == material_id]
        if frames and frames[-1]["stage"] in (MaterialStage.DONE, MaterialStage.FAILED):
            return frames[-1]
        time.sleep(0.05)
    pytest.fail(f"material {material_id} never reached a terminal state")


@pytest.fixture
def live_client(app: FastAPI, uploads):
    """A client whose event loop stays up between calls.

    Depends on uploads so it is torn down first. The other order undid the
    patched processor before the client shut down, and the lifespan drained
    the real singleton instead of the jobs these tests submitted.
    """
    with TestClient(app) as running:
        yield running


@pytest.fixture
def uploads(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> ProgressLog:
    """Point the upload path at a throwaway storage root and a fresh processor.

    Returns the hub the pipeline reports to, which records what the lecturer
    was told. The embedder and generator are the AI 1 fakes, since the model
    server is not part of what these tests are about.
    """
    # allowed_upload_extensions is left at the shipped default, spreadsheets
    # included, so the narrowing the route relies on is actually exercised.
    settings = Settings(_env_file=None, upload_storage_dir=str(tmp_path))
    storage = LocalDiskStorage(settings, allowed=material_extensions(settings))
    progress = ProgressLog()
    pipeline = MaterialPipeline(
        storage=storage,
        settings=settings,
        embedder=Embedder(dim=settings.embedding_dim),
        generator=Generator(),
        hub=progress,
    )
    processor = BackgroundProcessor(max_concurrent=2)

    monkeypatch.setattr(uploads_module, "get_material_storage", lambda: storage)
    monkeypatch.setattr(uploads_module, "get_material_pipeline", lambda: pipeline)
    monkeypatch.setattr(uploads_module, "get_background_processor", lambda: processor)
    # Shutdown drains through its own reference. Patched only in the upload
    # path, the lifespan drained the real singleton and this processor never.
    monkeypatch.setattr(main_module, "get_background_processor", lambda: processor)
    return progress


def test_a_student_cannot_upload_lecture_material(live_client: TestClient, uploads) -> None:
    headers = login(live_client, "student@clip.example.com", STUDENT_PASSWORD)

    response = upload(live_client, headers, "notes.txt", LECTURE_NOTES)

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "FORBIDDEN"


def test_a_lecturer_who_has_not_accepted_the_terms_cannot_upload(
    live_client: TestClient, uploads
) -> None:
    """The consent page is the frontend's courtesy; the gate is here."""
    headers = login(live_client, "lecturer@clip.example.com", LECTURER_PASSWORD, accept_terms=False)

    response = upload(live_client, headers, "notes.txt", LECTURE_NOTES)

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "CONSENT_REQUIRED"


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
    live_client: TestClient, uploads: ProgressLog, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The 202 promises work that is already on its way, for whoever uploaded."""
    processor = uploads_module.get_background_processor()
    submitted: list = []
    real_submit = processor.submit

    def submit(job):
        submitted.append(job.material_id)
        return real_submit(job)

    monkeypatch.setattr(processor, "submit", submit)
    headers = login(live_client, "lecturer@clip.example.com", LECTURER_PASSWORD)

    material_id = upload(live_client, headers, "notes.txt", LECTURE_NOTES).json()["id"]

    assert submitted == [UUID(material_id)]
    await_terminal_state(uploads, material_id)
    # Progress goes to the channel of whoever uploaded, not anyone else's.
    assert uploads.recipients == {LECTURER_ID}


def test_the_upload_is_processed_after_the_response(live_client: TestClient, uploads) -> None:
    headers = login(live_client, "lecturer@clip.example.com", LECTURER_PASSWORD)

    material_id = upload(live_client, headers, "notes.txt", LECTURE_NOTES).json()["id"]

    assert await_terminal_state(uploads, material_id)["stage"] == MaterialStage.DONE


def test_a_fake_pdf_is_rejected_before_background_processing(
    live_client: TestClient, uploads
) -> None:
    """A file renamed to PDF must fail before it reaches the parser."""
    headers = login(live_client, "lecturer@clip.example.com", LECTURER_PASSWORD)

    response = upload(
        live_client,
        headers,
        "broken.pdf",
        b"this is not a PDF",
    )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"


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


async def test_shutdown_waits_for_a_job_that_is_still_running(
    app: FastAPI, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A deploy that does not wait kills a parse halfway, and the lecturer is
    left watching a bar stuck at twenty per cent with no record of why."""
    processor = get_background_processor()
    drained_with: list[int] = []
    real_drain = processor.drain

    async def drain(*args, **kwargs) -> None:
        # Recorded, so a startup slower than the job cannot pass this vacuously.
        drained_with.append(processor.in_flight)
        await real_drain(*args, **kwargs)

    monkeypatch.setattr(processor, "drain", drain)
    running = asyncio.Event()

    class Slow:
        material_id = uuid4()

        async def run(self) -> None:
            running.set()
            await asyncio.sleep(0.2)

        async def abandon(self) -> None:
            raise AssertionError("a job that finishes in the grace period is not abandoned")

    processor.submit(Slow())
    await running.wait()
    assert processor.in_flight == 1

    async with lifespan(app):
        pass

    assert drained_with == [1]
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


def test_a_job_limit_of_zero_is_refused_at_startup() -> None:
    """Zero queued every upload forever; a negative limit made each one a 500."""
    from pydantic import ValidationError as SettingsError

    with pytest.raises(SettingsError):
        Settings(_env_file=None, max_concurrent_material_jobs=0)


def test_the_shown_filename_is_the_stored_one_not_the_raw_client_value(
    live_client: TestClient, uploads
) -> None:
    headers = login(live_client, "lecturer@clip.example.com", LECTURER_PASSWORD)

    response = upload(live_client, headers, "C:\\Users\\bob\\notes.txt", LECTURE_NOTES)

    assert response.json()["filename"] == "notes.txt"


def test_the_reported_type_comes_from_the_extension_not_a_generic_client_header(
    live_client: TestClient, uploads
) -> None:
    headers = login(live_client, "lecturer@clip.example.com", LECTURER_PASSWORD)

    response = live_client.post(
        "/api/v1/materials",
        headers=headers,
        files={"file": ("notes.txt", LECTURE_NOTES, "application/octet-stream")},
    )

    assert response.status_code == 202
    assert response.json()["content_type"] == "text/plain"


def test_a_specific_mismatched_client_mime_is_rejected(live_client: TestClient, uploads) -> None:
    headers = login(live_client, "lecturer@clip.example.com", LECTURER_PASSWORD)

    response = live_client.post(
        "/api/v1/materials",
        headers=headers,
        files={"file": ("notes.txt", LECTURE_NOTES, "text/html")},
    )

    assert response.status_code == 422


def test_the_real_wiring_uses_the_configured_limits() -> None:
    """Every other test replaces these singletons, so check what they build."""
    from app.core.config import get_settings
    from app.services.uploads import get_material_storage

    settings = get_settings()

    assert get_background_processor()._max_concurrent == settings.max_concurrent_material_jobs
    assert get_material_storage()._allowed == material_extensions(settings)
