from __future__ import annotations

import uuid
from typing import Any

import sqlalchemy as sa
from pgvector.sqlalchemy import Vector
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.models.mixins import TimestampMixin, UUIDPrimaryKeyMixin

# Must match migration 20260924_0017 (text-embedding-3-small = 1536 dims).
EMBEDDING_DIMENSIONS = 1536


class DocumentChunk(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """One retrieval unit cut from a DocumentIR (see services/chunking.py)."""

    __tablename__ = "document_chunks"
    __table_args__ = (
        sa.UniqueConstraint(
            "document_version_id",
            "chunk_index",
            name="uq_document_chunks_version_chunk_index",
        ),
        sa.CheckConstraint(
            "chunk_index >= 0", name="ck_document_chunks_chunk_index_nonnegative"
        ),
        sa.CheckConstraint(
            "page_start > 0 AND page_end >= page_start",
            name="ck_document_chunks_page_range",
        ),
        sa.CheckConstraint(
            "token_count > 0", name="ck_document_chunks_token_count_positive"
        ),
        sa.Index("ix_document_chunks_document_version_id", "document_version_id"),
    )

    document_version_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        sa.ForeignKey(
            "document_versions.id",
            ondelete="CASCADE",
            name="fk_document_chunks_document_version_id_document_versions",
        ),
        nullable=False,
    )
    chunk_index: Mapped[int] = mapped_column(sa.Integer, nullable=False)
    section_path: Mapped[str | None] = mapped_column(sa.Text, nullable=True)
    page_start: Mapped[int] = mapped_column(sa.Integer, nullable=False)
    page_end: Mapped[int] = mapped_column(sa.Integer, nullable=False)
    paragraph_ids: Mapped[list[Any]] = mapped_column(JSONB, nullable=False)
    text: Mapped[str] = mapped_column(sa.Text, nullable=False)
    token_count: Mapped[int] = mapped_column(sa.Integer, nullable=False)
    embedding: Mapped[list[float] | None] = mapped_column(
        Vector(EMBEDDING_DIMENSIONS), nullable=True
    )
