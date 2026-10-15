"""Session reports through the routes, against a real database.

Owner: General CS, Phase 7 (#65). The rules under test: only the lecturer who
runs a session, or an admin, can ask for its report or read it; anyone else is
told it does not exist; the report is built from what the session stored, and
says the same as /topics and /alerts; and the PDF is served only once ready.
"""

from __future__ import annotations

import asyncio
import threading
import time
from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest

from app.api.deps import get_principal
from app.auth.store import ADMIN_ID, LECTURER_ID, STUDENT_ID, get_consent_repository
from app.core.config import get_settings
from app.models.comprehension_result import ComprehensionResult
from app.models.student import Student
from app.models.student_response import StudentResponse
from app.models.user import User
from app.schemas.identity import Role
from app.services.reports import get_report_queue

from .session_support import add_course, add_lecturer, add_question, create_session, sign_in_as
from .test_alert_routes import keep


@pytest.fixture(autouse=True)
def fresh_queue():  # noqa: ANN201
    """Each test gets its own report queue, as each gets its own app."""
    get_report_queue.cache_clear()
    yield
    get_report_queue.cache_clear()


@pytest.fixture
def lecturer_session(db, app):  # noqa: ANN201
    """A session run by the development lecturer, signed in as them."""

    async def make():  # noqa: ANN202
        client, factory, created = db
        course = await add_course(factory, created)
        sign_in_as(app, LECTURER_ID, Role.LECTURER)
        return course, create_session(client, course)

    return make


def reports_path(session_id: str) -> str:
    return f"/api/v1/sessions/{session_id}/reports"


def wait_until_finished(client, report_id: str) -> dict:  # noqa: ANN001
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        body = client.get(f"/api/v1/reports/{report_id}").json()
        if body["status"] in ("ready", "failed"):
            return body
        time.sleep(0.02)
    raise AssertionError("the report never finished")


async def add_labelled_answer(db, course, session_id: UUID, label: str = "struggling") -> None:  # noqa: ANN001
    _, factory, created = db
    question_id = await add_question(db, course, LECTURER_ID, status="delivered")
    async with factory() as seed:
        user = User(name="Report Student", role="student", email=f"{uuid4().hex}@t.test")
        seed.add(user)
        await seed.flush()
        created["user"].append(user.user_id)
        student = Student(
            user_id=user.user_id,
            course_id=course.id,
            consent_status="granted",
            enrolled_at=datetime.now(UTC).date(),
        )
        seed.add(student)
        await seed.flush()
        response = StudentResponse(
            session_id=session_id,
            student_id=student.student_id,
            question_id=question_id,
            selected_option=1,
        )
        seed.add(response)
        await seed.flush()
        seed.add(
            ComprehensionResult(
                response_id=response.response_id,
                label=label,
                confidence_score=1.0,
                score=0.0,
                ai_feedback_text="",
            )
        )
        await seed.commit()


# -- asking and reading -----------------------------------------------------------


async def test_a_report_is_accepted_at_once_and_ready_soon_after(db, lecturer_session) -> None:
    client, factory, _ = db
    course, session = await lecturer_session()
    await add_labelled_answer(db, course, UUID(session["id"]))
    await keep(factory, session["id"])

    asked = client.post(reports_path(session["id"]))

    assert asked.status_code == 202, asked.text
    assert asked.headers["cache-control"] == "no-store"
    assert asked.json()["status"] in ("queued", "running", "ready")
    assert asked.json()["session_id"] == session["id"]
    done = wait_until_finished(client, asked.json()["report_id"])
    assert done["status"] == "ready", done
    report = done["report"]
    assert (report["course_code"], report["title"]) == (course.code, "Week 1")
    assert report["participation"]["answers"] == 1
    # The same figures the lecturer's other views show, so the two never disagree.
    assert report["topics"] == client.get(f"/api/v1/sessions/{session['id']}/topics").json()
    assert report["alerts"] == client.get(f"/api/v1/sessions/{session['id']}/alerts").json()


