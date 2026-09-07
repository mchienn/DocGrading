"""Add durable document IR storage for parsed PDF structure.

SC-1: both directions pin ``search_path`` before any operation.
SC-2: this revision never touches append-only audit triggers.
SC-3: all application objects and foreign-key targets are schema-qualified.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "20260902_0008"
down_revision: str | None = "20260829_0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(sa.text("SET search_path TO public"))
    op.create_table(
        "document_irs",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "document_version_id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
        ),
        sa.Column(
            "schema_version",
            sa.Integer(),
            server_default=sa.text("1"),
            nullable=False,
        ),
        sa.Column(
            "parser_version",
            sa.String(length=64),
            nullable=False,
        ),
        sa.Column(
            "content",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.CheckConstraint(
            "schema_version > 0",
            name="ck_document_irs_schema_version_positive",
        ),
        sa.CheckConstraint(
            "length(btrim(parser_version)) > 0 AND parser_version !~ '^[[:space:]]*$'",
            name="ck_document_irs_parser_version_not_blank",
        ),
        sa.CheckConstraint(
            "jsonb_typeof(content) = 'object'",
            name="ck_document_irs_content_object",
        ),
        sa.ForeignKeyConstraint(
            ["document_version_id"],
            ["public.document_versions.id"],
            name="fk_document_irs_document_version_id_document_versions",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_document_irs"),
        sa.UniqueConstraint(
            "document_version_id",
            name="uq_document_irs_document_version_id",
        ),
        schema="public",
    )


def downgrade() -> None:
    op.execute(sa.text("SET search_path TO public"))
    op.drop_table("document_irs", schema="public")
