
"""Tests for lecture readiness and session starting.

Lectures may start without uploaded materials or approved questions.
Missing content produces warnings rather than blockers.
"""

from __future__ import annotations

from uuid import UUID, uuid4

from app.auth.store import ADMIN_ID, LECTURER_ID, STUDENT_ID
from app.models.course import Course
from app.models.material import Material
from app.schemas.identity import Role
from app.services.session_readiness import assess

from .session_support import (
    add_course,
    add_lecturer,
    add_question,
    create_session,
    sign_in_as,
)


# -- Readiness rules without a database ------------------------------------


def _file(status: str, name: str = "week1.pdf") -> Material:
    return Material(id=uuid4(), filename=name, status=status)


def _codes(issues) -> list[str]:
    return [issue.code.value for issue in issues]


def test_nothing_uploaded_allows_lecture_with_warnings() -> None:
    report = assess(uuid4(), [], 0)

    assert report.ready is True
    assert report.blockers == []
    assert _codes(report.warnings) == [
        "no_material",
        "no_approved_questions",
    ]


def test_no_material_is_a_warning_when_a_question_is_staged() -> None:
    report = assess(uuid4(), [], 1)

    assert report.ready is True
    assert report.blockers == []
    assert _codes(report.warnings) == ["no_material"]


def test_material_still_processing_is_a_warning_when_questions_are_staged() -> None:
    pending = _file("pending", "a.pdf")
    processing = _file("processing", "b.pdf")

    report = assess(
        uuid4(),
        [_file("completed"), pending, processing],
        3,
    )

    assert report.ready is True
    assert report.blockers == []
    assert _codes(report.warnings) == [
        "material_processing",
        "material_processing",
    ]
    assert [w.material_id for w in report.warnings] == [
        pending.id,
        processing.id,
    ]
    assert "a.pdf" in report.warnings[0].message
    assert report.materials_processing == 2


def test_material_still_processing_allows_lecture_with_warnings() -> None:
    processing = _file("processing", "b.pdf")

    report = assess(uuid4(), [processing], 0)

    assert report.ready is True
    assert report.blockers == []
    assert _codes(report.warnings) == [
        "material_processing",
        "no_approved_questions",
    ]
    assert report.warnings[0].material_id == processing.id


def test_a_failed_material_is_a_warning_not_a_blocker() -> None:
    failed = _file("failed", "broken.pdf")

    report = assess(uuid4(), [_file("completed"), failed], 2)

    assert report.ready is True
    assert report.blockers == []
    assert _codes(report.warnings) == ["material_failed"]
    assert report.warnings[0].material_id == failed.id
    assert report.materials_failed == 1


def test_processed_material_without_questions_allows_lecture() -> None:
    report = assess(uuid4(), [_file("completed")], 0)

    assert report.ready is True
    assert report.blockers == []
    assert _codes(report.warnings) == ["no_approved_questions"]


def test_processed_material_and_a_staged_question_is_ready() -> None:
    report = assess(uuid4(), [_file("completed")], 1)

    assert report.ready is True
    assert report.blockers == []
    assert (report.materials_total, report.deliverable_questions) == (1, 1)


# -- API and database integration tests ------------------------------------


async def _material(
    db,
    course: Course,
    status: str,
    uploaded_by: UUID = LECTURER_ID,
) -> UUID:
    """Create a material with no questions."""
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


async def test_a_session_with_a_staged_question_reports_ready(db, app) -> None:
    client, factory, created = db
    course = await add_course(factory, created)
    await add_question(db, course, LECTURER_ID)

    sign_in_as(app, LECTURER_ID, Role.LECTURER)
    session = create_session(client, course)

    response = client.get(
        f"/api/v1/sessions/{session['id']}/readiness"
    )

    assert response.status_code == 200, response.text

    body = response.json()

    assert body["ready"] is True
    assert body["blockers"] == []
    assert body["deliverable_questions"] == 1


