"""Add submission queue and review workspace persistence."""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "20260910_0009"
down_revision: str | None = "20260902_0008"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

review_decision_type = postgresql.ENUM(
    "ACCEPT",
    "EDIT",
    "REJECT",
    name="review_decision_type",
    schema="public",
    create_type=False,
)


def upgrade() -> None:
    op.execute(sa.text("SET search_path TO public"))
    review_decision_type.create(op.get_bind(), checkfirst=False)
    uuid_type = postgresql.UUID(as_uuid=True)
    timestamp = sa.DateTime(timezone=True)

    op.create_table(
        "findings",
        sa.Column("id", uuid_type, nullable=False),
        sa.Column(
            "created_at", timestamp, server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", timestamp, server_default=sa.func.now(), nullable=False
        ),
        sa.Column("analysis_job_id", uuid_type, nullable=False),
        sa.Column("criterion_version_id", uuid_type, nullable=False),
        sa.Column("severity", sa.String(32), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("suggestion", sa.Text(), nullable=True),
        sa.Column("proposed_score", sa.Numeric(5, 2), nullable=True),
        sa.PrimaryKeyConstraint("id", name="pk_findings"),
        sa.CheckConstraint(
            "length(btrim(severity)) > 0 " "AND severity !~ '^[[:space:]]*$'",
            name="ck_findings_severity_not_blank",
        ),
        sa.CheckConstraint(
            "length(btrim(description)) > 0 " "AND description !~ '^[[:space:]]*$'",
            name="ck_findings_description_not_blank",
        ),
        sa.CheckConstraint(
            "proposed_score IS NULL "
            "OR (proposed_score >= 0 AND proposed_score <= 100)",
            name="ck_findings_proposed_score_range",
        ),
        sa.ForeignKeyConstraint(
            ["analysis_job_id"],
            ["public.analysis_jobs.id"],
            name="fk_findings_analysis_job_id_analysis_jobs",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["criterion_version_id"],
            ["public.criterion_versions.id"],
            name="fk_findings_criterion_version_id_criterion_versions",
            ondelete="RESTRICT",
        ),
        schema="public",
    )
    op.create_index(
        "ix_findings_analysis_job",
        "findings",
        ["analysis_job_id"],
        schema="public",
    )
    op.create_index(
        "ix_findings_criterion",
        "findings",
        ["criterion_version_id"],
        schema="public",
    )

    op.create_table(
        "evidence_anchors",
        sa.Column("id", uuid_type, nullable=False),
        sa.Column("finding_id", uuid_type, nullable=False),
        sa.Column("document_ir_id", uuid_type, nullable=False),
        sa.Column("element_id", sa.String(64), nullable=False),
        sa.Column("page_number", sa.Integer(), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_evidence_anchors"),
        sa.UniqueConstraint(
            "finding_id",
            "document_ir_id",
            "element_id",
            "page_number",
            name="uq_evidence_anchors_finding_element_page",
        ),
        sa.CheckConstraint("page_number > 0", name="ck_evidence_anchors_page_positive"),
        sa.CheckConstraint(
            "length(btrim(element_id)) > 0 " "AND element_id !~ '^[[:space:]]*$'",
            name="ck_evidence_anchors_element_id_not_blank",
        ),
        sa.ForeignKeyConstraint(
            ["finding_id"],
            ["public.findings.id"],
            name="fk_evidence_anchors_finding_id_findings",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["document_ir_id"],
            ["public.document_irs.id"],
            name="fk_evidence_anchors_document_ir_id_document_irs",
            ondelete="RESTRICT",
        ),
        schema="public",
    )
    op.create_index(
        "ix_evidence_anchors_finding",
        "evidence_anchors",
        ["finding_id"],
        schema="public",
    )

    op.create_table(
        "review_locks",
        sa.Column("id", uuid_type, nullable=False),
        sa.Column("submission_id", uuid_type, nullable=False),
        sa.Column("reviewer_user_id", uuid_type, nullable=False),
        sa.Column(
            "acquired_at", timestamp, server_default=sa.func.now(), nullable=False
        ),
        sa.Column("expires_at", timestamp, nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_review_locks"),
        sa.UniqueConstraint("submission_id", name="uq_review_locks_submission_id"),
        sa.CheckConstraint(
            "expires_at > acquired_at",
            name="ck_review_locks_expiry_after_acquired",
        ),
        sa.ForeignKeyConstraint(
            ["submission_id"],
            ["public.submissions.id"],
            name="fk_review_locks_submission_id_submissions",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["reviewer_user_id"],
            ["public.users.id"],
            name="fk_review_locks_reviewer_user_id_users",
            ondelete="RESTRICT",
        ),
        schema="public",
    )

    op.create_table(
        "review_drafts",
        sa.Column("id", uuid_type, nullable=False),
        sa.Column(
            "created_at", timestamp, server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", timestamp, server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "revision", sa.Integer(), server_default=sa.text("1"), nullable=False
        ),
        sa.Column("submission_id", uuid_type, nullable=False),
        sa.Column("document_version_id", uuid_type, nullable=False),
        sa.Column("reviewer_user_id", uuid_type, nullable=False),
        sa.Column("comment", sa.Text(), server_default=sa.text("''"), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_review_drafts"),
        sa.UniqueConstraint(
            "submission_id",
            "reviewer_user_id",
            name="uq_review_drafts_submission_reviewer",
        ),
        sa.CheckConstraint("revision > 0", name="ck_review_drafts_revision_positive"),
        sa.ForeignKeyConstraint(
            ["submission_id"],
            ["public.submissions.id"],
            name="fk_review_drafts_submission_id_submissions",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["document_version_id"],
            ["public.document_versions.id"],
            name="fk_review_drafts_document_version_id_document_versions",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["reviewer_user_id"],
            ["public.users.id"],
            name="fk_review_drafts_reviewer_user_id_users",
            ondelete="RESTRICT",
        ),
        schema="public",
    )

    op.create_table(
        "review_decisions",
        sa.Column("id", uuid_type, nullable=False),
        sa.Column(
            "created_at", timestamp, server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", timestamp, server_default=sa.func.now(), nullable=False
        ),
        sa.Column("review_draft_id", uuid_type, nullable=False),
        sa.Column("finding_id", uuid_type, nullable=False),
        sa.Column("decision", review_decision_type, nullable=False),
        sa.Column("edited_description", sa.Text(), nullable=True),
        sa.Column("final_score", sa.Numeric(5, 2), nullable=True),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint("id", name="pk_review_decisions"),
        sa.UniqueConstraint(
            "review_draft_id",
            "finding_id",
            name="uq_review_decisions_draft_finding",
        ),
        sa.CheckConstraint(
            "(decision = 'ACCEPT' "
            "AND edited_description IS NULL AND final_score IS NULL) "
            "OR (decision = 'EDIT' "
            "AND (edited_description IS NOT NULL OR final_score IS NOT NULL)) "
            "OR (decision = 'REJECT' "
            "AND edited_description IS NULL AND final_score IS NULL)",
            name="ck_review_decisions_payload",
        ),
        sa.CheckConstraint(
            "edited_description IS NULL " "OR edited_description !~ '^[[:space:]]*$'",
            name="ck_review_decisions_description_not_blank",
        ),
        sa.CheckConstraint(
            "reason IS NULL OR reason !~ '^[[:space:]]*$'",
            name="ck_review_decisions_reason_not_blank",
        ),
        sa.CheckConstraint(
            "final_score IS NULL OR (final_score >= 0 AND final_score <= 100)",
            name="ck_review_decisions_final_score_range",
        ),
        sa.ForeignKeyConstraint(
            ["review_draft_id"],
            ["public.review_drafts.id"],
            name="fk_review_decisions_review_draft_id_review_drafts",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["finding_id"],
            ["public.findings.id"],
            name="fk_review_decisions_finding_id_findings",
            ondelete="RESTRICT",
        ),
        schema="public",
    )


def downgrade() -> None:
    op.execute(sa.text("SET search_path TO public"))
    op.execute(
        sa.text(
            "LOCK TABLE public.review_decisions, public.review_drafts, "
            "public.review_locks, public.evidence_anchors, public.findings "
            "IN ACCESS EXCLUSIVE MODE"
        )
    )
    for table in (
        "review_decisions",
        "review_drafts",
        "review_locks",
        "evidence_anchors",
        "findings",
    ):
        has_rows = op.get_bind().scalar(
            sa.text(f"SELECT EXISTS (SELECT 1 FROM public.{table} LIMIT 1)")
        )
        if has_rows:
            raise RuntimeError(f"Refusing downgrade: public.{table} is not empty")

    op.drop_table("review_decisions", schema="public")
    op.drop_table("review_drafts", schema="public")
    op.drop_table("review_locks", schema="public")
    op.drop_index(
        "ix_evidence_anchors_finding",
        table_name="evidence_anchors",
        schema="public",
    )
    op.drop_table("evidence_anchors", schema="public")
    op.drop_index("ix_findings_criterion", table_name="findings", schema="public")
    op.drop_index("ix_findings_analysis_job", table_name="findings", schema="public")
    op.drop_table("findings", schema="public")
    review_decision_type.drop(op.get_bind(), checkfirst=False)
