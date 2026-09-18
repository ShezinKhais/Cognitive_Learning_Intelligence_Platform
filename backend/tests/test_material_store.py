"""The material store against a migrated database.

Owner: BBIS, Phase 2. Every write the pipeline makes goes through this store,
so these run the real SQL: an accepted upload gets its row, each stage lands in
the history, and a finished material's elements, chunks, vectors, drafts and
model runs arrive together, visible to the lecturer who uploaded it. Skipped
when no database is reachable, as the other database tests are.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator

import pytest
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.core.config import get_settings
from app.models.ai_model_run import AIModelRun
from app.models.extraction_element import ExtractionElement
from app.models.question import Question
from app.models.rag_chunk import RagChunk
from app.models.user import User
from app.repositories.material_repository import MaterialRepository
from app.repositories.question_repository import QuestionRepository
from app.schemas.content import Difficulty, QuestionType
from app.schemas.events import MaterialStage
from app.services.extraction import ContentChunk, ExtractedElement, ProcessingResult
from app.services.jobs import JobStatus
from app.services.material_pages import page_previews
from app.services.material_seams import (
    CompletedMaterial,
    DraftQuestion,
    EmbeddingBatch,
    ModelRun,
)
from app.services.material_store import DatabaseMaterialStore
from app.services.storage import StoredFile


@pytest.fixture
async def sessions() -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    engine = create_async_engine(get_settings().database_url, poolclass=NullPool)
    try:
        async with engine.connect() as connection:
            await connection.execute(text("select 1"))
    except Exception as exc:
        await engine.dispose()
        pytest.skip(f"no database reachable ({type(exc).__name__})")
    yield async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    await engine.dispose()


@pytest.fixture
async def lecturer(sessions) -> AsyncIterator[uuid.UUID]:
    user_id = uuid.uuid4()
    async with sessions() as session, session.begin():
        session.add(
            User(user_id=user_id, name="Store Lecturer", role="lecturer", email=f"{user_id}@t.test")
        )
    yield user_id
    # question and rag_chunk do not cascade from source_material; the other
    # material tables do.
    owned = "select id from source_material where uploaded_by_user_id = :u"
    async with sessions() as session, session.begin():
        for statement in (
            f"delete from question where source_material_id in ({owned})",
            f"delete from rag_chunk where source_material_id in ({owned})",
            "delete from source_material where uploaded_by_user_id = :u",
            'delete from "user" where user_id = :u',
        ):
            await session.execute(text(statement), {"u": user_id})


def _stored(material_id: uuid.UUID) -> StoredFile:
    return StoredFile(
        material_id=material_id,
        filename="Week 3.pdf",
        extension="pdf",
        size_bytes=2048,
        key=f"{material_id}.pdf",
    )


def _completed(material_id: uuid.UUID) -> CompletedMaterial:
    dim = get_settings().embedding_dim
    elements = [
        ExtractedElement("heading", "Transfer learning", 1),
        ExtractedElement("text", "The base layers are frozen during fine-tuning.", 1),
        ExtractedElement("image", "[image]", 2),
    ]
    chunks = [
        ContentChunk(
            chunk_id=uuid.uuid4(),
            chunk_index=0,
            material_id=material_id,
            chunk_text="Transfer learning. The base layers are frozen during fine-tuning.",
            source_page=1,
        )
    ]
    draft = DraftQuestion(
        type=QuestionType.MCQ,
        difficulty=Difficulty.MEDIUM,
        prompt="What happens to the base layers?",
        options=("They are frozen", "They are deleted", "They are doubled", "They move"),
        correct_option=0,
        topic="Transfer learning",
        source_slide=1,
        source_excerpt="The base layers are frozen",
    )
    return CompletedMaterial(
        status=JobStatus.for_stage(material_id, MaterialStage.DONE, "1 question(s) ready."),
        result=ProcessingResult(
            material_id=material_id,
            elements=elements,
            chunks=chunks,
            page_count=2,
            parser_used="pypdf",
        ),
        embeddings=EmbeddingBatch(vectors=[[0.25] * dim], model="nomic-embed-text", dim=dim),
        questions=(draft,),
        warnings=("Page 2 is mostly images.",),
        model_runs=(
            ModelRun("embedding", "nomic-embed-text", True),
            ModelRun("question_generation", "qwen2.5", True),
        ),
    )


async def test_an_accepted_upload_has_a_pending_row_under_its_own_id(sessions, lecturer) -> None:
    store = DatabaseMaterialStore(lambda: sessions)
    material_id = uuid.uuid4()

    await store.record_accepted(_stored(material_id), lecturer)

    async with sessions() as session:
        row = await MaterialRepository(session).get_by_id(material_id, uploaded_by_user_id=lecturer)
    assert row is not None
    assert row.status == "pending"
    assert row.content_type == "application/pdf"
    assert row.warnings == []
    # Read back with its time zone, as the upload response gives it; a bare
    # timestamp is taken as local time by every client not on UTC.
    assert row.uploaded_at.utcoffset() is not None


async def test_a_finished_material_is_recorded_whole_and_reviewable(sessions, lecturer) -> None:
    store = DatabaseMaterialStore(lambda: sessions)
    material_id = uuid.uuid4()
    await store.record_accepted(_stored(material_id), lecturer)
    for stage in (MaterialStage.VALIDATING, MaterialStage.EXTRACTING):
        await store.record_progress(JobStatus.for_stage(material_id, stage))

    await store.record_completed(_completed(material_id))

    async with sessions() as session:
        repository = MaterialRepository(session)
        row = await repository.get_by_id(material_id)
        history = await repository.list_status_history(material_id)
        elements = await repository.list_elements(material_id)
        chunks = (
            (
                await session.execute(
                    select(RagChunk).where(RagChunk.source_material_id == material_id)
                )
            )
            .scalars()
            .all()
        )
        runs = (
            (
                await session.execute(
                    select(AIModelRun).where(AIModelRun.source_material_id == material_id)
                )
            )
            .scalars()
            .all()
        )
        questions, total = await QuestionRepository(session).list_owned_by_material(
            material_id, lecturer, is_admin=False, limit=10, offset=0
        )

    assert (row.status, row.page_count, row.chunk_count) == ("completed", 2, 1)
    assert row.warnings == ["Page 2 is mostly images."]
    assert [item.stage for item in history] == ["validating", "extracting", "done"]
    assert [element.element_type for element in elements] == ["heading", "text", "image"]
    assert len(chunks) == 1
    assert chunks[0].embedding_model == "nomic-embed-text"
    assert len(chunks[0].embedding_vector) == get_settings().embedding_dim
    assert sorted(run.operation for run in runs) == ["embedding", "question_generation"]
    # Stored as a draft with no session, and visible to the lecturer who uploaded it.
    assert total == 1
    assert (questions[0].status, questions[0].session_id) == ("draft", None)
    assert questions[0].options == [
        "They are frozen",
        "They are deleted",
        "They are doubled",
        "They move",
    ]


async def test_a_failed_material_keeps_the_message_the_lecturer_was_given(
    sessions, lecturer
) -> None:
    store = DatabaseMaterialStore(lambda: sessions)
    material_id = uuid.uuid4()
    await store.record_accepted(_stored(material_id), lecturer)

    await store.record_failed(
        JobStatus.for_stage(
            material_id, MaterialStage.FAILED, message="x" * 900, error="INTERNAL_ERROR"
        )
    )

    async with sessions() as session:
        row = await MaterialRepository(session).get_by_id(material_id)
    assert row.status == "failed"
    # Bounded to the column rather than failing the write that records a failure.
    assert len(row.error) == 500


async def test_completion_without_an_accepted_row_is_refused(sessions) -> None:
    """A bug upstream, and writing chunks against nothing would hide it."""
    store = DatabaseMaterialStore(lambda: sessions)

    with pytest.raises(LookupError):
        await store.record_completed(_completed(uuid.uuid4()))


async def test_nothing_is_half_written_when_the_completion_fails(sessions, lecturer) -> None:
    store = DatabaseMaterialStore(lambda: sessions)
    material_id = uuid.uuid4()
    await store.record_accepted(_stored(material_id), lecturer)
    completed = _completed(material_id)
    # A vector of the wrong width fails the rag_chunk insert.
    broken = CompletedMaterial(
        status=completed.status,
        result=completed.result,
        embeddings=EmbeddingBatch(vectors=[[0.1] * 3], model="bad", dim=3),
        questions=completed.questions,
        warnings=completed.warnings,
    )

    with pytest.raises(Exception):  # noqa: B017 - the driver's error type is not ours to pin
        await store.record_completed(broken)

    async with sessions() as session:
        row = await MaterialRepository(session).get_by_id(material_id)
        leftovers = (
            (
                await session.execute(
                    select(ExtractionElement).where(
                        ExtractionElement.source_material_id == material_id
                    )
                )
            )
            .scalars()
            .all()
        )
        questions = (
            (
                await session.execute(
                    select(Question).where(Question.source_material_id == material_id)
                )
            )
            .scalars()
            .all()
        )
    assert row.status == "pending"
    assert leftovers == []
    assert questions == []


def test_page_previews_flag_thin_and_image_heavy_pages() -> None:
    class Element:
        def __init__(self, element_type: str, content: str, page: int | None) -> None:
            self.element_type, self.content, self.source_page = element_type, content, page

    words = " ".join(["normalisation"] * 40)
    previews = page_previews(
        [
            Element("heading", "Title slide", 1),
            Element("text", words, 2),
            Element("image", "[image]", 3),
            Element("image", "[image]", 3),
            Element("text", "A caption.", 3),
            Element("text", "No page number.", None),
        ]
    )

    by_page = {preview.page_number: preview for preview in previews}
    assert sorted(by_page) == [1, 2, 3]
    assert by_page[1].is_thin and not by_page[1].is_visual_heavy
    assert "No page number." in by_page[1].text
    assert not by_page[2].is_thin and by_page[2].word_count == 40
    assert by_page[3].is_visual_heavy and by_page[3].visual_element_count == 2
