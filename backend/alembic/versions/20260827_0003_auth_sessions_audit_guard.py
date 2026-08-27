"""Add session management table.

Security checklist (SC) coverage:
  SC-1  search_path pinned to public at top of upgrade/downgrade.
  SC-2  BEFORE TRUNCATE trigger on public.audit_events — already
        enforced by migration 20260825_0002; no action needed here.
  SC-3  All DDL uses schema="public"; FK references use public.*.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "20260827_0003"
down_revision: str | None = "20260825_0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # SC-1: pin search_path
    op.execute(sa.text("SET search_path TO public"))

    # ---------------------------------------------------------------
    # 1. sessions table
    # ---------------------------------------------------------------
    op.create_table(
        "sessions",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id", name="pk_sessions"),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["public.users.id"],
            name="fk_sessions_user_id_users",
            ondelete="CASCADE",
        ),
        schema="public",
    )
    op.create_index(
        "ix_sessions_user_id",
        "sessions",
        ["user_id"],
        schema="public",
    )
    op.create_index(
        "ix_sessions_expires_at",
        "sessions",
        ["expires_at"],
        schema="public",
    )


def downgrade() -> None:
    # SC-1: pin search_path
    op.execute(sa.text("SET search_path TO public"))

    # Drop sessions table
    op.drop_index("ix_sessions_expires_at", table_name="sessions", schema="public")
    op.drop_index("ix_sessions_user_id", table_name="sessions", schema="public")
    op.drop_table("sessions", schema="public")
