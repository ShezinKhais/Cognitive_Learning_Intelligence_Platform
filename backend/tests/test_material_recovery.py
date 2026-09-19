"""Ending materials whose processing stopped without recording an end.

Runs against a migrated database and skips without one.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

from app.models.material import Material
from app.models.material_processing_status import MaterialProcessingStatus
from app.services.material_recovery import (
    STALE_AFTER,
    STRANDED_MESSAGE,
    fail_stranded_materials,
)

from .test_material_store import lecturer, sessions  # noqa: F401

LONG_AGO = datetime.now(UTC) - STALE_AFTER - timedelta(minutes=5)


async def _material(sessions, owner, *, status, uploaded_at, recorded_at=None):  # noqa: F811
    material_id = uuid.uuid4()
    async with sessions() as session, session.begin():
        session.add(
            Material(
                id=material_id,
                filename="lecture.pdf",
                content_type="application/pdf",
                size_bytes=1024,
                status=status,
                uploaded_by_user_id=owner,
                uploaded_at=uploaded_at,
            )
        )
        if recorded_at is not None:
            await session.flush()
            session.add(
                MaterialProcessingStatus(
                    source_material_id=material_id,
                    sequence=1,
                    stage="extracting",
                    percent=20,
                    recorded_at=recorded_at,
                )
            )
    return material_id


async def test_only_a_material_nobody_is_working_on_is_failed(sessions, lecturer):  # noqa: F811
    """A failure the job could not record left the material processing
    forever, with a progress bar that would never finish."""
    stranded = await _material(sessions, lecturer, status="processing", uploaded_at=LONG_AGO)
    queued_forever = await _material(sessions, lecturer, status="pending", uploaded_at=LONG_AGO)
    still_running_here = await _material(
        sessions, lecturer, status="processing", uploaded_at=LONG_AGO
    )
    recently_active = await _material(
        sessions,
        lecturer,
        status="processing",
        uploaded_at=LONG_AGO,
        recorded_at=datetime.now(UTC),
    )
    just_uploaded = await _material(
        sessions, lecturer, status="pending", uploaded_at=datetime.now(UTC)
    )
    finished = await _material(sessions, lecturer, status="completed", uploaded_at=LONG_AGO)

    failed = await fail_stranded_materials(
        frozenset({still_running_here}), sessions=lambda: sessions
    )

    assert set(failed) == {stranded, queued_forever}
    async with sessions() as session:
        for material_id in (stranded, queued_forever):
            row = await session.get(Material, material_id)
            assert row.status == "failed"
            assert row.error == STRANDED_MESSAGE
        for material_id, status in (
            (still_running_here, "processing"),
            (recently_active, "processing"),
            (just_uploaded, "pending"),
            (finished, "completed"),
        ):
            assert (await session.get(Material, material_id)).status == status
