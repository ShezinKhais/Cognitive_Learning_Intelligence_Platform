"""A student's own data, as they can take it away.

Owner: BBIS, Phase 7. The export holds what the platform keeps about one
student: their account, profile, answers with the labels given to them, prompts,
engagement, attention summaries, missed responses and deletion requests. It never
holds another student's data, and writing it is audited with counts only.

The caller owns the transaction and commits.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.history.database import resolve_history_factory
from app.history.repository import list_for_student
from app.models.attention_signal_summary import AttentionSignalSummary
from app.models.comprehension_result import ComprehensionResult
from app.models.deletion_request import DeletionRequest
from app.models.dynamic_prompt import DynamicPrompt
from app.models.engagement_record import EngagementRecord
from app.models.missed_response import MissedResponse
from app.models.student import Student
from app.models.student_response import StudentResponse
from app.models.user import User
from app.repositories.audit_repository import record_event

EXPORT_ACTION = "STUDENT_DATA_EXPORTED"


class StudentNotFound(Exception):
    """The signed-in user has no student profile."""


def _when(value: Any) -> str | None:
    return value.isoformat() if value is not None else None


def _id(value: Any) -> str | None:
    return str(value) if value is not None else None


async def own_student(db: AsyncSession, user_id: UUID) -> Student:
    student = await db.scalar(select(Student).where(Student.user_id == user_id))
    if student is None:
        raise StudentNotFound("There is no student profile for this account.")
    return student


async def latest_deletion_request(db: AsyncSession, student_id: UUID) -> DeletionRequest | None:
    return await db.scalar(
        select(DeletionRequest)
        .where(DeletionRequest.target_type == "student", DeletionRequest.target_id == student_id)
        .order_by(DeletionRequest.requested_at.desc())
        .limit(1)
    )


async def export_student_data(
    db: AsyncSession,
    user_id: UUID,
    *,
    history: Callable[[], Any] | None = None,
) -> dict[str, Any]:
    student = await own_student(db, user_id)
    user = await db.get(User, user_id)
    sid = student.student_id

    answers = []
    rows = await db.execute(
        select(StudentResponse, ComprehensionResult)
        .outerjoin(
            ComprehensionResult, ComprehensionResult.response_id == StudentResponse.response_id
        )
        .where(StudentResponse.student_id == sid)
        .order_by(StudentResponse.submitted_at)
    )
    for response, result in rows:
        answers.append(
            {
                "response_id": _id(response.response_id),
                "session_id": _id(response.session_id),
                "question_id": _id(response.question_id),
                "selected_option": response.selected_option,
                "free_text": response.free_text,
                "is_correct": response.is_correct,
                "elapsed_ms": response.elapsed_ms,
                "submitted_at": _when(response.submitted_at),
                "result": None
                if result is None
                else {
                    "label": result.label,
                    "confidence_score": result.confidence_score,
                    "score": result.score,
                    "feedback": result.ai_feedback_text,
                    "reasons": result.reasons,
                    "key_point_coverage": result.key_point_coverage,
                    "wrong_claim": result.wrong_claim,
                    "similarity": result.similarity,
                    "created_at": _when(result.created_at),
                },
            }
        )

    prompts = [
        {
            "session_id": _id(p.session_id),
            "prompt_text": p.prompt_text,
            "trigger_reason": p.trigger_reason,
            "escalation": p.escalation,
            "sent_at": _when(p.sent_at),
            "response_status": p.response_status,
            "responded_at": _when(p.responded_at),
        }
        for p in await db.scalars(
            select(DynamicPrompt)
            .where(DynamicPrompt.student_id == sid)
            .order_by(DynamicPrompt.sent_at)
        )
    ]
    engagement = [
        {
            "session_id": _id(e.session_id),
            "attempt_rate": e.attempt_rate,
            "attention_signal": e.attention_signal,
            "engagement_score": e.engagement_score,
            "timestamp": _when(e.timestamp),
        }
        for e in await db.scalars(
            select(EngagementRecord)
            .where(EngagementRecord.student_id == sid)
            .order_by(EngagementRecord.timestamp)
        )
    ]
    attention = [
        {
            "session_id": _id(a.session_id),
            "window_start": _when(a.window_start),
            "window_seconds": a.window_seconds,
            "sample_count": a.sample_count,
            "gaze_on_screen_ratio": a.gaze_on_screen_ratio,
            "face_present_ratio": a.face_present_ratio,
            "speaking_ratio": a.speaking_ratio,
        }
        for a in await db.scalars(
            select(AttentionSignalSummary)
            .where(AttentionSignalSummary.student_id == sid)
            .order_by(AttentionSignalSummary.window_start)
        )
    ]
    missed = [
        {"reason": m.reason, "recorded_at": _when(m.recorded_at)}
        for m in await db.scalars(
            select(MissedResponse)
            .where(MissedResponse.student_id == sid)
            .order_by(MissedResponse.recorded_at)
        )
    ]
    requests = [
        {
            "request_id": _id(r.request_id),
            "status": r.status,
            "requested_at": _when(r.requested_at),
            "decided_at": _when(r.decided_at),
            "executed_at": _when(r.executed_at),
        }
        for r in await db.scalars(
            select(DeletionRequest)
            .where(DeletionRequest.target_type == "student", DeletionRequest.target_id == sid)
            .order_by(DeletionRequest.requested_at)
        )
    ]

    summaries = []
    factory = resolve_history_factory(history)
    if factory is not None:
        async with factory() as history_db:
            for row in await list_for_student(history_db, sid):
                summaries.append(
                    {
                        "semester": row.semester,
                        "course_id": _id(row.course_id),
                        "sessions_attended": row.sessions_attended,
                        "questions_attempted": row.questions_attempted,
                        "questions_correct": row.questions_correct,
                        "engagement_average": (
                            row.engagement_sum / row.engagement_count
                            if row.engagement_count
                            else None
                        ),
                        "gaze_average": (row.gaze_sum / row.gaze_count if row.gaze_count else None),
                    }
                )

    await record_event(
        db,
        action_type=EXPORT_ACTION,
        user_id=user_id,
        target_type="student",
        target_id=sid,
        details={
            "answers": len(answers),
            "prompts": len(prompts),
            "engagement": len(engagement),
            "attention_summaries": len(attention),
        },
    )

    return {
        "generated_at": datetime.now(UTC),
        "retention_days": get_settings().data_retention_days,
        "account": {
            "user_id": _id(user_id),
            "name": user.name if user is not None else None,
            "email": user.email if user is not None else None,
        },
        "profile": {
            "student_id": _id(sid),
            "course_id": _id(student.course_id),
            "consent_status": student.consent_status,
            "attention_threshold": student.attention_threshold,
            "enrolled_at": _when(student.enrolled_at),
        },
        "answers": answers,
        "prompts": prompts,
        "engagement": engagement,
        "attention_summaries": attention,
        "missed_responses": missed,
        "deletion_requests": requests,
        "history": summaries,
    }
