"""Add upload idempotency and the durable T-009 job lifecycle.

SC-1: both directions pin ``search_path`` before any operation.
SC-2: this revision never touches the append-only audit triggers.
SC-3: all application objects, enum casts, and foreign-key targets are public.
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20260828_0006"
down_revision: str | None = "20260828_0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _replace_job_enum(*, new_values: str, expression: str) -> None:
    op.execute(
        sa.text(
            "ALTER TYPE public.analysis_job_status RENAME TO " "analysis_job_status_old"
        )
    )
    op.execute(
        sa.text("CREATE TYPE public.analysis_job_status AS ENUM (" + new_values + ")")
    )
    op.execute(
        sa.text(
            "ALTER TABLE public.analysis_jobs ALTER COLUMN status TYPE "
            "public.analysis_job_status USING " + expression
        )
    )
    op.execute(sa.text("DROP TYPE public.analysis_job_status_old"))


def upgrade() -> None:
    op.execute(sa.text("SET search_path TO public"))

    # The partial index depends on the old enum's comparison operator; remove
    # it before replacing the enum type, then restore logical uniqueness below.
    op.drop_index(
        "uq_analysis_jobs_active_document_rubric",
        table_name="analysis_jobs",
        schema="public",
    )
    _replace_job_enum(
        new_values="'QUEUED', 'RUNNING', 'DONE', 'ERROR'",
        expression=(
            "CASE status::text WHEN 'SUCCEEDED' THEN 'DONE' "
            "WHEN 'FAILED' THEN 'ERROR' WHEN 'CANCELLED' THEN 'ERROR' "
            "ELSE status::text END::text::public.analysis_job_status"
        ),
    )

    op.create_unique_constraint(
        "uq_analysis_jobs_document_rubric",
        "analysis_jobs",
        ["document_version_id", "rubric_version_id"],
        schema="public",
    )

    op.add_column(
        "document_versions",
        sa.Column("declared_sha256", sa.String(length=64), nullable=True),
        schema="public",
    )
    op.add_column(
        "document_versions",
        sa.Column("idempotency_key", sa.String(length=128), nullable=True),
        schema="public",
    )
    op.add_column(
        "document_versions",
        sa.Column("idempotency_fingerprint", sa.String(length=64), nullable=True),
        schema="public",
    )
    op.add_column(
        "document_versions",
        sa.Column("upload_expires_at", sa.DateTime(timezone=True), nullable=True),
        schema="public",
    )
    op.create_unique_constraint(
        "uq_document_versions_submission_idempotency_key",
        "document_versions",
        ["submission_id", "idempotency_key"],
        schema="public",
    )


def downgrade() -> None:
    op.execute(sa.text("SET search_path TO public"))

    op.drop_constraint(
        "uq_document_versions_submission_idempotency_key",
        "document_versions",
        schema="public",
        type_="unique",
    )
    op.drop_column("document_versions", "upload_expires_at", schema="public")
    op.drop_column("document_versions", "idempotency_fingerprint", schema="public")
    op.drop_column("document_versions", "idempotency_key", schema="public")
    op.drop_column("document_versions", "declared_sha256", schema="public")

    op.drop_constraint(
        "uq_analysis_jobs_document_rubric",
        "analysis_jobs",
        schema="public",
        type_="unique",
    )
    _replace_job_enum(
        new_values="'QUEUED', 'RUNNING', 'SUCCEEDED', 'FAILED', 'CANCELLED'",
        expression=(
            "CASE status::text WHEN 'DONE' THEN 'SUCCEEDED' "
            "WHEN 'ERROR' THEN 'FAILED' ELSE status::text END::text::"
            "public.analysis_job_status"
        ),
    )
    op.create_index(
        "uq_analysis_jobs_active_document_rubric",
        "analysis_jobs",
        ["document_version_id", "rubric_version_id"],
        unique=True,
        postgresql_where=sa.text("status IN ('QUEUED', 'RUNNING')"),
        schema="public",
    )
