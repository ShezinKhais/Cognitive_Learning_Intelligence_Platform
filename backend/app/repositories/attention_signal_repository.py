"""Stores per-minute summaries of the attention signals a student's device sends.

Owner: BBIS, Phase 6. Each function works inside the caller's transaction and
does not commit. The live recorder collects the signals of one window, calls
summarise() and then save_summary().
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.attention_signal_summary import AttentionSignalSummary
from app.schemas.events import AttentionSignalPayload


@dataclass(frozen=True)
class WindowSummary:
    window_seconds: float
    sample_count: int
    gaze_on_screen_ratio: float | None
    face_present_ratio: float | None
    speaking_ratio: float | None


def _share(values: list[bool]) -> float | None:
    return sum(values) / len(values) if values else None


def summarise(signals: Sequence[AttentionSignalPayload]) -> WindowSummary:
    """Fold the signals of one window into a single summary.

    A signal a sensor did not report is left out of that ratio. When no signal
    reported it, the ratio is None, never zero.
    """
    if not signals:
        raise ValueError("A window needs at least one signal")
    gaze = [s.gaze_on_screen_ratio for s in signals if s.gaze_on_screen_ratio is not None]
    face = [s.face_present for s in signals if s.face_present is not None]
    speaking = [s.speaking for s in signals if s.speaking is not None]
    return WindowSummary(
        window_seconds=sum(s.window_seconds for s in signals),
        sample_count=len(signals),
        gaze_on_screen_ratio=sum(gaze) / len(gaze) if gaze else None,
        face_present_ratio=_share(face),
        speaking_ratio=_share(speaking),
    )


async def save_summary(
    db: AsyncSession,
    *,
    session_id: UUID,
    student_id: UUID,
    window_start: datetime,
    summary: WindowSummary,
) -> AttentionSignalSummary:
    """Add one student's summary for one window to the caller's transaction."""
    row = AttentionSignalSummary(
        session_id=session_id,
        student_id=student_id,
        window_start=window_start,
        window_seconds=summary.window_seconds,
        sample_count=summary.sample_count,
        gaze_on_screen_ratio=summary.gaze_on_screen_ratio,
        face_present_ratio=summary.face_present_ratio,
        speaking_ratio=summary.speaking_ratio,
    )
    db.add(row)
    await db.flush()
    return row


async def list_for_session(db: AsyncSession, session_id: UUID) -> list[AttentionSignalSummary]:
    """Every summary stored for one session, oldest window first."""
    result = await db.execute(
        select(AttentionSignalSummary)
        .where(AttentionSignalSummary.session_id == session_id)
        .order_by(AttentionSignalSummary.window_start, AttentionSignalSummary.student_id)
    )
    return list(result.scalars().all())
