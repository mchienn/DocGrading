"""Allow rubric edits until first assignment submission.

Rubric status remains for legacy history, but no longer controls mutability.
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20260924_0018"
down_revision: str | None = "20260924_0017"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


_MUTABLE_RUBRIC_VERSION = """
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
"""

_MUTABLE_CRITERION_PARENT = """
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
"""

_PUBLISHED_RUBRIC_VERSION = """
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
"""

_PUBLISHED_CRITERION_PARENT = """
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
"""


def upgrade() -> None:
    op.execute(sa.text("SET search_path TO public"))
    op.execute(sa.text(_MUTABLE_RUBRIC_VERSION))
    op.execute(sa.text(_MUTABLE_CRITERION_PARENT))


def downgrade() -> None:
    op.execute(sa.text("SET search_path TO public"))
    op.execute(sa.text(_PUBLISHED_RUBRIC_VERSION))
    op.execute(sa.text(_PUBLISHED_CRITERION_PARENT))
