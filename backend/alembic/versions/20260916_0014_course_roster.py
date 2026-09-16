"""Add course roster membership lifecycle and manual invites."""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "20260916_0014"
down_revision: str | None = "20260913_0013"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

membership_joined_via = postgresql.ENUM(
    "MANUAL",
    "CODE",
    name="membership_joined_via",
    schema="public",
    create_type=False,
)


def upgrade() -> None:
    op.execute(sa.text("SET search_path TO public"))
    op.execute(
        sa.text("CREATE TYPE public.membership_joined_via AS ENUM ('MANUAL', 'CODE')")
    )
    op.execute(
        sa.text(
            "ALTER TYPE public.membership_status "
            "RENAME VALUE 'INACTIVE' TO 'REMOVED'"
        )
    )

    op.add_column(
        "memberships",
        sa.Column(
            "joined_via",
            membership_joined_via,
            server_default=sa.text("'MANUAL'::public.membership_joined_via"),
            nullable=False,
        ),
        schema="public",
    )
    op.add_column(
        "memberships",
        sa.Column(
            "joined_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
        schema="public",
    )
    op.execute(
        sa.text(
            "UPDATE public.memberships SET joined_at = created_at "
            "WHERE joined_at IS NULL"
        )
    )
    op.alter_column(
        "memberships",
        "joined_at",
        server_default=sa.text("now()"),
        nullable=False,
        schema="public",
    )

    op.create_table(
        "course_invites",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("course_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("email", sa.String(length=320), nullable=False),
        sa.Column("created_by_user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_course_invites"),
        sa.ForeignKeyConstraint(
            ["course_id"],
            ["public.courses.id"],
            name="fk_course_invites_course_id_courses",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["created_by_user_id"],
            ["public.users.id"],
            name="fk_course_invites_created_by_user_id_users",
            ondelete="RESTRICT",
        ),
        sa.CheckConstraint(
            "length(btrim(email)) > 0 AND email !~ '^[[:space:]]*$'",
            name="ck_course_invites_email_not_blank",
        ),
        schema="public",
    )
    op.create_index(
        "uq_course_invites_course_email_lower",
        "course_invites",
        ["course_id", sa.text("lower(email)")],
        unique=True,
        schema="public",
    )


def downgrade() -> None:
    op.execute(sa.text("SET search_path TO public"))
    bind = op.get_bind()
    bind.execute(sa.text("LOCK TABLE public.course_invites IN ACCESS EXCLUSIVE MODE"))
    has_invites = bind.execute(
        sa.text("SELECT EXISTS (SELECT 1 FROM public.course_invites)")
    ).scalar()
    if has_invites:
        raise RuntimeError(
            "Cannot downgrade DOC-34 while course_invites contains data; "
            "export or remove invites first."
        )

    op.drop_index(
        "uq_course_invites_course_email_lower",
        table_name="course_invites",
        schema="public",
    )
    op.drop_table("course_invites", schema="public")
    op.drop_column("memberships", "joined_at", schema="public")
    op.drop_column("memberships", "joined_via", schema="public")
    op.execute(
        sa.text(
            "ALTER TYPE public.membership_status "
            "RENAME VALUE 'REMOVED' TO 'INACTIVE'"
        )
    )
    membership_joined_via.drop(bind, checkfirst=False)
