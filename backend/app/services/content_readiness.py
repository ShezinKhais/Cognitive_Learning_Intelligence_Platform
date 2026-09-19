"""Pre-session content-readiness gate.

Owner: AI 1, Phase 4. A session -- whether started from the staff console or
automatically from a Teams meeting-start event -- must not go live until the
course has at least one fully processed material and the session has at
least one question a lecturer has actually reviewed. Phase 3's start_session
only checked for a staged question; this supersedes that with the fuller
check PHASES.md asks for, while keeping the same failure shape.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession

from app.repositories.material_repository import MaterialRepository
from app.repositories.question_repository import QuestionRepository
from app.schemas.content import MaterialStatus, QuestionStatus


@dataclass(frozen=True)
class SessionReadiness:
    ready: bool
    reason: str | None
    materials_completed: int
    materials_processing: int
    materials_failed: int
    approved_questions: int
    staged_questions: int


async def check_session_readiness(
    db: AsyncSession,
    *,
    course_id: uuid.UUID,
    session_id: uuid.UUID,
) -> SessionReadiness:
    material_counts = await MaterialRepository(db).count_by_course_status(course_id)
    question_counts = await QuestionRepository(db).count_by_session_status(session_id)

    completed = material_counts.get(MaterialStatus.COMPLETED.value, 0)
    processing = material_counts.get(MaterialStatus.PROCESSING.value, 0) + material_counts.get(
        MaterialStatus.PENDING.value, 0
    )
    failed = material_counts.get(MaterialStatus.FAILED.value, 0)

    approved = question_counts.get(QuestionStatus.APPROVED.value, 0)
    staged = question_counts.get(QuestionStatus.STAGED.value, 0)
    # Delivered questions came from this same pool of reviewed work; a
    # session resuming mid-cycle should not be told it is unready because
    # everything it started with has already gone out.
    delivered = question_counts.get(QuestionStatus.DELIVERED.value, 0)

    reason = None
    if completed == 0:
        reason = (
            "No processed material for this course yet."
            if processing == 0
            else "Material is still processing."
        )
    elif approved + staged + delivered == 0:
        reason = "No question has been approved for this session yet."

    return SessionReadiness(
        ready=reason is None,
        reason=reason,
        materials_completed=completed,
        materials_processing=processing,
        materials_failed=failed,
        approved_questions=approved,
        staged_questions=staged,
    )
