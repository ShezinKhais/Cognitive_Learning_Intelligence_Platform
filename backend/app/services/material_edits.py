"""Renaming, re-filing and deleting a lecturer's material.

Owner: General CS, Phase 8, on the Phase 2 upload pipeline. A lecturer may
change their own material; an admin may change anyone's.

Deleting is refused while the material is still being processed, since the
pipeline is writing its rows, and once any of its questions has been
delivered in a class: the questions, the answers to them and the alerts
they raised are that class's history, and the report reads them. Otherwise
the material goes with everything drawn from it: its sections for the
tutor, its questions, what was read from each page, and the stored file.
"""

from __future__ import annotations

import logging
from uuid import UUID

from sqlalchemy import delete, exists, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import Principal
from app.core.errors import ConflictError, NotFoundError, ValidationError
from app.models.course import Course
from app.models.delivered_question import DeliveredQuestion
from app.models.material import Material
from app.models.question import Question
from app.models.rag_chunk import RagChunk
from app.models.student_response import StudentResponse
from app.repositories.course_repository import CourseRepository
from app.repositories.material_repository import MaterialRepository
from app.schemas.identity import Role
from app.services.storage import MAX_DISPLAY_NAME, MaterialStorage

log = logging.getLogger("clip.materials")

UNFINISHED = {"pending", "processing"}


async def owned_material(db: AsyncSession, principal: Principal, material_id: UUID) -> Material:
    """The material, if the caller may change it. A material someone else
    uploaded is missing to a lecturer, as it is when read."""
    uploaded_by = None if principal.is_(Role.ADMIN) else principal.user_id
    material = await MaterialRepository(db).get_by_id(material_id, uploaded_by_user_id=uploaded_by)
    if material is None:
        raise NotFoundError("Material was not found.", {"material_id": str(material_id)})
    return material


def clean_name(filename: str) -> str:
    """A display name: printable, trimmed, and within the column."""
    name = "".join(ch for ch in filename if ch.isprintable()).strip()
    if not name:
        raise ValidationError("Give the material a name.", {"field": "filename"})
    if len(name) > MAX_DISPLAY_NAME:
        raise ValidationError(
            f"A name can be at most {MAX_DISPLAY_NAME} characters.", {"field": "filename"}
        )
    return name


async def update_material(
    db: AsyncSession,
    principal: Principal,
    material_id: UUID,
    *,
    filename: str | None,
    course_code: str | None,
    set_course: bool,
) -> Material:
    """Rename the material, and when `set_course` is given, file it under a
    course (or none). The caller commits."""
    material = await owned_material(db, principal, material_id)
    if filename is not None:
        material.filename = clean_name(filename)
    if set_course:
        if course_code is None or not course_code.strip():
            material.course_id = None
        else:
            course = await CourseRepository(db).get_by_code(course_code.strip())
            if course is None:
                raise NotFoundError("No course has that code.", {"course_code": course_code})
            material.course_id = course.id
    await db.flush()
    return material


async def delete_material(
    db: AsyncSession,
    principal: Principal,
    material_id: UUID,
    storage: MaterialStorage,
) -> None:
    """Delete the material and what was drawn from it. The caller commits;
    the stored file is removed after, so a failed commit keeps it."""
    material = await owned_material(db, principal, material_id)
    if material.status in UNFINISHED:
        raise ConflictError(
            "This material is still being processed. Delete it once it has finished.",
            {"material_id": str(material_id), "status": material.status},
        )
    its_questions = select(Question.question_id).where(Question.source_material_id == material.id)
    used = await db.scalar(
        select(
            exists().where(DeliveredQuestion.question_id.in_(its_questions))
            | exists().where(StudentResponse.question_id.in_(its_questions))
        )
    )
    if used:
        raise ConflictError(
            "Its questions were used in a class, so deleting it would remove that class's "
            "history. Rename it instead if it is in the way.",
            {"material_id": str(material_id)},
        )
    await db.execute(delete(Question).where(Question.source_material_id == material.id))
    await db.execute(delete(RagChunk).where(RagChunk.source_material_id == material.id))
    # Pages read, processing history and model runs cascade with the row.
    await db.execute(delete(Material).where(Material.id == material.id))
    await db.flush()


async def remove_stored_file(storage: MaterialStorage, material_id: UUID) -> None:
    """After the rows are gone. A file left behind is purged by retention."""
    try:
        await storage.delete(material_id)
    except Exception:
        log.warning("could not delete the stored file of material %s", material_id)


async def course_codes(db: AsyncSession, course_ids: set[UUID]) -> dict[UUID, str]:
    if not course_ids:
        return {}
    rows = await db.execute(select(Course.id, Course.code).where(Course.id.in_(course_ids)))
    return dict(rows.tuples().all())
