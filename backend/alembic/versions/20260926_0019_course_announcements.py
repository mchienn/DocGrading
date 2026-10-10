"""Add course announcements."""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "20260926_0019"
down_revision: str | None = "20260924_0018"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(sa.text("SET search_path TO public"))
    uuid_type = postgresql.UUID(as_uuid=True)
    timestamp = sa.DateTime(timezone=True)
    op.create_table(
        "announcements",
        sa.Column("id", uuid_type, nullable=False),
        sa.Column("course_id", uuid_type, nullable=False),
        sa.Column("created_by_user_id", uuid_type, nullable=False),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column(
            "created_at", timestamp, server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", timestamp, server_default=sa.func.now(), nullable=False
        ),
        sa.PrimaryKeyConstraint("id", name="pk_announcements"),
        sa.ForeignKeyConstraint(
            ["course_id"],
            ["public.courses.id"],
            name="fk_announcements_course_id_courses",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["created_by_user_id"],
            ["public.users.id"],
            name="fk_announcements_created_by_user_id_users",
            ondelete="RESTRICT",
        ),
        sa.CheckConstraint(
            "length(btrim(title)) > 0 AND title !~ '^[[:space:]]*$'",
            name="ck_announcements_title_not_blank",
        ),
        sa.CheckConstraint(
            "length(btrim(body)) > 0 AND body !~ '^[[:space:]]*$'",
            name="ck_announcements_body_not_blank",
        ),
        schema="public",
    )
    op.create_index(
        "ix_announcements_course_created_at",
        "announcements",
        ["course_id", "created_at"],
        schema="public",
    )


def downgrade() -> None:
    op.execute(sa.text("SET search_path TO public"))
    op.execute(sa.text("LOCK TABLE public.announcements IN ACCESS EXCLUSIVE MODE"))
    if op.get_bind().scalar(
        sa.text("SELECT EXISTS (SELECT 1 FROM public.announcements LIMIT 1)")
    ):
        raise RuntimeError("Refusing downgrade: public.announcements is not empty")
    op.drop_table("announcements", schema="public")
