"""Add pgvector extension and document_chunks table for RAG."""

from collections.abc import Sequence

import sqlalchemy as sa
from pgvector.sqlalchemy import Vector
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "20260924_0017"
down_revision: str | None = "20260918_0016"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# text-embedding-3-small (OpenAI) dùng 1536 chiều — nếu sau này đổi provider
# embedding có số chiều khác, cần một migration riêng để ALTER COLUMN.
EMBEDDING_DIMENSIONS = 1536


def upgrade() -> None:
    op.execute(sa.text("SET search_path TO public"))
    op.execute(sa.text("CREATE EXTENSION IF NOT EXISTS vector"))

    timestamp = sa.DateTime(timezone=True)
    uuid_type = postgresql.UUID(as_uuid=True)

    op.create_table(
        "document_chunks",
        sa.Column("id", uuid_type, nullable=False),
        sa.Column(
            "created_at", timestamp, server_default=sa.text("now()"), nullable=False
        ),
        sa.Column(
            "updated_at", timestamp, server_default=sa.text("now()"), nullable=False
        ),
        sa.Column("document_version_id", uuid_type, nullable=False),
        sa.Column("chunk_index", sa.Integer(), nullable=False),
        sa.Column("section_path", sa.Text(), nullable=True),
        sa.Column("page_start", sa.Integer(), nullable=False),
        sa.Column("page_end", sa.Integer(), nullable=False),
        sa.Column("paragraph_ids", postgresql.JSONB(), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("token_count", sa.Integer(), nullable=False),
        sa.Column("embedding", Vector(EMBEDDING_DIMENSIONS), nullable=True),
        sa.PrimaryKeyConstraint("id", name="pk_document_chunks"),
        sa.UniqueConstraint(
            "document_version_id",
            "chunk_index",
            name="uq_document_chunks_version_chunk_index",
        ),
        sa.CheckConstraint(
            "chunk_index >= 0", name="ck_document_chunks_chunk_index_nonnegative"
        ),
        sa.CheckConstraint(
            "page_start > 0 AND page_end >= page_start",
            name="ck_document_chunks_page_range",
        ),
        sa.CheckConstraint(
            "token_count > 0", name="ck_document_chunks_token_count_positive"
        ),
        sa.ForeignKeyConstraint(
            ["document_version_id"],
            ["public.document_versions.id"],
            name="fk_document_chunks_document_version_id_document_versions",
            ondelete="CASCADE",
        ),
        schema="public",
    )
    op.create_index(
        "ix_document_chunks_document_version_id",
        "document_chunks",
        ["document_version_id"],
        schema="public",
    )


def downgrade() -> None:
    op.execute(sa.text("SET search_path TO public"))
    op.drop_index(
        "ix_document_chunks_document_version_id",
        table_name="document_chunks",
        schema="public",
    )
    op.drop_table("document_chunks", schema="public")