async def test_processing_material_allows_start_with_warnings(db, app) -> None:
    client, factory, created = db
    course = await add_course(factory, created)
    processing = await _material(db, course, "processing")

    sign_in_as(app, LECTURER_ID, Role.LECTURER)
    session = create_session(client, course)

    readiness = client.get(
        f"/api/v1/sessions/{session['id']}/readiness"
    ).json()

    start = client.post(
        f"/api/v1/sessions/{session['id']}/start"
    )

    assert readiness["ready"] is True
    assert readiness["blockers"] == []
    assert readiness["deliverable_questions"] == 0

    warnings = readiness["warnings"]

    assert [w["code"] for w in warnings] == [
        "material_processing",
        "no_approved_questions",
    ]
    assert warnings[0]["material_id"] == str(processing)

    assert start.status_code == 200, start.text
    assert start.json()["status"] == "active"

    ended = client.post(
        f"/api/v1/sessions/{session['id']}/end"
    )
    assert ended.status_code == 200
    assert ended.json()["status"] == "ended"


async def test_processing_material_does_not_hold_back_a_class_with_questions(
    db, app
) -> None:
    client, factory, created = db
    course = await add_course(factory, created)

    await add_question(db, course, LECTURER_ID)
    await _material(db, course, "processing")

    sign_in_as(app, LECTURER_ID, Role.LECTURER)
    session = create_session(client, course)

    readiness = client.get(
        f"/api/v1/sessions/{session['id']}/readiness"
    ).json()

    start = client.post(
        f"/api/v1/sessions/{session['id']}/start"
    )

    assert readiness["ready"] is True
    assert [w["code"] for w in readiness["warnings"]] == [
        "material_processing"
    ]
    assert start.status_code == 200, start.text

    client.post(f"/api/v1/sessions/{session['id']}/end")


async def test_readiness_is_refused_once_the_session_has_started(
    db, app
) -> None:
    client, factory, created = db
    course = await add_course(factory, created)

    await add_question(db, course, LECTURER_ID)

    sign_in_as(app, LECTURER_ID, Role.LECTURER)
    session = create_session(client, course)

    start = client.post(
        f"/api/v1/sessions/{session['id']}/start"
    )
    assert start.status_code == 200

    response = client.get(
        f"/api/v1/sessions/{session['id']}/readiness"
    )

    assert response.status_code == 409

    client.post(f"/api/v1/sessions/{session['id']}/end")


async def test_a_failed_material_does_not_hold_back_the_class(
    db, app
) -> None:
    client, factory, created = db
    course = await add_course(factory, created)

    await add_question(db, course, LECTURER_ID)
    await _material(db, course, "failed")

    sign_in_as(app, LECTURER_ID, Role.LECTURER)
    session = create_session(client, course)

    readiness = client.get(
        f"/api/v1/sessions/{session['id']}/readiness"
    ).json()

    start = client.post(
        f"/api/v1/sessions/{session['id']}/start"
    )

    assert [w["code"] for w in readiness["warnings"]] == [
        "material_failed"
    ]
    assert start.status_code == 200, start.text
    assert start.json()["status"] == "active"

    client.post(f"/api/v1/sessions/{session['id']}/end")


async def test_another_lecturers_material_does_not_block(
    db, app
) -> None:
    client, factory, created = db
    course = await add_course(factory, created)

    other = await add_lecturer(factory, created)

    await add_question(db, course, LECTURER_ID)
    await _material(
        db,
        course,
        "processing",
        uploaded_by=other,
    )

    sign_in_as(app, LECTURER_ID, Role.LECTURER)
    session = create_session(client, course)

    body = client.get(
        f"/api/v1/sessions/{session['id']}/readiness"
    ).json()

    assert body["ready"] is True
    assert body["materials_total"] == 1


async def test_only_the_sessions_lecturer_or_an_admin_may_check_readiness(
    db, app
) -> None:
    client, factory, created = db
    course = await add_course(factory, created)
    other = await add_lecturer(factory, created)

    sign_in_as(app, LECTURER_ID, Role.LECTURER)
    session = create_session(client, course)

    url = f"/api/v1/sessions/{session['id']}/readiness"

    sign_in_as(app, other, Role.LECTURER)
    assert client.get(url).status_code == 404

    sign_in_as(app, STUDENT_ID, Role.STUDENT)
    assert client.get(url).status_code == 403

    sign_in_as(app, ADMIN_ID, Role.ADMIN)
    assert client.get(url).status_code == 200
