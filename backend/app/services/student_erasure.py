"""Erasing one student: their own data goes, the record that it happened stays.

Owner: BBIS, Phase 7. Deleting the student record removes, through the database,
their answers and the labels on them, attention prompts, engagement and attention
summaries, attendance and missed questions. Alerts and recommendations about the
student are deleted too: their text is generated about the student and can describe
them. The student profile goes too, with its accessibility and
special-consideration notes.

The account row stays so the audit log and consent records keep a valid
reference, but it no longer identifies anyone: the name and email are replaced
and sign-in is disabled. Teams ids and names that point at the account are
cleared. Nothing here touches the audit log or consent records.

The caller owns the transaction and commits.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from uuid import UUID

from sqlalchemy import delete, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.ai_alert import AIAlert
from app.models.ai_recommendation import AIRecommendation
from app.models.attention_signal_summary import AttentionSignalSummary
from app.models.dynamic_prompt import DynamicPrompt
from app.models.engagement_record import EngagementRecord
from app.models.student import Student
from app.models.student_response import StudentResponse
from app.models.teams_participant_mapping import TeamsParticipantMapping
from app.models.teams_user_mapping import TeamsUserMapping
from app.models.user import User

DELETED_NAME = "Deleted student"


@dataclass(frozen=True)
class ErasureReport:
    answers: int = 0
    attention_summaries: int = 0
    prompts: int = 0
    engagement: int = 0
    teams_records: int = 0
    alerts: int = 0
    recommendations: int = 0

    def as_counts(self) -> dict[str, int]:
        return asdict(self)


async def _count(db: AsyncSession, model, column, value) -> int:
    return await db.scalar(select(func.count()).select_from(model).where(column == value)) or 0


async def erase_student(db: AsyncSession, student_id: UUID) -> ErasureReport:
    """Erase a student's own data and anonymise their account.

    A student who is already gone reports nothing erased, so a repeat is safe.
    """
    student = await db.scalar(
        select(Student).where(Student.student_id == student_id).with_for_update()
    )
    if student is None:
        return ErasureReport()
    user_id = student.user_id

    answers = await _count(db, StudentResponse, StudentResponse.student_id, student_id)
    attention = await _count(
        db, AttentionSignalSummary, AttentionSignalSummary.student_id, student_id
    )
    prompts = await _count(db, DynamicPrompt, DynamicPrompt.student_id, student_id)
    engagement = await _count(db, EngagementRecord, EngagementRecord.student_id, student_id)

    # Alerts and recommendations about this student are generated text that can
    # describe them, so they are deleted with the student and not merely unlinked.
    recommendations = await db.execute(
        delete(AIRecommendation).where(AIRecommendation.student_id == student_id)
    )
    alerts = await db.execute(delete(AIAlert).where(AIAlert.student_id == student_id))

    await db.execute(delete(Student).where(Student.student_id == student_id))

    mappings = await db.execute(delete(TeamsUserMapping).where(TeamsUserMapping.user_id == user_id))
    participants = await db.execute(
        update(TeamsParticipantMapping)
        .where(TeamsParticipantMapping.user_id == user_id)
        .values(user_id=None, tenant_id=None, teams_user_id=None, display_name=None)
    )

    account = await db.get(User, user_id)
    if account is not None and account.role == "student":
        account.name = DELETED_NAME
        account.email = f"deleted-{user_id.hex}@deleted.invalid"
        account.password_hash = None
        account.active = False
    await db.flush()

    return ErasureReport(
        answers=answers,
        attention_summaries=attention,
        prompts=prompts,
        engagement=engagement,
        teams_records=(mappings.rowcount or 0) + (participants.rowcount or 0),
        alerts=alerts.rowcount or 0,
        recommendations=recommendations.rowcount or 0,
    )
