"""Add persistent login brute-force lockout state."""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20260913_0013"
down_revision: str | None = "20260912_0012"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(sa.text("SET search_path TO public"))
    op.add_column(
        "users",
        sa.Column(
            "failed_login_attempts",
            sa.Integer(),
            server_default=sa.text("0"),
            nullable=False,
        ),
        schema="public",
    )
    op.add_column(
        "users",
        sa.Column(
            "failed_login_window_started_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
        schema="public",
    )
    op.add_column(
        "users",
        sa.Column(
            "login_locked_until",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
        schema="public",
    )
    op.create_check_constraint(
        "ck_users_failed_login_attempts_nonnegative",
        "users",
        "failed_login_attempts >= 0",
        schema="public",
    )


def downgrade() -> None:
    op.execute(sa.text("SET search_path TO public"))
    op.drop_constraint(
        "ck_users_failed_login_attempts_nonnegative",
        "users",
        type_="check",
        schema="public",
    )
    op.drop_column("users", "login_locked_until", schema="public")
    op.drop_column("users", "failed_login_window_started_at", schema="public")
    op.drop_column("users", "failed_login_attempts", schema="public")
