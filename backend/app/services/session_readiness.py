
"""Check whether a prepared lecture session can begin.

Owner: AI 1, Phase 4.

A lecturer can start a session even when no lecture materials have been
uploaded or no approved questions have been staged.

Missing materials, unfinished processing, failed processing, and missing
approved questions are reported as warnings rather than blockers.

This allows teaching to begin without requiring a quiz or checkpoint.

Questions can only be delivered when they are available and staged for
the session. The question delivery system performs its own checks.

Both the readiness endpoint and the session-starting service use
evaluate_readiness(), keeping the dashboard and backend consistent.
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.material import Material
from app.models.session import Session
from app.repositories.session_repository import SessionRepository
from app.schemas.content import MaterialStatus
from app.schemas.session import (
    ReadinessIssue,
    ReadinessIssueCode,
    SessionReadinessOut,
)


# Material statuses indicating that processing is not yet complete.
# These materials may eventually produce questions, but they do not
# prevent a lecturer from starting a session.
_UNFINISHED = {
    MaterialStatus.PENDING.value,
    MaterialStatus.PROCESSING.value,
}


def assess(
    session_id: UUID,
    materials: list[Material],
    deliverable_questions: int,
    *,
    now: datetime | None = None,
) -> SessionReadinessOut:
    """Build a readiness report without querying the database.

    The session is always allowed to start from a content-readiness
    perspective.

    Missing materials and questions are reported as warnings so the
    lecturer knows which features may be unavailable.

    Other session requirements, such as the lecturer's permissions and
    the session's current status, are checked elsewhere.
    """

    # Content-readiness issues no longer prevent starting a lecture.
    blockers: list[ReadinessIssue] = []

    # Warnings inform the lecturer about missing or unavailable content.
    warnings: list[ReadinessIssue] = []

    # Find materials that have not finished processing.
    unfinished = [
        material
        for material in materials
        if material.status in _UNFINISHED
    ]

    # Find materials whose processing failed.
    failed = [
        material
        for material in materials
        if material.status == MaterialStatus.FAILED.value
    ]

    # A lecture may start even without materials or approved questions.
    ready = True

    # All content-readiness issues are informational warnings.
    reasons = warnings

    # Warn the lecturer if no lecture materials have been uploaded.
    if not materials:
        reasons.append(
            ReadinessIssue(
                code=ReadinessIssueCode.NO_MATERIAL,
                message=(
                    "No lecture material has been uploaded. "
                    "You can start the lecture, but material-based "
                    "questions will be unavailable."
                ),
            )
        )

    # Warn about materials that are still pending or processing.
    # Processing does not prevent the lecture from starting.
    for material in unfinished:
        reasons.append(
            ReadinessIssue(
                code=ReadinessIssueCode.MATERIAL_PROCESSING,
                message=(
                    f"{material.filename} is still being processed."
                ),
                material_id=material.id,
            )
        )

    # Warn about materials whose processing failed.
    # Other usable materials and questions remain available.
    for material in failed:
        warnings.append(
            ReadinessIssue(
                code=ReadinessIssueCode.MATERIAL_FAILED,
                message=(
                    f"{material.filename} could not be processed "
                    "and has no questions."
                ),
                material_id=material.id,
            )
        )

    # Missing approved questions do not prevent the lecture from starting.
    # Checkpoints remain unavailable until questions are staged.
    if deliverable_questions == 0:
        warnings.append(
            ReadinessIssue(
                code=ReadinessIssueCode.NO_APPROVED_QUESTIONS,
                message=(
                    "No approved questions are staged. "
                    "You can start the lecture, but checkpoints "
                    "will be unavailable until questions are approved."
                ),
            )
        )

    # Return the readiness report used by the lecturer dashboard
    # and the backend session-starting service.
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


async def evaluate_readiness(
    db: AsyncSession,
    live: Session,
) -> SessionReadinessOut:
    """Load session materials and staged questions, then assess readiness.

    The database provides the current material-processing states and
    the number of questions available for delivery.

    The assess() function converts that information into a readiness
    report containing any relevant warnings.
    """

    repo = SessionRepository(db)

    # Retrieve materials associated with this session.
    materials = await repo.materials_for(live)

    # Count questions that are currently available for delivery.
    deliverable = await repo.count_deliverable(live)

    # Generate and return the readiness report.
    return assess(
        live.session_id,
        materials,
        deliverable,
    )
