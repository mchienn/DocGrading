"""Persist bounded PDF validation diagnostics on document versions."""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "20260918_0016"
down_revision: str | None = "20260916_0015"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_DEFAULT_REPORT = (
    "jsonb_build_object("
    "'schema_version', 1, "
    "'outcome', 'NOT_RUN', "
    "'diagnostics', '[]'::jsonb)"
)


def upgrade() -> None:
    op.execute(sa.text("SET search_path TO public"))
    op.add_column(
        "document_versions",
        sa.Column(
            "validation_report",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text(_DEFAULT_REPORT),
            nullable=False,
        ),
        schema="public",
    )
    op.create_check_constraint(
        "ck_document_versions_validation_report_object",
        "document_versions",
        "jsonb_typeof(validation_report) = 'object'",
        schema="public",
    )


def downgrade() -> None:
    op.execute(sa.text("SET search_path TO public"))
    op.drop_constraint(
        "ck_document_versions_validation_report_object",
        "document_versions",
        type_="check",
        schema="public",
    )
    op.drop_column("document_versions", "validation_report", schema="public")
