"""Lesson copies, history preservation, course scope and start/take-back races."""

import asyncio
from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest
from sqlalchemy import delete

from app.api.deps import Principal
from app.core.errors import ConflictError
from app.models.delivered_question import DeliveredQuestion
from app.models.material import Material
from app.models.question import Question
from app.models.rag_chunk import RagChunk
from app.models.session import Session
from app.repositories.question_repository import QuestionRepository
from app.repositories.session_repository import SessionRepository
from app.schemas.identity import Role
from app.schemas.question_plan import QuestionPlanIn
from app.services import question_plan
from tests.test_question_review import (
    _as,
    _cleanup_material,
    _seed_question,
    db_client,  # noqa: F401
)


@pytest.fixture
async def lesson(db_client, app):  # noqa: F811
    client, factory = db_client
    owner = uuid4()
    material, question = await _seed_question(factory, uploaded_by=owner, status="staged")
    sessions = [uuid4(), uuid4()]
    async with factory() as db:
        mat = await db.get(Material, material)
        db.add(
            RagChunk(
                source_material_id=material,
                chunk_index=0,
                source_page=3,
                chunk_text="Paris is the capital of France.",
            )
        )
        for sid in sessions:
            db.add(
                Session(
                    session_id=sid,
                    instructor_id=owner,
                    course_id=mat.course_id,
                    title="Lesson selection",
                    start_time=datetime.now(UTC),
                    mode="in_person",
                    status="prepared",
                )
            )
        await db.commit()
    _as(app, owner, Role.LECTURER, "owner@example.test")
    yield client, factory, owner, material, question, sessions
    async with factory() as db:
        await db.execute(
            delete(DeliveredQuestion).where(DeliveredQuestion.session_id.in_(sessions))
        )
        await db.execute(delete(Question).where(Question.session_id.in_(sessions)))
        await db.execute(delete(Session).where(Session.session_id.in_(sessions)))
        await db.execute(delete(RagChunk).where(RagChunk.source_material_id == material))
        await db.commit()
    await _cleanup_material(factory, material, question)


def plan_body(ids, selected=True):
    return {
        "selected_only": selected,
        "question_ids": [str(q) for q in ids],
        "reviewed_confirmed": True,
    }


async def test_explicit_lessons_copy_the_same_bank_question_without_claiming_it(lesson):
    client, factory, owner, material, question, (first, second) = lesson
    principal = Principal(user_id=owner, role=Role.LECTURER, email="owner@example.test")

    async def save(sid):
        async with factory() as db:
            return await question_plan.save_plan(
                db, principal, sid, QuestionPlanIn(**plan_body([question]))
            )

    a, b = await asyncio.wait_for(asyncio.gather(save(first), save(second)), timeout=5)
    assert a.items[0].id != b.items[0].id != question
    assert a.items[0].source_slide == b.items[0].source_slide
    async with factory() as db:
        bank = await db.get(Question, question)
        assert bank.status == "staged" and bank.session_id is None
        one, two = await db.get(Session, first), await db.get(Session, second)
        repo = SessionRepository(db)
        assert [
            q.question_id for q in (await repo.list_deliverable(one, limit=20, offset=0))[0]
        ] == [a.items[0].id]
        assert [
            q.question_id for q in (await repo.list_deliverable(two, limit=20, offset=0))[0]
        ] == [b.items[0].id]
        # Named delivery cannot reach the shared bank or the other lesson's copy.
        for invalid in [question, b.items[0].id]:
            assert (
                await repo.claim_for_delivery(
                    one,
                    invalid,
                    delivered_at=datetime.now(UTC),
                    closes_at=datetime.now(UTC),
                    window_seconds=30,
                )
                is None
            )
        used = await repo.claim_for_delivery(
            one,
            a.items[0].id,
            delivered_at=datetime.now(UTC),
            closes_at=datetime.now(UTC),
            window_seconds=30,
        )
        assert used is not None
        assert await repo.count_deliverable(one) == 0  # no fallback to the shared bank
        assert await repo.count_deliverable(two) == 1
        await db.commit()
    # A delivery remains immutable, including through back-to-review.
    assert (
        client.patch(
            f"/api/v1/materials/{material}/questions/{a.items[0].id}", json={"status": "draft"}
        ).status_code
        == 409
    )
    async with factory() as db:
        snapshot = await db.get(Question, a.items[0].id)
        assert snapshot.status == "delivered" and snapshot.session_id == first


