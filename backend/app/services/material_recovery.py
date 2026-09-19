"""Ending materials whose processing stopped without recording an end.

Owner: General CS, Phase 2.

A job records its own failure, but that write can itself fail: the database
is down when the failure happens, or the process is killed outright. The
material then stays pending or processing in the database with nothing left
to move it on, and the workspace shows a bar that will never finish. This
sweep finds those materials and marks them failed, so the lecturer is told to
upload again rather than left waiting.

A material is only swept when this process is not working on it and nothing
has been recorded for it for STALE_AFTER. The first rule is exact for a single
process; the second keeps a sweep in one process from failing a job another
process is still running.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.database import get_session_factory
from app.models.material import Material
from app.models.material_processing_status import MaterialProcessingStatus
from app.repositories.material_repository import MaterialRepository
from app.schemas.content import MaterialStatus
from app.schemas.events import MaterialStage
from app.services.jobs import STAGE_PERCENT

log = logging.getLogger("clip.material_recovery")

# Far longer than any stage takes; extraction, the slowest, is under a minute.
STALE_AFTER = timedelta(minutes=15)
SWEEP_EVERY_SECONDS = 300.0

STRANDED_MESSAGE = "Processing stopped before it finished. Please upload the file again."


async def fail_stranded_materials(
    active: frozenset[UUID],
    sessions: Callable[[], async_sessionmaker[AsyncSession]] = get_session_factory,
    now: datetime | None = None,
) -> list[UUID]:
    """Mark stranded materials failed and return their ids."""
    cutoff = (now or datetime.now(UTC)) - STALE_AFTER
    last_recorded = (
        select(func.max(MaterialProcessingStatus.recorded_at))
        .where(MaterialProcessingStatus.source_material_id == Material.id)
        .scalar_subquery()
    )
    async with sessions()() as session, session.begin():
        candidates = (
            await session.execute(
                select(Material.id).where(
                    Material.status.in_([MaterialStatus.PENDING, MaterialStatus.PROCESSING]),
                    Material.uploaded_at < cutoff,
                    or_(last_recorded.is_(None), last_recorded < cutoff),
                )
            )
        ).scalars()
        stranded = [material_id for material_id in candidates if material_id not in active]

        repository = MaterialRepository(session)
        for material_id in stranded:
            await repository.record_progress(
                material_id=material_id,
                stage=MaterialStage.FAILED,
                percent=STAGE_PERCENT[MaterialStage.FAILED],
                message=STRANDED_MESSAGE,
            )

    if stranded:
        log.warning("marked %d stranded material(s) failed", len(stranded))
    return stranded


async def keep_sweeping(active: Callable[[], frozenset[UUID]]) -> None:
    """Sweep now and then every SWEEP_EVERY_SECONDS until cancelled.

    Run from the app lifespan. A database that cannot be reached skips that
    sweep; the next one tries again.
    """
    while True:
        try:
            await fail_stranded_materials(active())
        except Exception as exc:
            log.debug("stranded material sweep skipped: %s", type(exc).__name__)
        await asyncio.sleep(SWEEP_EVERY_SECONDS)
