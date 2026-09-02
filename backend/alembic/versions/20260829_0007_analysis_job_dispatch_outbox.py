"""Add the durable analysis-job dispatch outbox.

SC-1: both directions pin ``search_path`` before any operation.
SC-2: this revision never touches append-only audit triggers.
SC-3: all application objects and foreign-key targets are schema-qualified.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "20260829_0007"
down_revision: str | None = "20260828_0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(sa.text("SET search_path TO public"))
    op.execute(sa.text("LOCK TABLE public.analysis_jobs IN ACCESS EXCLUSIVE MODE"))
    op.create_table(
        "analysis_job_dispatches",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "analysis_job_id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
        ),
        sa.Column(
            "attempt_count",
            sa.Integer(),
            server_default=sa.text("0"),
            nullable=False,
        ),
        sa.Column(
            "next_attempt_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.CheckConstraint(
            "attempt_count >= 0",
            name="ck_analysis_job_dispatches_attempt_count_nonnegative",
        ),
        sa.ForeignKeyConstraint(
            ["analysis_job_id"],
            ["public.analysis_jobs.id"],
            name="fk_analysis_job_dispatches_analysis_job_id_analysis_jobs",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_analysis_job_dispatches"),
        sa.UniqueConstraint(
            "analysis_job_id",
            name="uq_analysis_job_dispatches_analysis_job_id",
        ),
        schema="public",
    )
    op.create_index(
        "ix_analysis_job_dispatches_due",
        "analysis_job_dispatches",
        ["next_attempt_at", "created_at", "id"],
        unique=False,
        schema="public",
    )
    op.execute(sa.text("""
        CREATE FUNCTION public.enqueue_analysis_job_dispatch()
        RETURNS trigger
        LANGUAGE plpgsql
        SET search_path = pg_catalog, public, pg_temp
        AS $$
        BEGIN
            IF NEW.status::text = 'QUEUED' THEN
                INSERT INTO public.analysis_job_dispatches (id, analysis_job_id)
                VALUES (gen_random_uuid(), NEW.id)
                ON CONFLICT (analysis_job_id) DO NOTHING;
            END IF;
            RETURN NEW;
        END;
        $$;
    """))
    op.execute(sa.text("""
        CREATE TRIGGER trg_analysis_jobs_dispatch_outbox
        AFTER INSERT OR UPDATE OF status ON public.analysis_jobs
        FOR EACH ROW
        EXECUTE FUNCTION public.enqueue_analysis_job_dispatch();
    """))
    op.execute(sa.text("""
            INSERT INTO public.analysis_job_dispatches
                (
                    id,
                    analysis_job_id,
                    attempt_count,
                    next_attempt_at,
                    created_at,
                    updated_at
                )
            SELECT
                gen_random_uuid(),
                id,
                0,
                now(),
                now(),
                now()
            FROM public.analysis_jobs
            WHERE status::text = 'QUEUED'
            ON CONFLICT (analysis_job_id) DO NOTHING
        """))


def downgrade() -> None:
    op.execute(sa.text("SET search_path TO public"))
    op.execute(sa.text("LOCK TABLE public.analysis_jobs IN ACCESS EXCLUSIVE MODE"))
    op.execute(
        sa.text("LOCK TABLE public.analysis_job_dispatches IN ACCESS EXCLUSIVE MODE")
    )
    op.execute(sa.text("""
        DROP TRIGGER IF EXISTS trg_analysis_jobs_dispatch_outbox
        ON public.analysis_jobs
    """))
    op.execute(
        sa.text("DROP FUNCTION IF EXISTS public.enqueue_analysis_job_dispatch()")
    )
    op.execute(sa.text("""
            DO $$
            BEGIN
                IF EXISTS (
                    SELECT 1 FROM public.analysis_job_dispatches
                ) THEN
                    RAISE EXCEPTION '%',
                        'pending analysis job dispatches '
                        'must be drained before downgrade';
                END IF;
            END $$;
        """))
    op.drop_index(
        "ix_analysis_job_dispatches_due",
        table_name="analysis_job_dispatches",
        schema="public",
    )
    op.drop_table("analysis_job_dispatches", schema="public")
