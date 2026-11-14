"""Prepare independent copies for a lesson, serialized with session start/delivery.

No generated draft is implicitly approved. Only reviewed bank entries are candidates.
Legacy sessions keep the course bank; opt-in sessions never fall back when exhausted.
"""

from uuid import UUID

from sqlalchemy import exists, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import Principal
from app.core.errors import ConflictError, NotFoundError, ValidationError
from app.models.delivered_question import DeliveredQuestion
from app.models.material import Material
from app.models.question import Question
from app.models.student_response import StudentResponse
from app.repositories.session_repository import SessionRepository
from app.schemas.common import Page
from app.schemas.question_plan import LessonQuestionOut, QuestionPlanIn, QuestionPlanOut
from app.services.question_bank import copy_question, validate_reusable
from app.services.session_lifecycle import owned_session


def question_out(question: Question, title: str) -> LessonQuestionOut:
    return LessonQuestionOut(
        id=question.question_id,
        material_id=question.source_material_id,
        type=question.question_type,
        status=question.status,
        difficulty=question.difficulty,
        prompt=question.question_text,
        options=question.options,
        correct_option=question.correct_option,
        reference_answer=question.reference_answer,
        key_points=question.key_points,
        topic=question.topic,
        source_slide=question.source_slide,
        source_excerpt=question.source_excerpt,
        material_title=title,
        source_question_id=question.source_question_id,
    )


def candidates_query(live):
    return (
        select(Question, Material.filename)
        .join(Material, Material.id == Question.source_material_id)
        .where(
            Material.uploaded_by_user_id == live.instructor_id,
            or_(Material.course_id.is_(None), Material.course_id == live.course_id),
            Material.status == "completed",
            Question.status.in_(["approved", "staged", "delivered"]),
            or_(Question.session_id.is_(None), Question.status == "delivered"),
        )
    )


async def candidates(
    db: AsyncSession,
    principal: Principal,
    session_id: UUID,
    limit: int,
    offset: int,
    material: str | None,
    topic: str | None,
):
    live = await owned_session(SessionRepository(db), principal, session_id, for_update=False)
    query = candidates_query(live)
    if material:
        query = query.where(Material.filename.icontains(material, autoescape=True))
    if topic:
        query = query.where(Question.topic.icontains(topic, autoescape=True))
    total = await db.scalar(select(func.count()).select_from(query.subquery())) or 0
    rows = (
        await db.execute(
            query.order_by(Material.filename, Question.created_at, Question.question_id)
            .limit(limit)
            .offset(offset)
        )
    ).all()
    return Page[LessonQuestionOut](
        items=[question_out(q, title) for q, title in rows], total=total, limit=limit, offset=offset
    )


async def read_plan(db: AsyncSession, principal: Principal, session_id: UUID):
    live = await owned_session(SessionRepository(db), principal, session_id, for_update=False)
    rows = []
    if live.question_selection_enabled:
        rows = (
            await db.execute(
                select(Question, Material.filename)
                .join(Material, Material.id == Question.source_material_id)
                .where(Question.session_id == session_id)
                .order_by(Question.created_at, Question.question_id)
            )
        ).all()
    return QuestionPlanOut(
        session_id=session_id,
        selected_only=live.question_selection_enabled,
        editable=live.status == "prepared",
        items=[question_out(q, title) for q, title in rows],
    )


async def save_plan(
    db: AsyncSession, principal: Principal, session_id: UUID, payload: QuestionPlanIn
):
    # Same first lock as start and delivery. A plan cannot change under an active class.
    live = await owned_session(SessionRepository(db), principal, session_id)
    if live.status != "prepared":
        raise ConflictError("Choose lesson checkpoints before starting the class.")
    if not payload.reviewed_confirmed:
        raise ValidationError("Confirm the selected questions and sources suit this lesson.")
    if not payload.selected_only and payload.question_ids:
        raise ValidationError("Course-bank mode cannot also specify a lesson selection.")
    existing = list(
        (
            await db.scalars(
                select(Question)
                .where(Question.session_id == session_id)
                .order_by(Question.question_id)
                .with_for_update()
            )
        ).all()
    )
    old_ids = {q.question_id for q in existing}
    if old_ids and await db.scalar(
        select(
            exists().where(DeliveredQuestion.question_id.in_(old_ids))
            | exists().where(StudentResponse.question_id.in_(old_ids))
        )
    ):
        raise ConflictError("This lesson already has historical answers or deliveries.")
    wanted = set(payload.question_ids)
    keep = {q.question_id: q for q in existing if q.question_id in wanted}
    if keep:
        scoped_ids = set(
            await db.scalars(
                select(Question.question_id)
                .join(Material, Material.id == Question.source_material_id)
                .where(
                    Question.question_id.in_(keep),
                    Material.uploaded_by_user_id == live.instructor_id,
                    or_(Material.course_id.is_(None), Material.course_id == live.course_id),
                    Material.status == "completed",
                )
            )
        )
        if scoped_ids != keep.keys():
            raise NotFoundError("A selected material is no longer available for this lesson.")
    new_ids = wanted - keep.keys()
    rows = []
    if new_ids:
        rows = (
            await db.execute(
                candidates_query(live)
                .where(Question.question_id.in_(new_ids))
                .order_by(Question.question_id)
                .with_for_update(of=Question)
                .execution_options(populate_existing=True)
            )
        ).all()
        if {q.question_id for q, _ in rows} != new_ids:
            raise NotFoundError("One or more selected questions are unavailable for this lesson.")
    selected = [*keep.values(), *(q for q, _ in rows)]
    origins = {q.source_question_id or q.question_id for q in selected}
    if len(origins) != len(selected):
        raise ValidationError("Select each source checkpoint only once per lesson.")
    for q in selected:
        validate_reusable(q)
    # All validation precedes mutation. Copies leave the bank and historical answers intact.
    for q in existing:
        if q.question_id not in keep:
            await db.delete(q)
    for q, _ in rows:
        clone = copy_question(q, principal.user_id)
        clone.session_id = session_id
        db.add(clone)
    live.question_selection_enabled = payload.selected_only
    await db.commit()
    return await read_plan(db, principal, session_id)
