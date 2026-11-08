"""The lecturer's AI switches for a class, and the course defaults.

Owner: General CS, Phase 8. A lecturer can turn off, for their own class:
checkpoints on C.L.I.P's timer, the learning assistant, refocus nudges and
engagement estimates. The classroom applies a change at once and tells the
class, so students' pages hide what is off. With apply_to_course, the same
choice becomes what every new class of the course starts with. A class that
already exists keeps its own switches.
"""

from __future__ import annotations

from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import Principal
from app.core.errors import PermissionError_
from app.models.course import Course
from app.realtime.classroom import classroom
from app.repositories.session_repository import SessionRepository
from app.schemas.ai_controls import AiControlsOut, AiControlsUpdate
from app.schemas.events import AiControls
from app.schemas.session import SessionStatus
from app.services.course_membership import my_courses
from app.services.session_lifecycle import FINISHED, owned_session


def _store(row: object, controls: AiControls) -> None:
    row.ai_auto_checkpoints = controls.auto_checkpoints  # type: ignore[attr-defined]
    row.ai_learning_assistant = controls.learning_assistant  # type: ignore[attr-defined]
    row.ai_refocus_nudges = controls.refocus_nudges  # type: ignore[attr-defined]
    row.ai_engagement_estimates = controls.engagement_estimates  # type: ignore[attr-defined]


async def read(db: AsyncSession, principal: Principal, session_id: UUID) -> AiControlsOut:
    row = await owned_session(SessionRepository(db), principal, session_id, for_update=False)
    course = await db.get(Course, row.course_id)
    return AiControlsOut(
        **AiControls.of(row).model_dump(),
        course_defaults=AiControls.of(course),
    )


async def update(
    db: AsyncSession, principal: Principal, session_id: UUID, payload: AiControlsUpdate
) -> AiControlsOut:
    row = await owned_session(SessionRepository(db), principal, session_id)
    controls = AiControls.model_validate(payload.model_dump(exclude={"apply_to_course"}))
    _store(row, controls)
    course = await db.get(Course, row.course_id)
    if payload.apply_to_course and course is not None:
        # Running a class is not enough to set a course's defaults: only its
        # lecturers, or an admin, may.
        if course.code not in {c.code for c in await my_courses(db, principal)}:
            raise PermissionError_(
                "Only a lecturer of this course can save these for every class of it.",
                {"course_code": course.code},
            )
        _store(course, controls)
    status = SessionStatus(row.status)
    await db.commit()
    if row.status not in FINISHED:
        await classroom.set_ai(session_id, controls, status)
    return AiControlsOut(**controls.model_dump(), course_defaults=AiControls.of(course))