async def test_empty_selection_never_falls_back_and_reset_restores_legacy_bank(lesson):
    client, factory, _, _, question, (sid, _) = lesson
    url = f"/api/v1/sessions/{sid}/question-plan"
    empty = client.put(url, json=plan_body([]))
    assert empty.status_code == 200, empty.text
    assert empty.headers["cache-control"] == "no-store"
    async with factory() as db:
        assert await SessionRepository(db).count_deliverable(await db.get(Session, sid)) == 0
    assert client.get(f"/api/v1/sessions/{sid}/readiness").json()["deliverable_questions"] == 0
    assert client.put(url, json=plan_body([], selected=False)).status_code == 200
    async with factory() as db:
        available, total = await SessionRepository(db).list_deliverable(
            await db.get(Session, sid), limit=20, offset=0
        )
        assert total == 1 and [q.question_id for q in available] == [question]


async def test_plan_replacement_preserves_original_and_rejects_invalid_scopes(lesson, app):
    client, factory, owner, material, question, (sid, _) = lesson
    url = f"/api/v1/sessions/{sid}/question-plan"
    created = client.put(url, json=plan_body([question])).json()
    copy_id = UUID(created["items"][0]["id"])
    assert created["items"][0]["source_question_id"] == str(question)
    assert client.put(url, json=plan_body([copy_id, question])).status_code == 422
    assert client.get(url).json()["items"] == created["items"]
    assert client.put(url, json=plan_body([copy_id])).json()["items"][0]["id"] == str(copy_id)
    # Invalid source ids fail atomically and leave the existing selection intact.
    assert client.put(url, json=plan_body([uuid4()])).status_code == 404
    assert client.get(url).json()["items"][0]["id"] == str(copy_id)
    other_owner = uuid4()
    foreign_material, foreign_question = await _seed_question(
        factory, uploaded_by=other_owner, status="staged"
    )
    try:
        assert client.put(url, json=plan_body([foreign_question])).status_code == 404
        _as(app, other_owner, Role.LECTURER, "other@example.test")
        assert client.get(url).status_code == 404
        assert client.get(url + "/candidates").status_code == 404
        assert client.put(url, json=plan_body([question])).status_code == 404
    finally:
        await _cleanup_material(factory, foreign_material, foreign_question)
    _as(app, owner, Role.LECTURER, "owner@example.test")
    assert client.put(url, json=plan_body([])).status_code == 200
    async with factory() as db:
        assert await db.get(Question, copy_id) is None
        assert (await db.get(Question, question)).status == "staged"


async def test_candidate_filters_and_sources_are_scoped_and_drafts_are_excluded(lesson):
    client, factory, _, material, question, (sid, _) = lesson
    url = f"/api/v1/sessions/{sid}/question-plan/candidates"
    async with factory() as db:
        q = await db.get(Question, question)
        q.topic = "Planets%_"
        await db.commit()
    page = client.get(url + "?topic=%25_&limit=1")
    assert page.status_code == 200 and page.headers["cache-control"] == "no-store"
    assert page.json()["total"] == 1
    assert page.json()["items"][0]["correct_option"] == 0
    assert client.get(url + "?material=missing").json()["total"] == 0
    assert client.get(url + "?limit=1&offset=1").json()["items"] == []
    async with factory() as db:
        (await db.get(Question, question)).status = "draft"
        await db.commit()
    assert client.get(url).json()["total"] == 0
    assert (
        client.put(f"/api/v1/sessions/{sid}/question-plan", json=plan_body([question])).status_code
        == 404
    )


async def test_start_lock_wins_over_concurrent_plan_edit(lesson):
    _, factory, owner, _, question, (sid, _) = lesson
    principal = Principal(user_id=owner, role=Role.LECTURER, email="owner@example.test")
    async with factory() as starting, factory() as planning:
        live = await SessionRepository(starting).get(sid, for_update=True)
        pending = asyncio.create_task(
            question_plan.save_plan(
                planning, principal, sid, QuestionPlanIn(**plan_body([question]))
            )
        )
        # The blocked edit must re-read the session after start commits.
        await asyncio.sleep(0.05)
        assert not pending.done()
        live.status = "active"
        await starting.commit()
        with pytest.raises(ConflictError):
            await asyncio.wait_for(pending, timeout=5)
        await planning.rollback()


