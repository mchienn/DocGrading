"""Add chat_sessions and chat_messages for saved teacher chat history."""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "20260925_0019"
down_revision: str | None = "20260925_0018"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(sa.text("SET search_path TO public"))

    timestamp = sa.DateTime(timezone=True)
    uuid_type = postgresql.UUID(as_uuid=True)

    op.create_table(
        "chat_sessions",
        sa.Column("id", uuid_type, nullable=False),
        sa.Column(
            "created_at", timestamp, server_default=sa.text("now()"), nullable=False
        ),
        sa.Column(
            "updated_at", timestamp, server_default=sa.text("now()"), nullable=False
        ),
        sa.Column("owner_user_id", uuid_type, nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("course_id", uuid_type, nullable=True),
        sa.Column(
            "all_courses", sa.Boolean(), server_default=sa.false(), nullable=False
        ),
        sa.Column("submission_id", uuid_type, nullable=True),
        sa.Column("is_pinned", sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_chat_sessions"),
        sa.CheckConstraint(
            "length(btrim(title)) > 0", name="ck_chat_sessions_title_not_blank"
        ),
        sa.CheckConstraint(
            "NOT (all_courses AND course_id IS NOT NULL)",
            name="ck_chat_sessions_all_courses_without_course",
        ),
        sa.ForeignKeyConstraint(
            ["owner_user_id"],
            ["public.users.id"],
            name="fk_chat_sessions_owner_user_id_users",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["course_id"],
            ["public.courses.id"],
            name="fk_chat_sessions_course_id_courses",
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["submission_id"],
            ["public.submissions.id"],
            name="fk_chat_sessions_submission_id_submissions",
            ondelete="SET NULL",
        ),
        schema="public",
    )
    op.create_index(
        "ix_chat_sessions_owner_user_id_updated_at",
        "chat_sessions",
        ["owner_user_id", "updated_at"],
        schema="public",
    )

    op.create_table(
        "chat_messages",
        sa.Column("id", uuid_type, nullable=False),
        sa.Column(
            "created_at", timestamp, server_default=sa.text("now()"), nullable=False
        ),
        sa.Column(
            "updated_at", timestamp, server_default=sa.text("now()"), nullable=False
        ),
        sa.Column("session_id", uuid_type, nullable=False),
        sa.Column("sender", sa.Text(), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column(
            "payload",
            postgresql.JSONB(),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name="pk_chat_messages"),
        sa.CheckConstraint(
            "sender IN ('user', 'bot')", name="ck_chat_messages_sender_valid"
        ),
        sa.CheckConstraint(
            "jsonb_typeof(payload) = 'object'",
            name="ck_chat_messages_payload_object",
        ),
        sa.ForeignKeyConstraint(
            ["session_id"],
            ["public.chat_sessions.id"],
            name="fk_chat_messages_session_id_chat_sessions",
            ondelete="CASCADE",
        ),
        schema="public",
    )
    op.create_index(
        "ix_chat_messages_session_id_created_at",
        "chat_messages",
        ["session_id", "created_at"],
        schema="public",
    )


def downgrade() -> None:
    op.execute(sa.text("SET search_path TO public"))
    op.drop_index(
        "ix_chat_messages_session_id_created_at",
        table_name="chat_messages",
        schema="public",
    )
    op.drop_table("chat_messages", schema="public")
    op.drop_index(
        "ix_chat_sessions_owner_user_id_updated_at",
        table_name="chat_sessions",
        schema="public",
    )
    op.drop_table("chat_sessions", schema="public")
