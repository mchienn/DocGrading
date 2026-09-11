"""Add approval snapshots, published result history, and review idempotency."""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "20260911_0010"
down_revision: str | None = "20260910_0009"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(sa.text("SET search_path TO public"))
    op.execute(sa.text("LOCK TABLE public.document_versions IN ACCESS EXCLUSIVE MODE"))
    if op.get_bind().scalar(
        sa.text(
            "SELECT EXISTS ("
            "SELECT 1 FROM public.document_versions "
            "WHERE status IN ("
            "'APPROVED'::public.document_status, "
            "'PUBLISHED'::public.document_status"
            ") LIMIT 1)"
        )
    ):
        raise RuntimeError(
            "Refusing upgrade: legacy APPROVED/PUBLISHED document_versions "
            "require approval snapshot backfill"
        )
    uuid_type = postgresql.UUID(as_uuid=True)
    timestamp = sa.DateTime(timezone=True)

    op.add_column(
        "document_versions",
        sa.Column("approved_at", timestamp, nullable=True),
        schema="public",
    )
    op.add_column(
        "document_versions",
        sa.Column("approved_by_user_id", uuid_type, nullable=True),
        schema="public",
    )
    op.add_column(
        "document_versions",
        sa.Column("approved_snapshot", postgresql.JSONB, nullable=True),
        schema="public",
    )
    op.create_foreign_key(
        "fk_document_versions_approved_by_user_id_users",
        "document_versions",
        "users",
        ["approved_by_user_id"],
        ["id"],
        source_schema="public",
        referent_schema="public",
        ondelete="RESTRICT",
    )
    op.create_check_constraint(
        "ck_document_versions_approved_snapshot_object",
        "document_versions",
        "approved_snapshot IS NULL OR jsonb_typeof(approved_snapshot) = 'object'",
        schema="public",
    )

    op.create_table(
        "published_result_versions",
        sa.Column("id", uuid_type, nullable=False),
        sa.Column("document_version_id", uuid_type, nullable=False),
        sa.Column("version_number", sa.Integer(), nullable=False),
        sa.Column("approved_by_user_id", uuid_type, nullable=False),
        sa.Column("published_by_user_id", uuid_type, nullable=False),
        sa.Column("approved_at", timestamp, nullable=False),
        sa.Column("published_at", timestamp, nullable=False),
        sa.Column("snapshot", postgresql.JSONB, nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_published_result_versions"),
        sa.UniqueConstraint(
            "document_version_id",
            "version_number",
            name="uq_published_result_versions_document_version_number",
        ),
        sa.CheckConstraint(
            "version_number > 0",
            name="ck_published_result_versions_version_number_positive",
        ),
        sa.CheckConstraint(
            "jsonb_typeof(snapshot) = 'object'",
            name="ck_published_result_versions_snapshot_object",
        ),
        sa.ForeignKeyConstraint(
            ["document_version_id"],
            ["public.document_versions.id"],
            name="fk_published_results_document_version",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["approved_by_user_id"],
            ["public.users.id"],
            name="fk_published_result_versions_approved_by_user_id_users",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["published_by_user_id"],
            ["public.users.id"],
            name="fk_published_result_versions_published_by_user_id_users",
            ondelete="RESTRICT",
        ),
        schema="public",
    )

    op.create_table(
        "review_commands",
        sa.Column("id", uuid_type, nullable=False),
        sa.Column("actor_user_id", uuid_type, nullable=False),
        sa.Column("action", sa.String(32), nullable=False),
        sa.Column("idempotency_key", sa.String(128), nullable=False),
        sa.Column("request_fingerprint", sa.String(64), nullable=False),
        sa.Column("response", postgresql.JSONB, nullable=False),
        sa.Column(
            "created_at", timestamp, server_default=sa.func.now(), nullable=False
        ),
        sa.PrimaryKeyConstraint("id", name="pk_review_commands"),
        sa.UniqueConstraint(
            "actor_user_id",
            "action",
            "idempotency_key",
            name="uq_review_commands_actor_action_key",
        ),
        sa.CheckConstraint(
            "jsonb_typeof(response) = 'object'",
            name="ck_review_commands_response_object",
        ),
        sa.CheckConstraint(
            "length(idempotency_key) BETWEEN 1 AND 128",
            name="ck_review_commands_idempotency_key_length",
        ),
        sa.CheckConstraint(
            "length(request_fingerprint) = 64",
            name="ck_review_commands_request_fingerprint_length",
        ),
        sa.ForeignKeyConstraint(
            ["actor_user_id"],
            ["public.users.id"],
            name="fk_review_commands_actor_user_id_users",
            ondelete="RESTRICT",
        ),
        schema="public",
    )

    op.execute(sa.text("""
            CREATE FUNCTION public.prevent_published_result_mutation()
            RETURNS trigger
            LANGUAGE plpgsql
            SET search_path = pg_catalog, public, pg_temp
            AS $$
            BEGIN
                RAISE EXCEPTION 'published_result_versions is append-only';
            END;
            $$
            """))
    op.execute(sa.text("""
            CREATE TRIGGER trg_published_result_versions_no_update
            BEFORE UPDATE ON public.published_result_versions
            FOR EACH ROW EXECUTE FUNCTION public.prevent_published_result_mutation()
            """))
    op.execute(sa.text("""
            CREATE TRIGGER trg_published_result_versions_no_delete
            BEFORE DELETE ON public.published_result_versions
            FOR EACH ROW EXECUTE FUNCTION public.prevent_published_result_mutation()
            """))
    op.execute(sa.text("""
            CREATE TRIGGER trg_published_result_versions_no_truncate
            BEFORE TRUNCATE ON public.published_result_versions
            FOR EACH STATEMENT EXECUTE FUNCTION
            public.prevent_published_result_mutation()
            """))


def downgrade() -> None:
    op.execute(sa.text("SET search_path TO public"))
    op.execute(
        sa.text(
            "LOCK TABLE public.published_result_versions, public.review_commands, "
            "public.document_versions IN ACCESS EXCLUSIVE MODE"
        )
    )
    bind = op.get_bind()
    if bind.scalar(
        sa.text(
            "SELECT EXISTS (SELECT 1 FROM public.published_result_versions " "LIMIT 1)"
        )
    ):
        raise RuntimeError(
            "Refusing downgrade: public.published_result_versions is not empty"
        )
    if bind.scalar(
        sa.text("SELECT EXISTS (SELECT 1 FROM public.review_commands LIMIT 1)")
    ):
        raise RuntimeError("Refusing downgrade: public.review_commands is not empty")
    if bind.scalar(
        sa.text(
            "SELECT EXISTS (SELECT 1 FROM public.document_versions "
            "WHERE approved_at IS NOT NULL OR approved_by_user_id IS NOT NULL "
            "OR approved_snapshot IS NOT NULL)"
        )
    ):
        raise RuntimeError(
            "Refusing downgrade: public.document_versions approval data exists"
        )

    op.execute(
        sa.text(
            "DROP TRIGGER IF EXISTS trg_published_result_versions_no_update "
            "ON public.published_result_versions"
        )
    )
    op.execute(
        sa.text(
            "DROP TRIGGER IF EXISTS trg_published_result_versions_no_delete "
            "ON public.published_result_versions"
        )
    )
    op.execute(
        sa.text(
            "DROP TRIGGER IF EXISTS trg_published_result_versions_no_truncate "
            "ON public.published_result_versions"
        )
    )
    op.execute(sa.text("DROP FUNCTION public.prevent_published_result_mutation()"))
    op.drop_table("review_commands", schema="public")
    op.drop_table("published_result_versions", schema="public")
    op.drop_constraint(
        "ck_document_versions_approved_snapshot_object",
        "document_versions",
        schema="public",
        type_="check",
    )
    op.drop_constraint(
        "fk_document_versions_approved_by_user_id_users",
        "document_versions",
        schema="public",
        type_="foreignkey",
    )
    op.drop_column("document_versions", "approved_snapshot", schema="public")
    op.drop_column("document_versions", "approved_by_user_id", schema="public")
    op.drop_column("document_versions", "approved_at", schema="public")
