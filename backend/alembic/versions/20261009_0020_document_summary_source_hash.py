"""Add document_summaries.source_hash so stale cached summaries are rebuilt.

Existing rows get NULL, which the service never treats as a match: each
legacy summary is regenerated once, on its next request.
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20261009_0020"
down_revision: str | None = "20260925_0019"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(sa.text("SET search_path TO public"))
    op.add_column(
        "document_summaries",
        sa.Column("source_hash", sa.String(length=64), nullable=True),
        schema="public",
    )


def downgrade() -> None:
    op.execute(sa.text("SET search_path TO public"))
    op.drop_column("document_summaries", "source_hash", schema="public")
