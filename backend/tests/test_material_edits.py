"""Renaming, re-filing and deleting a material (General CS, Phase 8)."""

from __future__ import annotations

from sqlalchemy import select, update

from app.auth.store import LECTURER_ID
from app.models.material import Material
from app.models.question import Question
from app.schemas.identity import Role

from .session_support import add_course, add_lecturer, add_question, sign_in_as


async def _material_of(factory, question_id):  # noqa: ANN001, ANN202
    async with factory() as session:
        return await session.scalar(
            select(Question.source_material_id).where(Question.question_id == question_id)
        )


async def test_a_material_is_renamed_and_filed_under_a_course(db, app) -> None:  # noqa: ANN001
    client, factory, created = db
    course = await add_course(factory, created)
    material = await _material_of(
        factory, await add_question(db, course, LECTURER_ID, course_id=False)
    )
    sign_in_as(app, LECTURER_ID, Role.LECTURER)

    response = client.patch(
        f"/api/v1/materials/{material}",
        json={"filename": "Week 1 slides", "course_code": course.code},
    )

    assert response.status_code == 200
    assert (response.json()["filename"], response.json()["course_code"]) == (
        "Week 1 slides",
        course.code,
    )
    cleared = client.patch(f"/api/v1/materials/{material}", json={"course_code": None})
    assert cleared.json()["course_code"] is None
    assert cleared.json()["filename"] == "Week 1 slides"


async def test_an_unused_material_is_deleted_with_its_questions(db, app) -> None:  # noqa: ANN001
    client, factory, created = db
    course = await add_course(factory, created)
    question = await add_question(db, course, LECTURER_ID, status="draft")
    material = await _material_of(factory, question)
    sign_in_as(app, LECTURER_ID, Role.LECTURER)

    assert client.delete(f"/api/v1/materials/{material}").status_code == 204
    async with factory() as session:
        assert await session.get(Material, material) is None
        assert await session.get(Question, question) is None


async def test_a_processing_material_cannot_be_deleted(db, app) -> None:  # noqa: ANN001
    client, factory, created = db
    course = await add_course(factory, created)
    material = await _material_of(factory, await add_question(db, course, LECTURER_ID))
    async with factory() as session:
        await session.execute(
            update(Material).where(Material.id == material).values(status="processing")
        )
        await session.commit()
    sign_in_as(app, LECTURER_ID, Role.LECTURER)

    assert client.delete(f"/api/v1/materials/{material}").status_code == 409


async def test_another_lecturers_material_is_missing(db, app) -> None:  # noqa: ANN001
    client, factory, created = db
    course = await add_course(factory, created)
    other = await add_lecturer(factory, created)
    material = await _material_of(factory, await add_question(db, course, other))
    sign_in_as(app, LECTURER_ID, Role.LECTURER)

    assert client.delete(f"/api/v1/materials/{material}").status_code == 404
    assert client.patch(f"/api/v1/materials/{material}", json={"filename": "x"}).status_code == 404
