"""Tests that need a real Postgres.

They skip when no database is reachable so the suite still runs on a machine
without Docker started. CI always has one, so these always execute there.

This is the pattern for anything touching the schema: take the `db` fixture,
and let it skip rather than fail when the database is absent.
"""

import pytest
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.core.config import get_settings
from app.models.ai_model_run import AIModelRun
from app.models.consent import Consent
from app.models.course import Course
from app.models.embedding import Embedding
from app.models.extraction_element import ExtractionElement
from app.models.material import Material
from app.models.material_processing_status import MaterialProcessingStatus
from app.models.rag_chunk import RagChunk
from app.models.user import User

REQUIRED_EXTENSIONS = {"vector", "pg_trgm", "uuid-ossp"}


def test_rag_chunk_model_matches_content_pipeline() -> None:
    columns = RagChunk.__table__.c

    assert columns.embedding_vector.type.dim == get_settings().embedding_dim
    assert columns.embedding_vector.nullable is True
    assert columns.embedding_model.nullable is True
    assert columns.chunk_index.nullable is False
    assert columns.source_page.nullable is True


def test_material_course_reference_matches_course_model() -> None:
    course_id = Material.__table__.c.course_id

    assert course_id.type.as_uuid is True
    assert course_id.nullable is True
    assert course_id.index is True
    assert {key.target_fullname for key in course_id.foreign_keys} == {"course.id"}


def test_course_code_is_unique_and_indexed() -> None:
    code = Course.__table__.c.code

    assert code.unique is True
    assert code.index is True


def test_user_model_supports_auth_contract() -> None:
    columns = User.__table__.c
    constraint_names = {constraint.name for constraint in User.__table__.constraints}

    assert columns.password_hash.nullable is True
    assert columns.active.nullable is False
    assert columns.active.server_default is not None
    assert "ck_user_role" in constraint_names
    assert isinstance(User.id, property)
    assert isinstance(User.full_name, property)


def test_models_package_exports_user() -> None:
    from app.models import User as ExportedUser

    assert ExportedUser is User


def test_consent_model_supports_granular_revocable_consent() -> None:
    columns = Consent.__table__.c
    constraint_names = {constraint.name for constraint in Consent.__table__.constraints}

    assert columns.user_id.nullable is False
    assert {key.target_fullname for key in columns.user_id.foreign_keys} == {"user.user_id"}
    assert columns.consent_type.nullable is False
    assert columns.granted.nullable is False
    assert columns.recorded_at.nullable is False
    assert "ck_consent_type" in constraint_names
    assert "uq_consent_user_type" in constraint_names


def test_extraction_elements_are_traceable_by_material() -> None:
    columns = ExtractionElement.__table__.c
    constraint_names = {constraint.name for constraint in ExtractionElement.__table__.constraints}

    assert {key.target_fullname for key in columns.source_material_id.foreign_keys} == {
        "source_material.id"
    }
    assert columns.source_material_id.index is True
    assert columns.element_index.nullable is False
    assert columns.element_type.nullable is False
    assert columns.metadata.nullable is False
    assert "uq_extraction_element_material_index" in constraint_names


def test_processing_status_matches_material_progress_contract() -> None:
    columns = MaterialProcessingStatus.__table__.c
    constraint_names = {
        constraint.name for constraint in MaterialProcessingStatus.__table__.constraints
    }

    assert {key.target_fullname for key in columns.source_material_id.foreign_keys} == {
        "source_material.id"
    }
    assert columns.stage.nullable is False
    assert columns.percent.nullable is False
    assert columns.recorded_at.nullable is False
    assert "ck_material_processing_status_stage" in constraint_names
    assert "ck_material_processing_status_percent" in constraint_names


def test_ai_model_runs_are_traceable_by_material() -> None:
    columns = AIModelRun.__table__.c
    constraint_names = {constraint.name for constraint in AIModelRun.__table__.constraints}

    assert {key.target_fullname for key in columns.source_material_id.foreign_keys} == {
        "source_material.id"
    }
    assert columns.operation.nullable is False
    assert columns.model_name.nullable is False
    assert columns.status.nullable is False
    assert "ck_ai_model_run_status" in constraint_names


def test_embeddings_are_traceable_by_chunk_and_model_run() -> None:
    columns = Embedding.__table__.c
    constraint_names = {constraint.name for constraint in Embedding.__table__.constraints}

    assert {key.target_fullname for key in columns.chunk_id.foreign_keys} == {"rag_chunk.chunk_id"}
    assert {key.target_fullname for key in columns.model_run_id.foreign_keys} == {
        "ai_model_run.run_id"
    }
    assert columns.vector.type.dim == get_settings().embedding_dim
    assert columns.vector.nullable is False
    assert "uq_embedding_chunk_model" in constraint_names


