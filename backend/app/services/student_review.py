"""Read only the caller's ended-session answers and their bounded source context.

No new scoring or model calls. The legacy engagement table has neither confidence
nor missing-signal metadata, so it cannot safely populate a verified review score.
Cyber 1 can supply that contract later without conflating it with comprehension.
"""

from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import NotFoundError
from app.models.comprehension_result import ComprehensionResult
from app.models.course import Course
from app.models.delivered_question import DeliveredQuestion
from app.models.material import Material
from app.models.missed_response import MissedResponse
from app.models.question import Question
from app.models.rag_chunk import RagChunk
from app.models.session import Session
from app.models.student import Student
from app.models.student_response import StudentResponse
from app.schemas.common import Page
from app.schemas.student_review import (
    ReviewAnswer,
    ReviewSession,
    ReviewSource,
    ReviewSources,
    StudentReview,
)


def sessions_query(user_id: UUID):
    return (
        select(Session, Course.code, Student.student_id)
        .join(Course, Course.id == Session.course_id)
        .join(Student, Student.course_id == Session.course_id)
        .where(Student.user_id == user_id, Session.status == "ended")
    )


def session_out(row: Session, course_code: str) -> ReviewSession:
    return ReviewSession(
        id=row.session_id,
        title=row.title or course_code,
        course_code=course_code,
        ended_at=row.ended_at,
    )


async def list_reviews(db: AsyncSession, user_id: UUID, limit: int, offset: int):
    query = sessions_query(user_id)
    total = await db.scalar(select(func.count()).select_from(query.subquery()))
    rows = (
        await db.execute(
            query.order_by(Session.ended_at.desc().nullslast(), Session.session_id)
            .limit(limit)
            .offset(offset)
        )
    ).all()
    return Page[ReviewSession](
        items=[session_out(s, c) for s, c, _ in rows], total=total or 0, limit=limit, offset=offset
    )


async def own_session(db: AsyncSession, user_id: UUID, session_id: UUID):
    row = (
        await db.execute(sessions_query(user_id).where(Session.session_id == session_id))
    ).one_or_none()
    if row is None:
        # Non-members, missing sessions and sessions not yet ended look identical.
        raise NotFoundError("Session review is unavailable.")
    return row


def answer_text(response: StudentResponse, question: Question) -> str:
    if response.free_text is not None:
        return response.free_text
    index = response.selected_option
    if index is not None and question.options and 0 <= index < len(question.options):
        return question.options[index]
    return "Answer text unavailable"


async def read_review(db: AsyncSession, user_id: UUID, session_id: UUID, limit: int, offset: int):
    session, code, student_id = await own_session(db, user_id, session_id)
    scope = (StudentResponse.session_id == session_id, StudentResponse.student_id == student_id)
    total = await db.scalar(select(func.count()).select_from(StudentResponse).where(*scope)) or 0
    missed = await db.scalar(
        select(func.count())
        .select_from(MissedResponse)
        .join(DeliveredQuestion, DeliveredQuestion.delivery_id == MissedResponse.delivery_id)
        .where(DeliveredQuestion.session_id == session_id, MissedResponse.student_id == student_id)
    )
    rows = (
        await db.execute(
            select(StudentResponse, Question, ComprehensionResult)
            .join(Question, Question.question_id == StudentResponse.question_id)
            .outerjoin(
                ComprehensionResult, ComprehensionResult.response_id == StudentResponse.response_id
            )
            .where(*scope)
            .order_by(StudentResponse.submitted_at, StudentResponse.response_id)
            .limit(limit)
            .offset(offset)
        )
    ).all()
    answers = [
        ReviewAnswer(
            id=r.response_id,
            question=q.question_text,
            topic=q.topic,
            answer=answer_text(r, q),
            is_correct=r.is_correct,
            label=c.label if c else None,
            confidence=c.confidence_score if c else None,
            submitted_at=r.submitted_at,
        )
        for r, q, c in rows
    ]
    return StudentReview(
        session=session_out(session, code),
        questions_attempted=total,
        questions_missed=missed or 0,
        answers=answers,
        total=total,
        limit=limit,
        offset=offset,
    )


async def read_sources(db: AsyncSession, user_id: UUID, session_id: UUID, response_id: UUID):
    session, _, student_id = await own_session(db, user_id, session_id)
    question = (
        await db.execute(
            select(Question)
            .join(StudentResponse, StudentResponse.question_id == Question.question_id)
            .where(
                StudentResponse.response_id == response_id,
                StudentResponse.session_id == session_id,
                StudentResponse.student_id == student_id,
            )
        )
    ).scalar_one_or_none()
    if question is None:
        raise NotFoundError("Answer was not found.")
    # Never search all materials or trust a client-supplied chunk/material id.
    # Only the question's material, still belonging to this course, is eligible.
    query = (
        select(RagChunk, Material.filename)
        .join(Material, Material.id == RagChunk.source_material_id)
        .where(
            RagChunk.source_material_id == question.source_material_id,
            Material.course_id == session.course_id,
        )
    )
    excerpt = (question.source_excerpt or "").strip()
    if question.source_slide is not None:
        query = query.where(RagChunk.source_page == question.source_slide)
    elif excerpt:
        query = query.where(RagChunk.chunk_text.contains(excerpt, autoescape=True))
    else:
        return ReviewSources(items=[])
    rows = (
        await db.execute(query.order_by(RagChunk.chunk_index, RagChunk.chunk_id).limit(6))
    ).all()
    return ReviewSources(
        items=[
            ReviewSource(
                chunk_id=chunk.chunk_id,
                material_title=title,
                source_page=chunk.source_page,
                text=chunk.chunk_text,
                match="excerpt" if excerpt and excerpt in chunk.chunk_text else "page",
            )
            for chunk, title in rows[:5]
        ],
        has_more=len(rows) > 5,
    )
