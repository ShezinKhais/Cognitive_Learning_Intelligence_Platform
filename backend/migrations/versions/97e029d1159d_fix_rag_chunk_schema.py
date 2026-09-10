"""fix rag chunk schema

Revision ID: 97e029d1159d
Revises: f16a4d356f03
Create Date: 2026-08-14 14:27:15.886493

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from pgvector.sqlalchemy import Vector

# revision identifiers, used by Alembic.
revision: str = "97e029d1159d"
down_revision: str | Sequence[str] | None = "f16a4d356f03"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.execute(
        sa.text(
            """
            DO $$
            BEGIN
                IF EXISTS (SELECT 1 FROM rag_chunk) THEN
                    RAISE EXCEPTION
                        'rag_chunk must be empty before changing its schema';
                END IF;
            END
            $$;
            """
        )
    )

    op.alter_column(
        "rag_chunk",
        "embedding_vector",
        existing_type=Vector(dim=1536),
        type_=Vector(dim=768),
        existing_nullable=False,
        nullable=True,
        postgresql_using="embedding_vector::vector(768)",
    )
    op.alter_column(
        "rag_chunk",
        "embedding_model",
        existing_type=sa.String(length=100),
        existing_nullable=False,
        nullable=True,
    )
    op.add_column(
        "rag_chunk",
        sa.Column("chunk_index", sa.Integer(), nullable=False),
    )
    op.add_column(
        "rag_chunk",
        sa.Column("source_page", sa.Integer(), nullable=True),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.execute(
        sa.text(
            """
            DO $$
            BEGIN
                IF EXISTS (SELECT 1 FROM rag_chunk) THEN
                    RAISE EXCEPTION
                        'rag_chunk must be empty before reverting its schema';
                END IF;
            END
            $$;
            """
        )
    )

    op.drop_column("rag_chunk", "source_page")
    op.drop_column("rag_chunk", "chunk_index")
    op.alter_column(
        "rag_chunk",
        "embedding_model",
        existing_type=sa.String(length=100),
        existing_nullable=True,
        nullable=False,
    )
    op.alter_column(
        "rag_chunk",
        "embedding_vector",
        existing_type=Vector(dim=768),
        type_=Vector(dim=1536),
        existing_nullable=True,
        nullable=False,
        postgresql_using="embedding_vector::vector(1536)",
    )
