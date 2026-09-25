"""Add document_summaries cache for RAG submission summaries."""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "20260925_0018"
down_revision: str | None = "20260924_0017"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(sa.text("SET search_path TO public"))

    timestamp = sa.DateTime(timezone=True)
    uuid_type = postgresql.UUID(as_uuid=True)

    op.create_table(
        "document_summaries",
        sa.Column("id", uuid_type, nullable=False),
        sa.Column(
            "created_at", timestamp, server_default=sa.text("now()"), nullable=False
        ),
        sa.Column(
            "updated_at", timestamp, server_default=sa.text("now()"), nullable=False
        ),
        sa.Column("document_version_id", uuid_type, nullable=False),
        sa.Column("summary", sa.Text(), nullable=False),
        sa.Column("model_version", sa.Text(), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_document_summaries"),
        sa.UniqueConstraint(
            "document_version_id",
            name="uq_document_summaries_document_version_id",
        ),
        sa.CheckConstraint(
            "length(btrim(summary)) > 0",
            name="ck_document_summaries_summary_not_blank",
        ),
        sa.CheckConstraint(
            "length(btrim(model_version)) > 0",
            name="ck_document_summaries_model_version_not_blank",
        ),
        sa.ForeignKeyConstraint(
            ["document_version_id"],
            ["public.document_versions.id"],
            name="fk_document_summaries_document_version_id_document_versions",
            ondelete="CASCADE",
        ),
        schema="public",
    )


def downgrade() -> None:
    op.execute(sa.text("SET search_path TO public"))
    op.drop_table("document_summaries", schema="public")
