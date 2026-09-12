"""Add criterion review requests."""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "20260912_0011"
down_revision: str | None = "20260911_0010"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

review_request_status = postgresql.ENUM(
    "OPEN",
    "RESOLVED",
    "REJECTED",
    name="review_request_status",
    schema="public",
    create_type=False,
)


def upgrade() -> None:
    op.execute(sa.text("SET search_path TO public"))
    review_request_status.create(op.get_bind(), checkfirst=False)
    uuid_type = postgresql.UUID(as_uuid=True)
    timestamp = sa.DateTime(timezone=True)

    op.create_table(
        "review_requests",
        sa.Column("id", uuid_type, nullable=False),
        sa.Column(
            "created_at", timestamp, server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", timestamp, server_default=sa.func.now(), nullable=False
        ),
        sa.Column("published_result_id", uuid_type, nullable=False),
        sa.Column("submission_id", uuid_type, nullable=False),
        sa.Column("student_id", uuid_type, nullable=False),
        sa.Column("criterion_version_id", uuid_type, nullable=False),
        sa.Column("finding_id", uuid_type, nullable=True),
        sa.Column(
            "status",
            review_request_status,
            server_default=sa.text("'OPEN'::public.review_request_status"),
            nullable=False,
        ),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("response", sa.Text(), nullable=True),
        sa.Column("responded_by_user_id", uuid_type, nullable=True),
        sa.Column("responded_at", timestamp, nullable=True),
        sa.PrimaryKeyConstraint("id", name="pk_review_requests"),
        sa.CheckConstraint(
            "(status = 'OPEN' AND response IS NULL "
            "AND responded_by_user_id IS NULL AND responded_at IS NULL) "
            "OR (status IN ('RESOLVED', 'REJECTED') "
            "AND response IS NOT NULL AND responded_by_user_id IS NOT NULL "
            "AND responded_at IS NOT NULL)",
            name="ck_review_requests_state",
        ),
        sa.CheckConstraint(
            "length(btrim(reason)) > 0 AND reason !~ '^[[:space:]]*$'",
            name="ck_review_requests_reason_not_blank",
        ),
        sa.CheckConstraint(
            "response IS NULL OR response !~ '^[[:space:]]*$'",
            name="ck_review_requests_response_not_blank",
        ),
        sa.ForeignKeyConstraint(
            ["published_result_id"],
            ["public.published_result_versions.id"],
            name="fk_review_requests_published_result",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["submission_id"],
            ["public.submissions.id"],
            name="fk_review_requests_submission_id_submissions",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["student_id"],
            ["public.users.id"],
            name="fk_review_requests_student_id_users",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["criterion_version_id"],
            ["public.criterion_versions.id"],
            name="fk_review_requests_criterion_version_id_criterion_versions",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["finding_id"],
            ["public.findings.id"],
            name="fk_review_requests_finding_id_findings",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["responded_by_user_id"],
            ["public.users.id"],
            name="fk_review_requests_responded_by_user_id_users",
            ondelete="RESTRICT",
        ),
        schema="public",
    )
    op.create_index(
        "ix_review_requests_published_result",
        "review_requests",
        ["published_result_id"],
        schema="public",
    )
    op.create_index(
        "ix_review_requests_student",
        "review_requests",
        ["student_id"],
        schema="public",
    )
    op.create_index(
        "uq_review_requests_open_target",
        "review_requests",
        ["published_result_id", "student_id", "criterion_version_id"],
        unique=True,
        schema="public",
        postgresql_where=sa.text("status = 'OPEN'::public.review_request_status"),
    )


def downgrade() -> None:
    op.execute(sa.text("SET search_path TO public"))
    op.execute(sa.text("LOCK TABLE public.review_requests IN ACCESS EXCLUSIVE MODE"))
    if op.get_bind().scalar(
        sa.text("SELECT EXISTS (SELECT 1 FROM public.review_requests LIMIT 1)")
    ):
        raise RuntimeError("Refusing downgrade: public.review_requests is not empty")
    op.drop_table("review_requests", schema="public")
    review_request_status.drop(op.get_bind(), checkfirst=False)
