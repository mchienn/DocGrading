"""Add durable in-app notifications."""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "20260912_0012"
down_revision: str | None = "20260912_0011"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

notification_type = postgresql.ENUM(
    "ANALYSIS_JOB_ERROR",
    "RESULT_PUBLISHED",
    "REVIEW_REQUEST_CREATED",
    "REVIEW_REQUEST_RESOLVED",
    "REVIEW_REQUEST_REJECTED",
    name="notification_type",
    schema="public",
    create_type=False,
)


def upgrade() -> None:
    op.execute(sa.text("SET search_path TO public"))
    notification_type.create(op.get_bind(), checkfirst=False)
    uuid_type = postgresql.UUID(as_uuid=True)
    timestamp = sa.DateTime(timezone=True)

    op.create_table(
        "notifications",
        sa.Column("id", uuid_type, nullable=False),
        sa.Column("recipient_id", uuid_type, nullable=False),
        sa.Column("type", notification_type, nullable=False),
        sa.Column("payload", postgresql.JSONB(), nullable=False),
        sa.Column("read_at", timestamp, nullable=True),
        sa.Column(
            "created_at", timestamp, server_default=sa.func.now(), nullable=False
        ),
        sa.PrimaryKeyConstraint("id", name="pk_notifications"),
        sa.CheckConstraint(
            "jsonb_typeof(payload) = 'object'",
            name="ck_notifications_payload_object",
        ),
        sa.ForeignKeyConstraint(
            ["recipient_id"],
            ["public.users.id"],
            name="fk_notifications_recipient_id_users",
            ondelete="RESTRICT",
        ),
        schema="public",
    )
    op.create_index(
        "ix_notifications_recipient_created_at",
        "notifications",
        ["recipient_id", "created_at"],
        schema="public",
    )
    op.create_index(
        "ix_notifications_recipient_unread",
        "notifications",
        ["recipient_id"],
        schema="public",
        postgresql_where=sa.text("read_at IS NULL"),
    )


def downgrade() -> None:
    op.execute(sa.text("SET search_path TO public"))
    op.execute(sa.text("LOCK TABLE public.notifications IN ACCESS EXCLUSIVE MODE"))
    if op.get_bind().scalar(
        sa.text("SELECT EXISTS (SELECT 1 FROM public.notifications LIMIT 1)")
    ):
        raise RuntimeError("Refusing downgrade: public.notifications is not empty")
    op.drop_table("notifications", schema="public")
    notification_type.drop(op.get_bind(), checkfirst=False)
