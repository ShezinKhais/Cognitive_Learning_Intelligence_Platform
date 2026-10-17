"""Whether a prepared session has the content it needs to begin.

Owner: AI 1, Phase 4.

A session may always start. Nothing here blocks it: a lecturer can open a
class before any question is staged and stage one once it is live, since
delivery looks for staged questions at the moment it sends one. Missing
material, material still processing, a failed upload and having no staged
question yet are all warnings, shown so the lecturer knows what the class
has to work with. The readiness endpoint and start_session both call
evaluate_readiness, so what the lecturer is shown and what the start button
does cannot disagree.
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.material import Material
from app.models.session import Session
from app.repositories.session_repository import SessionRepository
from app.schemas.content import MaterialStatus
from app.schemas.session import ReadinessIssue, ReadinessIssueCode, SessionReadinessOut

# Materials that have not finished yet. Either may still produce questions.
_UNFINISHED = {MaterialStatus.PENDING.value, MaterialStatus.PROCESSING.value}


def assess(
    session_id: UUID,
    materials: list[Material],
    deliverable_questions: int,
    *,
    now: datetime | None = None,
) -> SessionReadinessOut:
    """Build the readiness report from what is already known. No database."""
    blockers: list[ReadinessIssue] = []
    warnings: list[ReadinessIssue] = []

    unfinished = [m for m in materials if m.status in _UNFINISHED]
    failed = [m for m in materials if m.status == MaterialStatus.FAILED.value]

    if not materials:
        warnings.append(
            ReadinessIssue(
                code=ReadinessIssueCode.NO_MATERIAL,
                message="No lecture material is uploaded for this course yet.",
            )
        )

    for material in unfinished:
        warnings.append(
            ReadinessIssue(
                code=ReadinessIssueCode.MATERIAL_PROCESSING,
                message=f"{material.filename} is still being processed.",
                material_id=material.id,
            )
        )

    for material in failed:
        warnings.append(
            ReadinessIssue(
                code=ReadinessIssueCode.MATERIAL_FAILED,
                message=f"{material.filename} could not be processed and has no questions.",
                material_id=material.id,
            )
        )

    if deliverable_questions == 0:
        warnings.append(
            ReadinessIssue(
                code=ReadinessIssueCode.NO_APPROVED_QUESTIONS,
                message="No approved question is staged yet. The session can start, "
                "but there is nothing to send until one is staged.",
            )
        )

    return SessionReadinessOut(
        session_id=session_id,
        ready=True,
        blockers=blockers,
        warnings=warnings,
        materials_total=len(materials),
        materials_processing=len(unfinished),
        materials_failed=len(failed),
        deliverable_questions=deliverable_questions,
        checked_at=now or datetime.now(UTC),
    )


async def evaluate_readiness(db: AsyncSession, live: Session) -> SessionReadinessOut:
    """Load the session's materials and staged questions, then assess them."""
    repo = SessionRepository(db)
    materials = await repo.materials_for(live)
    deliverable = await repo.count_deliverable(live)
    return assess(live.session_id, materials, deliverable)
