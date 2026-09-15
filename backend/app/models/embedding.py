"""Versioned chunk embeddings produced by traceable AI model runs."""

import uuid
from datetime import datetime

from pgvector.sqlalchemy import Vector
from sqlalchemy import DateTime, ForeignKey, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from app.core.config import get_settings
from app.core.database import Base


class Embedding(Base):
    __tablename__ = "embedding"
    __table_args__ = (
        UniqueConstraint(
            "chunk_id",
            "model_name",
            name="uq_embedding_chunk_model",
        ),
    )

    embedding_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    chunk_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("rag_chunk.chunk_id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    model_run_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("ai_model_run.run_id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    vector: Mapped[list[float]] = mapped_column(
        Vector(get_settings().embedding_dim),
        nullable=False,
    )
    model_name: Mapped[str] = mapped_column(String(150), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
