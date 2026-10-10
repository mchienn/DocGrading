"""Persist Teacher semantic citation verdict overrides."""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20260924_0017"
down_revision: str | None = "20260918_0016"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_OLD_PAYLOAD_CHECK = (
    "(decision = 'ACCEPT' "
    "AND edited_description IS NULL AND final_score IS NULL) "
    "OR (decision = 'EDIT' "
    "AND (edited_description IS NOT NULL OR final_score IS NOT NULL)) "
    "OR (decision = 'REJECT' "
    "AND edited_description IS NULL AND final_score IS NULL)"
)

_NEW_PAYLOAD_CHECK = (
    "(decision = 'ACCEPT' "
    "AND edited_description IS NULL AND final_score IS NULL "
    "AND edited_semantic_verdict IS NULL) "
    "OR (decision = 'EDIT' "
    "AND (edited_description IS NOT NULL OR final_score IS NOT NULL "
    "OR edited_semantic_verdict IS NOT NULL)) "
    "OR (decision = 'REJECT' "
    "AND edited_description IS NULL AND final_score IS NULL "
    "AND edited_semantic_verdict IS NULL)"
)

_SEMANTIC_VERDICT_CHECK = (
    "edited_semantic_verdict IS NULL OR edited_semantic_verdict IN "
    "('SUPPORTED', 'PARTIALLY_SUPPORTED', 'CONTRADICTED', 'IRRELEVANT', "
    "'INSUFFICIENT_EVIDENCE', 'SOURCE_UNAVAILABLE', 'AMBIGUOUS_CLAIM', "
    "'NEEDS_MANUAL_REVIEW')"
)


def upgrade() -> None:
    op.execute(sa.text("SET search_path TO public"))
    op.add_column(
        "review_decisions",
        sa.Column("edited_semantic_verdict", sa.String(length=32), nullable=True),
        schema="public",
    )
    op.drop_constraint(
        "ck_review_decisions_payload",
        "review_decisions",
        type_="check",
        schema="public",
    )
    op.create_check_constraint(
        "ck_review_decisions_payload",
        "review_decisions",
        _NEW_PAYLOAD_CHECK,
        schema="public",
    )
    op.create_check_constraint(
        "ck_review_decisions_semantic_verdict",
        "review_decisions",
        _SEMANTIC_VERDICT_CHECK,
        schema="public",
    )


def downgrade() -> None:
    op.execute(sa.text("SET search_path TO public"))
    op.execute(sa.text("LOCK TABLE public.review_decisions IN ACCESS EXCLUSIVE MODE"))
    op.execute(sa.text("""
            DO $$
            BEGIN
                IF EXISTS (
                    SELECT 1
                    FROM public.review_decisions
                    WHERE edited_semantic_verdict IS NOT NULL
                ) THEN
                    RAISE EXCEPTION
                        'Refusing downgrade: public.review_decisions contains '
                        'semantic verdict overrides';
                END IF;
            END
            $$;
            """))
    op.drop_constraint(
        "ck_review_decisions_semantic_verdict",
        "review_decisions",
        type_="check",
        schema="public",
    )
    op.drop_constraint(
        "ck_review_decisions_payload",
        "review_decisions",
        type_="check",
        schema="public",
    )
    op.drop_column("review_decisions", "edited_semantic_verdict", schema="public")
    op.create_check_constraint(
        "ck_review_decisions_payload",
        "review_decisions",
        _OLD_PAYLOAD_CHECK,
        schema="public",
    )