@pytest.fixture
async def db():
    """A session on an engine built for this test only.

    The application engine is module-level and binds to whichever event loop
    first uses it. pytest-asyncio gives each test a fresh loop, so sharing it
    hands the second test a connection from a pool tied to a dead loop. NullPool
    and a per-test engine avoid that entirely.
    """
    engine = create_async_engine(get_settings().database_url, poolclass=NullPool)
    try:
        async with engine.connect() as conn:
            await conn.execute(text("select 1"))
    except Exception as exc:
        await engine.dispose()
        pytest.skip(f"no database reachable ({type(exc).__name__})")

    session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with session_factory() as session:
        yield session
        await session.rollback()

    await engine.dispose()


async def test_extensions_are_installed(db: AsyncSession) -> None:
    """A database without pgvector looks fine until the first embedding insert."""
    installed = (await db.execute(text("select extname from pg_extension"))).scalars().all()
    missing = REQUIRED_EXTENSIONS - set(installed)
    assert not missing, f"missing extensions: {sorted(missing)}"


async def test_vector_column_round_trips(db: AsyncSession) -> None:
    """Proves pgvector is usable, not merely present."""
    await db.execute(text("create temporary table _probe (id int primary key, v vector(3))"))
    await db.execute(text("insert into _probe values (1, '[1,2,3]')"))

    distance = (
        await db.execute(text("select v <-> '[1,2,4]' from _probe where id = 1"))
    ).scalar_one()

    assert distance == pytest.approx(1.0)


async def test_phase_two_pipeline_is_traceable_by_material(db: AsyncSession) -> None:
    material = Material(
        filename="week-3.txt",
        content_type="text/plain",
        size_bytes=12,
        status="processing",
    )
    db.add(material)
    await db.flush()

    extraction = ExtractionElement(
        source_material_id=material.id,
        element_index=0,
        element_type="paragraph",
        content="Stored source content",
        source_page=1,
        metadata_json={"section": "Introduction"},
    )
    progress = MaterialProcessingStatus(
        source_material_id=material.id,
        stage="embedding",
        percent=75,
        message="Creating vectors",
    )
    model_run = AIModelRun(
        source_material_id=material.id,
        operation="embedding",
        provider="test",
        model_name="test-embedding-model",
        status="completed",
        parameters={},
    )
    chunk = RagChunk(
        source_material_id=material.id,
        chunk_index=0,
        source_page=1,
        chunk_text="Stored source content",
    )
    db.add_all([extraction, progress, model_run, chunk])
    await db.flush()

    embedding = Embedding(
        chunk_id=chunk.chunk_id,
        model_run_id=model_run.run_id,
        vector=[0.0] * get_settings().embedding_dim,
        model_name=model_run.model_name,
    )
    db.add(embedding)
    await db.flush()

    stored_progress = (
        await db.execute(
            select(MaterialProcessingStatus).where(
                MaterialProcessingStatus.source_material_id == material.id
            )
        )
    ).scalar_one()
    stored_extraction = (
        await db.execute(
            select(ExtractionElement).where(ExtractionElement.source_material_id == material.id)
        )
    ).scalar_one()
    stored_embedding = (
        await db.execute(
            select(Embedding)
            .join(RagChunk, Embedding.chunk_id == RagChunk.chunk_id)
            .where(RagChunk.source_material_id == material.id)
        )
    ).scalar_one()

    assert stored_progress.stage == "embedding"
    assert stored_extraction.content == "Stored source content"
    assert stored_embedding.model_run_id == model_run.run_id


async def test_trigram_similarity_works(db: AsyncSession) -> None:
    """pg_trgm backs matching Teams display names against the admin roster."""
    score = (await db.execute(text("select similarity('Mike Chen', 'Michael Chen')"))).scalar_one()
    assert 0.0 < score < 1.0


async def test_readiness_passes_when_the_database_is_up(db: AsyncSession, client) -> None:
    """The 503 path is covered elsewhere; this covers the healthy one."""
    response = client.get("/api/v1/ready")
    assert response.status_code == 200

    body = response.json()
    postgres = next(d for d in body["dependencies"] if d["name"] == "postgres")
    assert postgres["ok"] is True
    assert postgres["latency_ms"] is not None
