"""A student's own engagement history across finished classes (#243).

Read only from what each class stored. Nothing here scores anyone:
participation is counted, device readings are reported as available or not.

Readings follow consent as it stands now. A student who has withdrawn
engagement monitoring sees no readings at all, and a sensor is counted only
from the latest time it was granted, so a window recorded before a withdrawal
and later regrant never reappears. Readings removed by the retention purge or
an erasure simply are not there, and show as none recorded.

Only the caller's own record is read: sessions are those of the courses they
are on that have ended, and every count is filtered by their student id.
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.attention_signal_summary import AttentionSignalSummary as Window
from app.models.consent import Consent
from app.models.delivered_question import DeliveredQuestion
from app.models.missed_response import MissedResponse
from app.models.session import Session
from app.models.session_participant import SessionParticipant
from app.models.student_response import StudentResponse
from app.schemas.identity import ConsentType
from app.schemas.student_engagement import (
    ClassEngagement,
    ClassParticipation,
    ClassReadings,
    StudentEngagementHistory,
)
from app.services.student_review import sessions_query

_SENSORS = (ConsentType.ENGAGEMENT_MONITORING, ConsentType.CAMERA, ConsentType.MICROPHONE)


async def _grants(db: AsyncSession, user_id: UUID) -> dict[str, datetime]:
    """When each sensor consent was last granted, for those granted now. The
    latest record of each type decides: a later withdrawal removes it."""
    latest: dict[str, tuple[bool, datetime]] = {}
    rows = await db.execute(
        select(Consent.consent_type, Consent.granted, Consent.recorded_at)
        .where(Consent.user_id == user_id, Consent.consent_type.in_([s.value for s in _SENSORS]))
        .order_by(Consent.recorded_at)
    )
    for kind, granted, at in rows.tuples().all():
        latest[kind] = (granted, at)
    return {kind: at for kind, (granted, at) in latest.items() if granted}


async def _count(db: AsyncSession, student_id: UUID, session_ids: list[UUID], *where) -> dict:
    if not session_ids:
        return {}
    rows = await db.execute(
        select(Window.session_id, func.count())
        .where(Window.student_id == student_id, Window.session_id.in_(session_ids), *where)
        .group_by(Window.session_id)
    )
    return dict(rows.tuples().all())


async def history(
    db: AsyncSession, user_id: UUID, limit: int, offset: int
) -> StudentEngagementHistory:
    query = sessions_query(user_id)
    total = await db.scalar(select(func.count()).select_from(query.subquery())) or 0
    rows = (
        await db.execute(
            query.order_by(Session.ended_at.desc().nullslast(), Session.session_id)
            .limit(limit)
            .offset(offset)
        )
    ).all()
    if not rows:
        return StudentEngagementHistory(classes=[], total=total, limit=limit, offset=offset)
    student_id = rows[0][2]
    ids = [session.session_id for session, _, _ in rows]

    async def per_session(stmt) -> dict:  # noqa: ANN001
        return dict((await db.execute(stmt)).tuples().all())

    sent = await per_session(
        select(DeliveredQuestion.session_id, func.count())
        .where(DeliveredQuestion.session_id.in_(ids))
        .group_by(DeliveredQuestion.session_id)
    )
    answered = await per_session(
        select(StudentResponse.session_id, func.count())
        .where(StudentResponse.session_id.in_(ids), StudentResponse.student_id == student_id)
        .group_by(StudentResponse.session_id)
    )
    missed = await per_session(
        select(DeliveredQuestion.session_id, func.count())
        .join(MissedResponse, MissedResponse.delivery_id == DeliveredQuestion.delivery_id)
        .where(DeliveredQuestion.session_id.in_(ids), MissedResponse.student_id == student_id)
        .group_by(DeliveredQuestion.session_id)
    )
    joined = set(
        await db.scalars(
            select(SessionParticipant.session_id).where(
                SessionParticipant.session_id.in_(ids),
                SessionParticipant.student_id == student_id,
            )
        )
    )

    grants = await _grants(db, user_id)
    monitoring = grants.get(ConsentType.ENGAGEMENT_MONITORING.value)
    camera_from = grants.get(ConsentType.CAMERA.value)
    microphone_from = grants.get(ConsentType.MICROPHONE.value)
    camera: dict = {}
    microphone: dict = {}
    if monitoring is not None and camera_from is not None:
        camera = await _count(
            db,
            student_id,
            ids,
            Window.window_start >= max(monitoring, camera_from),
            or_(Window.gaze_on_screen_ratio.is_not(None), Window.face_present_ratio.is_not(None)),
        )
    if monitoring is not None and microphone_from is not None:
        microphone = await _count(
            db,
            student_id,
            ids,
            Window.window_start >= max(monitoring, microphone_from),
            Window.speaking_ratio.is_not(None),
        )

    def availability(consented: bool, windows: int | None) -> str:
        if not consented:
            return "not_consented"
        return "available" if windows else "none_recorded"

    classes = []
    for session, code, _ in rows:
        sid = session.session_id
        cam, mic = camera.get(sid), microphone.get(sid)
        classes.append(
            ClassEngagement(
                session_id=sid,
                title=session.title or code,
                course_code=code,
                ended_at=session.ended_at,
                participation=ClassParticipation(
                    joined=sid in joined,
                    checkpoints=sent.get(sid, 0),
                    answered=answered.get(sid, 0),
                    missed=missed.get(sid, 0),
                ),
                readings=ClassReadings(
                    camera=availability(monitoring is not None and camera_from is not None, cam),
                    camera_windows=cam or None,
                    microphone=availability(
                        monitoring is not None and microphone_from is not None, mic
                    ),
                    microphone_windows=mic or None,
                ),
            )
        )
    return StudentEngagementHistory(classes=classes, total=total, limit=limit, offset=offset)
