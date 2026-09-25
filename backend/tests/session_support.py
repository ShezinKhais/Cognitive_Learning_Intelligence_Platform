"""The database fixture and builders shared by the session tests.

conftest.py registers this module as a plugin, so the db fixture needs no
import.
"""

from __future__ import annotations

from datetime import date
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.api.deps import Principal, get_principal
from app.auth.store import (
    STUDENT_ID,
    dev_user_records,
    get_consent_repository,
)
from app.core.config import get_settings
from app.core.database import get_db
from app.models.course import Course
from app.models.material import Material
from app.models.question import Question
from app.models.session import Session as SessionModel
from app.models.student import Student
from app.models.student_response import StudentResponse
from app.models.user import User
from app.schemas.identity import ConsentType, Role

from .database_support import require_database


@pytest.fixture
async def db(app):
    """A TestClient and a session factory sharing one engine with get_db."""
    require_database()
    engine = create_async_engine(get_settings().database_url, poolclass=NullPool)
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async def _get_db():
        async with factory() as session:
            try:
                yield session
                await session.commit()
            except Exception:
                await session.rollback()
                raise

    async with factory() as seed:
        # The development accounts sign in from memory but own rows by id.
        await seed.execute(
            insert(User)
            .values(
                [
                    {
                        "user_id": r.id,
                        "name": r.full_name,
                        "email": r.email,
                        "role": r.role.value,
                        "password_hash": r.password_hash,
                    }
                    for r in dev_user_records()
                ]
            )
            .on_conflict_do_nothing()
        )
        await seed.commit()

    app.dependency_overrides[get_db] = _get_db
    created: dict[str, list[UUID]] = {"course": [], "material": [], "user": []}
    with TestClient(app) as client:
        yield client, factory, created
    app.dependency_overrides.clear()

    async with factory() as cleanup:
        courses, materials = created["course"], created["material"]
        await cleanup.execute(
            delete(StudentResponse).where(
                StudentResponse.question_id.in_(
                    select(Question.question_id).where(Question.source_material_id.in_(materials))
                )
            )
        )
        await cleanup.execute(delete(Question).where(Question.source_material_id.in_(materials)))
        await cleanup.execute(delete(SessionModel).where(SessionModel.course_id.in_(courses)))
        await cleanup.execute(delete(Material).where(Material.id.in_(materials)))
        await cleanup.execute(delete(Student).where(Student.course_id.in_(courses)))
        await cleanup.execute(delete(Course).where(Course.id.in_(courses)))
        await cleanup.execute(delete(User).where(User.user_id.in_(created["user"])))
        await cleanup.commit()
    await engine.dispose()


def sign_in_as(app, user_id: UUID, role: Role) -> None:
    app.dependency_overrides[get_principal] = lambda: Principal(
        user_id=user_id, role=role, email=f"{role.value}@clip.example.com"
    )
    get_consent_repository(get_settings()).record(user_id, ConsentType.TERMS, True)


async def add_course(factory, created) -> Course:
    async with factory() as seed:
        course = Course(code=f"T{uuid4().hex[:8]}", name="Live Test Course")
        seed.add(course)
        await seed.commit()
    created["course"].append(course.id)
    return course


async def add_lecturer(factory, created) -> UUID:
    user_id = uuid4()
    async with factory() as seed:
        seed.add(
            User(user_id=user_id, name="Other", role="lecturer", email=f"{user_id.hex}@t.test")
        )
        await seed.commit()
    created["user"].append(user_id)
    return user_id


async def add_question(
    db,
    course: Course,
    uploaded_by: UUID,
    status: str = "staged",
    course_id: bool = True,
    question_type: str = "mcq",
    options: list[str] | None = None,
) -> UUID:
    _, factory, created = db
    async with factory() as seed:
        material = Material(
            course_id=course.id if course_id else None,
            filename="week1.pdf",
            content_type="application/pdf",
            size_bytes=10,
            status="completed",
            uploaded_by_user_id=uploaded_by,
        )
        seed.add(material)
        await seed.flush()
        question = Question(
            source_material_id=material.id,
            question_text="Which planet is largest?",
            question_type=question_type,
            status=status,
            options=["Mars", "Jupiter", "Venus"] if options is None else options,
            correct_option=1,
            source_slide=3,
        )
        seed.add(question)
        await seed.commit()
    created["material"].append(material.id)
    return question.question_id


async def enrol(factory, course: Course, user_id: UUID = STUDENT_ID) -> None:
    """Move the student onto this course. An upsert, because startup enrols
    the development student on the development course at the same time."""
    async with factory() as seed:
        await seed.execute(
            insert(Student)
            .values(
                user_id=user_id,
                course_id=course.id,
                consent_status="granted",
                enrolled_at=date(2026, 9, 1),
            )
            .on_conflict_do_update(index_elements=[Student.user_id], set_={"course_id": course.id})
        )
        await seed.commit()


def create_session(client: TestClient, course: Course, title: str = "Week 1") -> dict:
    response = client.post("/api/v1/sessions", json={"course_code": course.code, "title": title})
    assert response.status_code == 201, response.text
    return response.json()


def token_for(client: TestClient, email: str, password: str) -> str:
    response = client.post("/api/v1/auth/login", json={"email": email, "password": password})
    return response.json()["access_token"]
