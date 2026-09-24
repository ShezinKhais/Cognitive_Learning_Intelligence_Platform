"""The pre-session content-readiness gate.

Owner: AI 1, Phase 4. The first half checks the rules with no database. The
second half checks the endpoint and the start button against a real one.
"""

from __future__ import annotations

from uuid import UUID, uuid4

from app.auth.store import ADMIN_ID, LECTURER_ID, STUDENT_ID
from app.models.course import Course
from app.models.material import Material
from app.schemas.identity import Role
from app.services.session_readiness import assess

from .test_session_lifecycle import _as, _course, _create, _lecturer, _question, db  # noqa: F401

# -- the rules, no database --------------------------------------------------


def _file(status: str, name: str = "week1.pdf") -> Material:
    return Material(id=uuid4(), filename=name, status=status)


def _codes(issues) -> list[str]:
    return [issue.code.value for issue in issues]


def test_nothing_uploaded_is_not_ready() -> None:
    report = assess(uuid4(), [], 0)

    assert report.ready is False
    assert _codes(report.blockers) == ["no_material", "no_approved_questions"]


def test_material_still_processing_blocks_the_start() -> None:
    pending, processing = _file("pending", "a.pdf"), _file("processing", "b.pdf")

    report = assess(uuid4(), [_file("completed"), pending, processing], 3)

    assert report.ready is False
    assert _codes(report.blockers) == ["material_processing", "material_processing"]
    assert [b.material_id for b in report.blockers] == [pending.id, processing.id]
    assert "a.pdf" in report.blockers[0].message
    assert report.materials_processing == 2


def test_a_failed_material_is_a_warning_not_a_blocker() -> None:
    failed = _file("failed", "broken.pdf")

    report = assess(uuid4(), [_file("completed"), failed], 2)

    assert report.ready is True
    assert report.blockers == []
    assert _codes(report.warnings) == ["material_failed"]
    assert report.warnings[0].material_id == failed.id
    assert report.materials_failed == 1


def test_processed_material_without_approved_questions_is_not_ready() -> None:
    report = assess(uuid4(), [_file("completed")], 0)

    assert report.ready is False
    assert _codes(report.blockers) == ["no_approved_questions"]


def test_processed_material_and_a_staged_question_is_ready() -> None:
    report = assess(uuid4(), [_file("completed")], 1)

    assert report.ready is True
    assert (report.materials_total, report.deliverable_questions) == (1, 1)


# -- the endpoint and the start button, against a real database --------------


async def _material(db, course: Course, status: str, uploaded_by: UUID = LECTURER_ID) -> UUID:  # noqa: F811
    """A material with no questions, in whatever processing state."""
    _, factory, created = db
    async with factory() as seed:
        material = Material(
            course_id=course.id,
            filename=f"{status}.pdf",
            content_type="application/pdf",
            size_bytes=10,
            status=status,
            uploaded_by_user_id=uploaded_by,
        )
        seed.add(material)
        await seed.commit()
    created["material"].append(material.id)
    return material.id


async def test_a_session_with_a_staged_question_reports_ready(db, app) -> None:  # noqa: F811
    client, factory, created = db
    course = await _course(factory, created)
    await _question(db, course, LECTURER_ID)
    _as(app, LECTURER_ID, Role.LECTURER)
    session = _create(client, course)

    response = client.get(f"/api/v1/sessions/{session['id']}/readiness")

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["ready"] is True
    assert body["blockers"] == []
    assert body["deliverable_questions"] == 1


async def test_processing_material_refuses_the_start_and_says_why(db, app) -> None:  # noqa: F811
    client, factory, created = db
    course = await _course(factory, created)
    await _question(db, course, LECTURER_ID)
    processing = await _material(db, course, "processing")
    _as(app, LECTURER_ID, Role.LECTURER)
    session = _create(client, course)

    readiness = client.get(f"/api/v1/sessions/{session['id']}/readiness").json()
    start = client.post(f"/api/v1/sessions/{session['id']}/start")

    assert readiness["ready"] is False
    assert start.status_code == 409
    blockers = start.json()["error"]["detail"]["blockers"]
    assert [b["code"] for b in blockers] == ["material_processing"]
    assert blockers[0]["material_id"] == str(processing)
    # The same blockers on both, so the page and the button agree.
    assert blockers == readiness["blockers"]
    # A refused start leaves the session prepared: ending it now cancels it,
    # which only happens to a session that never started.
    ended = client.post(f"/api/v1/sessions/{session['id']}/end")
    assert ended.json()["status"] == "cancelled"


async def test_a_failed_material_does_not_hold_back_the_class(db, app) -> None:  # noqa: F811
    client, factory, created = db
    course = await _course(factory, created)
    await _question(db, course, LECTURER_ID)
    await _material(db, course, "failed")
    _as(app, LECTURER_ID, Role.LECTURER)
    session = _create(client, course)

    readiness = client.get(f"/api/v1/sessions/{session['id']}/readiness").json()
    start = client.post(f"/api/v1/sessions/{session['id']}/start")

    assert [w["code"] for w in readiness["warnings"]] == ["material_failed"]
    assert start.status_code == 200, start.text
    assert start.json()["status"] == "active"
    client.post(f"/api/v1/sessions/{session['id']}/end")


async def test_another_lecturers_material_does_not_block(db, app) -> None:  # noqa: F811
    client, factory, created = db
    course = await _course(factory, created)
    other = await _lecturer(factory, created)
    await _question(db, course, LECTURER_ID)
    await _material(db, course, "processing", uploaded_by=other)
    _as(app, LECTURER_ID, Role.LECTURER)
    session = _create(client, course)

    body = client.get(f"/api/v1/sessions/{session['id']}/readiness").json()

    assert body["ready"] is True
    assert body["materials_total"] == 1


async def test_only_the_sessions_lecturer_or_an_admin_may_check_readiness(db, app) -> None:  # noqa: F811
    client, factory, created = db
    course = await _course(factory, created)
    other = await _lecturer(factory, created)
    _as(app, LECTURER_ID, Role.LECTURER)
    session = _create(client, course)
    url = f"/api/v1/sessions/{session['id']}/readiness"

    _as(app, other, Role.LECTURER)
    assert client.get(url).status_code == 404
    _as(app, STUDENT_ID, Role.STUDENT)
    assert client.get(url).status_code == 403
    _as(app, ADMIN_ID, Role.ADMIN)
    assert client.get(url).status_code == 200