async def test_the_pdf_is_served_once_the_report_is_ready(db, lecturer_session) -> None:
    client, _, _ = db
    _, session = await lecturer_session()
    report_id = client.post(reports_path(session["id"])).json()["report_id"]
    wait_until_finished(client, report_id)

    pdf = client.get(f"/api/v1/reports/{report_id}/pdf")

    assert pdf.status_code == 200
    assert pdf.headers["content-type"] == "application/pdf"
    assert pdf.headers["cache-control"] == "no-store"
    assert pdf.headers["content-disposition"].startswith(
        'attachment; filename="clip-session-report-'
    )
    assert pdf.content.startswith(b"%PDF")


async def test_the_pdf_is_refused_until_the_report_is_ready(db, lecturer_session) -> None:
    client, _, _ = db
    _, session = await lecturer_session()
    queue = get_report_queue()
    building = queue._builder  # noqa: SLF001
    # The app runs on the test client's own thread, so the gate is a thread's.
    gate = threading.Event()

    class Held:
        async def build(self, session_id):  # noqa: ANN001, ANN202
            await asyncio.to_thread(gate.wait, 10)
            return await building.build(session_id)

    queue._builder = Held()  # noqa: SLF001
    report_id = client.post(reports_path(session["id"])).json()["report_id"]

    early = client.get(f"/api/v1/reports/{report_id}/pdf")
    gate.set()

    assert early.status_code == 409
    assert early.json()["error"]["detail"]["status"] in ("queued", "running")
    assert wait_until_finished(client, report_id)["status"] == "ready"
    assert client.get(f"/api/v1/reports/{report_id}/pdf").status_code == 200


async def test_an_admin_may_ask_for_and_read_any_lecturers_report(
    db, app, lecturer_session
) -> None:
    client, _, _ = db
    _, session = await lecturer_session()
    report_id = client.post(reports_path(session["id"])).json()["report_id"]

    sign_in_as(app, ADMIN_ID, Role.ADMIN)

    assert wait_until_finished(client, report_id)["status"] == "ready"
    assert client.post(reports_path(session["id"])).status_code == 202


# -- who may not --------------------------------------------------------------------


async def test_another_lecturer_is_told_neither_session_nor_report_exists(
    db, app, lecturer_session
) -> None:
    client, factory, created = db
    _, session = await lecturer_session()
    report_id = client.post(reports_path(session["id"])).json()["report_id"]
    wait_until_finished(client, report_id)
    sign_in_as(app, await add_lecturer(factory, created), Role.LECTURER)

    asking = client.post(reports_path(session["id"]))
    reading = client.get(f"/api/v1/reports/{report_id}")
    downloading = client.get(f"/api/v1/reports/{report_id}/pdf")
    missing = client.get(f"/api/v1/reports/{uuid4()}")

    assert asking.status_code == reading.status_code == downloading.status_code == 404
    # A real report id answers exactly as a made-up one, so ids cannot be probed.
    assert reading.json()["error"]["message"] == missing.json()["error"]["message"]
    assert "session_id" not in str(reading.json())


async def test_a_student_cannot_ask_for_or_read_a_report(db, app, lecturer_session) -> None:
    client, _, _ = db
    _, session = await lecturer_session()
    report_id = client.post(reports_path(session["id"])).json()["report_id"]
    sign_in_as(app, STUDENT_ID, Role.STUDENT)

    assert client.post(reports_path(session["id"])).status_code == 403
    assert client.get(f"/api/v1/reports/{report_id}").status_code == 403
    assert client.get(f"/api/v1/reports/{report_id}/pdf").status_code == 403


async def test_nobody_signed_out_can_ask_or_read(db, app, lecturer_session) -> None:
    client, _, _ = db
    _, session = await lecturer_session()
    report_id = client.post(reports_path(session["id"])).json()["report_id"]
    app.dependency_overrides.pop(get_principal, None)

    assert client.post(reports_path(session["id"])).status_code == 401
    assert client.get(f"/api/v1/reports/{report_id}").status_code == 401


async def test_a_lecturer_without_terms_consent_is_refused(db, lecturer_session) -> None:
    client, _, _ = db
    _, session = await lecturer_session()
    get_consent_repository(get_settings()).clear()

    assert client.post(reports_path(session["id"])).status_code == 403


async def test_a_report_for_a_session_that_does_not_exist_is_refused(db, lecturer_session) -> None:
    client, _, _ = db
    await lecturer_session()

    assert client.post(reports_path(str(uuid4()))).status_code == 404
