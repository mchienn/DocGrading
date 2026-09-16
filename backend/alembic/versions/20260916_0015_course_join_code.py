"""Add course join-code credentials and database-backed rate limits."""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "20260916_0015"
down_revision: str | None = "20260916_0014"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(sa.text("SET search_path TO public"))
    timestamp = sa.DateTime(timezone=True)
    uuid_type = postgresql.UUID(as_uuid=True)

    op.create_table(
        "course_join_codes",
        sa.Column("id", uuid_type, nullable=False),
        sa.Column("created_at", timestamp, server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", timestamp, server_default=sa.text("now()"), nullable=False),
        sa.Column("course_id", uuid_type, nullable=False),
        sa.Column("code", sa.String(length=20), nullable=False),
        sa.Column("expires_at", timestamp, nullable=False),
        sa.Column("revoked_at", timestamp, nullable=True),
        sa.PrimaryKeyConstraint("id", name="pk_course_join_codes"),
        sa.UniqueConstraint("code", name="uq_course_join_codes_code"),
        sa.CheckConstraint(
            "length(code) = 20 AND code ~ "
            "'^[ABCDEFGHJKMNPQRSTUVWXYZ23456789]{20}$'",
            name="ck_course_join_codes_code_shape",
        ),
        sa.CheckConstraint(
            "expires_at > created_at",
            name="ck_course_join_codes_expiry_after_creation",
        ),
        sa.ForeignKeyConstraint(
            ["course_id"],
            ["public.courses.id"],
            name="fk_course_join_codes_course_id_courses",
            ondelete="CASCADE",
        ),
        schema="public",
    )
    op.create_index(
        "uq_course_join_codes_course_active",
        "course_join_codes",
        ["course_id"],
        unique=True,
        postgresql_where=sa.text("revoked_at IS NULL"),
        schema="public",
    )

    op.create_table(
        "join_rate_limits",
        sa.Column("id", uuid_type, nullable=False),
        sa.Column("created_at", timestamp, server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", timestamp, server_default=sa.text("now()"), nullable=False),
        sa.Column("subject_hash", sa.String(length=64), nullable=False),
        sa.Column("window_started_at", timestamp, nullable=False),
        sa.Column("request_count", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_join_rate_limits"),
        sa.UniqueConstraint("subject_hash", name="uq_join_rate_limits_subject_hash"),
        sa.CheckConstraint("length(subject_hash) = 64", name="ck_join_rate_limits_subject_hash"),
        sa.CheckConstraint("request_count >= 0", name="ck_join_rate_limits_count_nonnegative"),
        schema="public",
    )


def downgrade() -> None:
    op.execute(sa.text("SET search_path TO public"))
    bind = op.get_bind()
    bind.execute(
        sa.text(
            "LOCK TABLE public.course_join_codes, public.join_rate_limits "
            "IN ACCESS EXCLUSIVE MODE"
        )
    )
    if bind.scalar(
        sa.text("SELECT EXISTS (SELECT 1 FROM public.course_join_codes LIMIT 1)")
    ):
        raise RuntimeError(
            "Refusing downgrade: public.course_join_codes is not empty"
        )

    op.drop_table("join_rate_limits", schema="public")
    op.drop_index(
        "uq_course_join_codes_course_active",
        table_name="course_join_codes",
        schema="public",
    )
    op.drop_table("course_join_codes", schema="public")
