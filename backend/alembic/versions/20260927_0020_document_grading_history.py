"""Preserve review drafts and document status history per version."""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "20260927_0020"
down_revision: str | None = "20260926_0019"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(sa.text("SET search_path TO public"))
    op.drop_constraint(
        "uq_review_drafts_submission_reviewer",
        "review_drafts",
        type_="unique",
        schema="public",
    )
    op.create_unique_constraint(
        "uq_review_drafts_document_reviewer",
        "review_drafts",
        ["document_version_id", "reviewer_user_id"],
        schema="public",
    )

    uuid_type = postgresql.UUID(as_uuid=True)
    document_status = postgresql.ENUM(name="document_status", create_type=False)
    op.create_table(
        "document_status_events",
        sa.Column("id", uuid_type, nullable=False),
        sa.Column("document_version_id", uuid_type, nullable=False),
        sa.Column("from_status", document_status, nullable=True),
        sa.Column("to_status", document_status, nullable=False),
        sa.Column(
            "changed_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name="pk_document_status_events"),
        sa.ForeignKeyConstraint(
            ["document_version_id"],
            ["public.document_versions.id"],
            name="fk_document_status_events_document_version_id_document_versions",
            ondelete="CASCADE",
        ),
        sa.CheckConstraint(
            "from_status IS NULL OR from_status <> to_status",
            name="ck_document_status_events_changed",
        ),
        schema="public",
    )
    op.create_index(
        "ix_document_status_events_document_changed",
        "document_status_events",
        ["document_version_id", "changed_at", "id"],
        schema="public",
    )
    op.execute(sa.text("""
            CREATE FUNCTION public.record_document_status_event()
            RETURNS trigger
            LANGUAGE plpgsql
            AS $$
            BEGIN
                IF TG_OP = 'INSERT' THEN
                    INSERT INTO public.document_status_events (
                        id, document_version_id, from_status, to_status, changed_at
                    ) VALUES (
                        gen_random_uuid(), NEW.id, NULL, NEW.status,
                        COALESCE(NEW.created_at, CURRENT_TIMESTAMP)
                    );
                ELSIF OLD.status IS DISTINCT FROM NEW.status THEN
                    INSERT INTO public.document_status_events (
                        id, document_version_id, from_status, to_status, changed_at
                    ) VALUES (
                        gen_random_uuid(), NEW.id, OLD.status, NEW.status,
                        CURRENT_TIMESTAMP
                    );
                END IF;
                RETURN NEW;
            END;
            $$
        """))
    op.execute(sa.text("""
            CREATE TRIGGER trg_document_versions_status_history
            AFTER INSERT OR UPDATE OF status ON public.document_versions
            FOR EACH ROW
            EXECUTE FUNCTION public.record_document_status_event()
        """))


def downgrade() -> None:
    op.execute(sa.text("SET search_path TO public"))
    op.execute(
        sa.text(
            "LOCK TABLE public.document_status_events, public.review_drafts "
            "IN ACCESS EXCLUSIVE MODE"
        )
    )
    if op.get_bind().scalar(
        sa.text("SELECT EXISTS (SELECT 1 FROM public.document_status_events LIMIT 1)")
    ):
        raise RuntimeError(
            "Refusing downgrade: public.document_status_events contains history"
        )
    if op.get_bind().scalar(sa.text("""
            SELECT EXISTS (
                SELECT 1
                FROM public.review_drafts
                GROUP BY submission_id, reviewer_user_id
                HAVING count(*) > 1
            )
        """)):
        raise RuntimeError(
            "Refusing downgrade: review drafts contain per-document history"
        )
    op.execute(
        sa.text(
            "DROP TRIGGER trg_document_versions_status_history "
            "ON public.document_versions"
        )
    )
    op.execute(sa.text("DROP FUNCTION public.record_document_status_event()"))
    op.drop_table("document_status_events", schema="public")
    op.drop_constraint(
        "uq_review_drafts_document_reviewer",
        "review_drafts",
        type_="unique",
        schema="public",
    )
    op.create_unique_constraint(
        "uq_review_drafts_submission_reviewer",
        "review_drafts",
        ["submission_id", "reviewer_user_id"],
        schema="public",
    )
