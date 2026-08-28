"""Add Course archive lifecycle state.

Security checklist (SC) coverage:
  SC-1  search_path pinned to public at the top of upgrade/downgrade.
  SC-2  public.audit_events is untouched; its existing BEFORE TRUNCATE guard
        remains in force.
  SC-3  Enum and table DDL are schema-qualified as public.*; no FK is added.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "20260828_0004"
down_revision: str | None = "20260827_0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

course_status = postgresql.ENUM(
    "ACTIVE",
    "ARCHIVED",
    name="course_status",
    schema="public",
)


def upgrade() -> None:
    # SC-1: pin search_path.
    op.execute(sa.text("SET search_path TO public"))

    bind = op.get_bind()
    course_status.create(bind, checkfirst=False)
    op.add_column(
        "courses",
        sa.Column(
            "status",
            course_status,
            server_default=sa.text("'ACTIVE'::public.course_status"),
            nullable=False,
        ),
        schema="public",
    )


def downgrade() -> None:
    # SC-1: pin search_path.
    op.execute(sa.text("SET search_path TO public"))

    op.drop_column("courses", "status", schema="public")
    course_status.drop(op.get_bind(), checkfirst=False)
