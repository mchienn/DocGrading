"""Enforce published rubric immutability at the database boundary.

Security checklist (SC) coverage:
  SC-1  search_path pinned to public at the top of upgrade/downgrade.
  SC-2  public.audit_events is untouched; its existing BEFORE TRUNCATE guard
        remains in force.
  SC-3  Function, table, and enum references are schema-qualified public.*.
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20260828_0005"
down_revision: str | None = "20260828_0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # SC-1: pin search_path.
    op.execute(sa.text("SET search_path TO public"))

    op.execute(sa.text("""
        CREATE OR REPLACE FUNCTION public.fn_immut_rubric_version()
        RETURNS trigger
        LANGUAGE plpgsql
        SET search_path = pg_catalog, public, pg_temp
        AS $$
        DECLARE
            assignment_row record;
        BEGIN
            PERFORM public.fn_domain_lock('rubric', OLD.id);
            IF OLD.status <> 'DRAFT'::public.rubric_status THEN
                RAISE EXCEPTION USING
                    ERRCODE = '23514',
                    MESSAGE = 'published rubric version is immutable';
            END IF;
            FOR assignment_row IN
                SELECT a.id
                FROM public.assignments AS a
                WHERE a.rubric_version_id = OLD.id
                ORDER BY a.id
            LOOP
                PERFORM public.fn_domain_lock('assignment', assignment_row.id);
                IF EXISTS (
                    SELECT 1
                    FROM public.assignments AS a
                    WHERE a.id = assignment_row.id
                      AND a.first_submission_at IS NOT NULL
                ) THEN
                    RAISE EXCEPTION USING
                        ERRCODE = '23514',
                        MESSAGE = 'rubric version is immutable '
                            || 'after first submission';
                END IF;
            END LOOP;
            IF TG_OP = 'DELETE' THEN
                RETURN OLD;
            END IF;
            RETURN NEW;
        END;
        $$;
    """))

    op.execute(sa.text("""
        CREATE OR REPLACE FUNCTION public.fn_assert_criterion_parent_mutable(
            parent_id uuid
        )
        RETURNS void
        LANGUAGE plpgsql
        SET search_path = pg_catalog, public, pg_temp
        AS $$
        DECLARE
            assignment_row record;
        BEGIN
            PERFORM public.fn_domain_lock('rubric', parent_id);
            IF EXISTS (
                SELECT 1
                FROM public.rubric_versions AS rv
                WHERE rv.id = parent_id
                  AND rv.status <> 'DRAFT'::public.rubric_status
            ) THEN
                RAISE EXCEPTION USING
                    ERRCODE = '23514',
                    MESSAGE = 'published rubric criterion is immutable';
            END IF;
            FOR assignment_row IN
                SELECT a.id
                FROM public.assignments AS a
                WHERE a.rubric_version_id = parent_id
                ORDER BY a.id
            LOOP
                PERFORM public.fn_domain_lock('assignment', assignment_row.id);
                IF EXISTS (
                    SELECT 1
                    FROM public.assignments AS a
                    WHERE a.id = assignment_row.id
                      AND a.first_submission_at IS NOT NULL
                ) THEN
                    RAISE EXCEPTION USING
                        ERRCODE = '23514',
                        MESSAGE = 'criterion version is immutable '
                            || 'after first submission';
                END IF;
            END LOOP;
        END;
        $$;
    """))


def downgrade() -> None:
    # SC-1: pin search_path.
    op.execute(sa.text("SET search_path TO public"))

    op.execute(sa.text("""
        CREATE OR REPLACE FUNCTION public.fn_immut_rubric_version()
        RETURNS trigger
        LANGUAGE plpgsql
        SET search_path = pg_catalog, public, pg_temp
        AS $$
        DECLARE
            assignment_row record;
        BEGIN
            PERFORM public.fn_domain_lock('rubric', OLD.id);
            FOR assignment_row IN
                SELECT a.id
                FROM public.assignments AS a
                WHERE a.rubric_version_id = OLD.id
                ORDER BY a.id
            LOOP
                PERFORM public.fn_domain_lock('assignment', assignment_row.id);
                IF EXISTS (
                    SELECT 1
                    FROM public.assignments AS a
                    WHERE a.id = assignment_row.id
                      AND a.first_submission_at IS NOT NULL
                ) THEN
                    RAISE EXCEPTION USING
                        ERRCODE = '23514',
                        MESSAGE = 'rubric version is immutable '
                            || 'after first submission';
                END IF;
            END LOOP;
            IF TG_OP = 'DELETE' THEN
                RETURN OLD;
            END IF;
            RETURN NEW;
        END;
        $$;
    """))

    op.execute(sa.text("""
        CREATE OR REPLACE FUNCTION public.fn_assert_criterion_parent_mutable(
            parent_id uuid
        )
        RETURNS void
        LANGUAGE plpgsql
        SET search_path = pg_catalog, public, pg_temp
        AS $$
        DECLARE
            assignment_row record;
        BEGIN
            PERFORM public.fn_domain_lock('rubric', parent_id);
            FOR assignment_row IN
                SELECT a.id
                FROM public.assignments AS a
                WHERE a.rubric_version_id = parent_id
                ORDER BY a.id
            LOOP
                PERFORM public.fn_domain_lock('assignment', assignment_row.id);
                IF EXISTS (
                    SELECT 1
                    FROM public.assignments AS a
                    WHERE a.id = assignment_row.id
                      AND a.first_submission_at IS NOT NULL
                ) THEN
                    RAISE EXCEPTION USING
                        ERRCODE = '23514',
                        MESSAGE = 'criterion version is immutable '
                            || 'after first submission';
                END IF;
            END LOOP;
        END;
        $$;
    """))
