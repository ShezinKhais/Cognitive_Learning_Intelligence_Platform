"""Regenerating a draft question from the review screen.

Owner: Cyber 2 with AI 1, Phase 2. Runs the route against a migrated database
with the model replaced by a stand-in, so what is checked is the rules: only
the uploader's drafts can be replaced, the old draft is kept as rejected, and a
generator that fails changes nothing.
"""

from __future__ import annotations

from uuid import UUID, uuid4

import pytest
from sqlalchemy import select, text

from app.api.deps import get_principal
from app.api.v1 import content
from app.models.question import Question
from app.models.rag_chunk import RagChunk
from app.schemas.content import Difficulty, QuestionType
from app.schemas.identity import Role
from app.services.material_seams import DraftQuestion

from .test_question_review import _as, _cleanup, _seed_question, db_client  # noqa: F401

PAGE_TEXT = "Paris is the capital of France. Lyon is known for its cuisine."


def replacement(prompt: str = "Which city is the capital of France?") -> DraftQuestion:
    return DraftQuestion(
        type=QuestionType.MCQ,
        difficulty=Difficulty.EASY,
        prompt=prompt,
        options=("Paris", "Lyon", "Nice", "Lille"),
        correct_option=0,
        source_slide=1,
        source_excerpt="Paris is the capital of France",
    )


class StandInGenerator:
    model = "test-generate"

    def __init__(self, drafts=None, fails: bool = False) -> None:
        self.drafts = drafts if drafts is not None else [replacement()]
        self.fails = fails
        self.seen_chunks = []

    async def generate(self, material_id, chunks, count=None):
        self.seen_chunks = list(chunks)
        if self.fails:
            raise TimeoutError("model server did not answer")
        return self.drafts


async def _with_chunk(session_factory, material_id: UUID) -> None:
    async with session_factory() as seed, seed.begin():
        seed.add(
            RagChunk(
                source_material_id=material_id, chunk_index=0, source_page=1, chunk_text=PAGE_TEXT
            )
        )


async def _tidy(session_factory, material_id: UUID, question_id: UUID) -> None:
    async with session_factory() as tidy, tidy.begin():
        await tidy.execute(
            text("delete from question where source_material_id = :m and question_id != :q"),
            {"m": material_id, "q": question_id},
        )
        await tidy.execute(
            text("delete from rag_chunk where source_material_id = :m"), {"m": material_id}
        )
    await _cleanup(session_factory, question_id)


@pytest.fixture
def generator(monkeypatch: pytest.MonkeyPatch):
    def install(stand_in: StandInGenerator) -> StandInGenerator:
        monkeypatch.setattr(content, "get_question_generator", lambda: stand_in)
        return stand_in

    return install


async def test_a_draft_is_replaced_and_kept_as_rejected(db_client, app, generator):  # noqa: F811
    test_client, session_factory = db_client
    lecturer = uuid4()
    material_id, question_id = await _seed_question(session_factory, uploaded_by=lecturer)
    await _with_chunk(session_factory, material_id)
    stand_in = generator(StandInGenerator())
    try:
        _as(app, lecturer, Role.LECTURER, "lecturer@uni.test")

        response = test_client.post(
            f"/api/v1/materials/{material_id}/questions/{question_id}:regenerate"
        )

        assert response.status_code == 201
        body = response.json()
        assert body["status"] == "draft"
        assert body["prompt"] == "Which city is the capital of France?"
        assert body["id"] != str(question_id)
        assert [chunk.chunk_text for chunk in stand_in.seen_chunks] == [PAGE_TEXT]
        async with session_factory() as check:
            old = await check.get(Question, question_id)
            assert old.status == "rejected"
            assert old.reviewed_by == lecturer
            listed = test_client.get(f"/api/v1/materials/{material_id}/questions").json()
            assert {item["status"] for item in listed["items"]} == {"draft", "rejected"}
    finally:
        await _tidy(session_factory, material_id, question_id)
        app.dependency_overrides.pop(get_principal, None)


async def test_an_approved_question_is_not_replaced(db_client, app, generator):  # noqa: F811
    test_client, session_factory = db_client
    lecturer = uuid4()
    material_id, question_id = await _seed_question(
        session_factory, uploaded_by=lecturer, status="approved"
    )
    await _with_chunk(session_factory, material_id)
    generator(StandInGenerator())
    try:
        _as(app, lecturer, Role.LECTURER, "lecturer@uni.test")

        response = test_client.post(
            f"/api/v1/materials/{material_id}/questions/{question_id}:regenerate"
        )

        assert response.status_code == 409
    finally:
        await _tidy(session_factory, material_id, question_id)
        app.dependency_overrides.pop(get_principal, None)


async def test_another_lecturer_cannot_regenerate(db_client, app, generator):  # noqa: F811
    test_client, session_factory = db_client
    owner = uuid4()
    material_id, question_id = await _seed_question(session_factory, uploaded_by=owner)
    await _with_chunk(session_factory, material_id)
    stand_in = generator(StandInGenerator())
    try:
        _as(app, uuid4(), Role.LECTURER, "someone@uni.test")

        response = test_client.post(
            f"/api/v1/materials/{material_id}/questions/{question_id}:regenerate"
        )

        assert response.status_code == 403
        assert stand_in.seen_chunks == []
    finally:
        await _tidy(session_factory, material_id, question_id)
        app.dependency_overrides.pop(get_principal, None)


@pytest.mark.parametrize(
    "stand_in",
    [
        StandInGenerator(fails=True),
        # Only a repeat of the question being replaced came back.
        StandInGenerator(drafts=[replacement("What is the capital of France?")]),
    ],
)
async def test_nothing_changes_when_no_replacement_can_be_made(
    db_client,  # noqa: F811
    app,
    generator,
    stand_in,
):
    test_client, session_factory = db_client
    lecturer = uuid4()
    material_id, question_id = await _seed_question(session_factory, uploaded_by=lecturer)
    await _with_chunk(session_factory, material_id)
    generator(stand_in)
    try:
        _as(app, lecturer, Role.LECTURER, "lecturer@uni.test")

        response = test_client.post(
            f"/api/v1/materials/{material_id}/questions/{question_id}:regenerate"
        )

        assert response.status_code == 503
        async with session_factory() as check:
            rows = (
                (
                    await check.execute(
                        select(Question).where(Question.source_material_id == material_id)
                    )
                )
                .scalars()
                .all()
            )
            assert [(row.question_id, row.status) for row in rows] == [(question_id, "draft")]
    finally:
        await _tidy(session_factory, material_id, question_id)
        app.dependency_overrides.pop(get_principal, None)
