"""Whether a prepared session has the content it needs to begin.

Owner: AI 1, Phase 4.

A session may start once it has at least one approved, staged question to
deliver: that question's material has processed, or it would not exist.
Everything else explains why there is none, or is a warning when there are
some, so a slow upload for another week never holds back a class that has
something to ask. The readiness endpoint and start_session both call
evaluate_readiness, so what the lecturer is shown and what the start button
does cannot disagree.

A failed material is a warning, not a blocker. It will never finish, so
blocking on it would hold the class back forever even when the rest of the
material is fine and has questions staged.
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
    ready = deliverable_questions > 0
    # Only a missing question blocks. Missing or unfinished material is the
    # reason there is none, or a warning when there already are some, so
    # ready is true exactly when blockers is empty.
    reasons = warnings if ready else blockers

    if not materials:
        reasons.append(
            ReadinessIssue(
                code=ReadinessIssueCode.NO_MATERIAL,
                message="Upload lecture material for this course before starting.",
            )
        )

    for material in unfinished:
        reasons.append(
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

    if not ready:
        blockers.append(
            ReadinessIssue(
                code=ReadinessIssueCode.NO_APPROVED_QUESTIONS,
                message="Stage at least one approved question before starting the session.",
            )
        )

    return SessionReadinessOut(
        session_id=session_id,
        ready=ready,
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