async def test_take_back_lock_prevents_delivery_then_delivery_prevents_take_back(lesson):
    _, factory, owner, _, question, (sid, _) = lesson
    async with factory() as reviewing, factory() as delivering:
        q = await reviewing.get(Question, question)
        await QuestionRepository(reviewing).apply_review(q, status="draft", reviewer_id=owner)
        live = await delivering.get(Session, sid)
        assert (
            await SessionRepository(delivering).claim_for_delivery(
                live,
                question,
                delivered_at=datetime.now(UTC),
                closes_at=datetime.now(UTC),
                window_seconds=30,
            )
            is None
        )
        await reviewing.rollback()
        await delivering.rollback()
    async with factory() as delivering, factory() as reviewing:
        live = await delivering.get(Session, sid)
        await SessionRepository(delivering).claim_for_delivery(
            live,
            question,
            delivered_at=datetime.now(UTC),
            closes_at=datetime.now(UTC),
            window_seconds=30,
        )
        await delivering.commit()
        q = await reviewing.get(Question, question)
        with pytest.raises(ConflictError):
            await QuestionRepository(reviewing).apply_review(q, status="draft", reviewer_id=owner)
        await reviewing.rollback()


@pytest.mark.parametrize("state", ["active", "ended", "cancelled"])
async def test_lesson_selection_is_locked_after_preparation(lesson, state):
    client, factory, _, _, question, (sid, _) = lesson
    async with factory() as db:
        (await db.get(Session, sid)).status = state
        await db.commit()
    assert (
        client.put(f"/api/v1/sessions/{sid}/question-plan", json=plan_body([question])).status_code
        == 409
    )


async def test_manual_sources_are_validated_and_written_answers_remain_markable(lesson):
    client, _, _, material, _, _ = lesson
    url = f"/api/v1/materials/{material}/questions"
    body = {
        "type": "free_text",
        "prompt": "Explain the capital.",
        "reference_answer": "Paris.",
        "key_points": ["Paris"],
        "source_slide": 3,
        "source_excerpt": "Paris is the capital",
    }
    result = client.post(url, json=body)
    assert result.status_code == 201, result.text
    assert result.json()["reference_answer"] == "Paris."
    assert result.json()["key_points"] == ["Paris"]
    assert result.json()["source_slide"] == 3
    assert client.post(url, json={**body, "source_slide": 4}).status_code == 422
    assert (
        client.post(url, json={**body, "source_excerpt": "Fabricated passage"}).status_code == 422
    )
    assert client.post(url, json={**body, "key_points": []}).status_code == 422


async def test_refiled_material_cannot_escape_the_selected_course_boundary(lesson):
    from app.models.course import Course

    client, factory, _, material, question, (sid, _) = lesson
    url = f"/api/v1/sessions/{sid}/question-plan"
    selected = client.put(url, json=plan_body([question])).json()["items"][0]["id"]
    async with factory() as db:
        mat = await db.get(Material, material)
        original_course = mat.course_id
        foreign_course = Course(code=f"PLAN{uuid4().hex[:8]}", name="Other course")
        db.add(foreign_course)
        await db.flush()
        foreign_id = foreign_course.id
        mat.course_id = foreign_id
        await db.commit()
    try:
        assert client.get(url + "/candidates").json()["total"] == 0
        assert client.put(url, json=plan_body([selected])).status_code == 404
        assert client.put(url, json=plan_body([question])).status_code == 404
        async with factory() as db:
            live = await db.get(Session, sid)
            assert await SessionRepository(db).count_deliverable(live) == 0
            assert await SessionRepository(db).materials_for(live) == []
    finally:
        async with factory() as db:
            (await db.get(Material, material)).course_id = original_course
            await db.flush()
            await db.execute(delete(Course).where(Course.id == foreign_id))
            await db.commit()
