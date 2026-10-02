"""Kiểm tra xem build_chunks() có hoạt động đúng không.
Cách chạy:
    uv run python -m scripts.inspect_chunks
    uv run python -m scripts.inspect_chunks --document-version-id <uuid>
"""

from __future__ import annotations

import argparse
import asyncio
import uuid

import sqlalchemy as sa

from app.db.session import _session_factory
from app.models.analysis import DocumentIR
from app.services.chunking import build_chunks


async def _fetch_document_ir(
    session, document_version_id: uuid.UUID | None
) -> DocumentIR | None:
    stmt = sa.select(DocumentIR)
    if document_version_id is not None:
        stmt = stmt.where(DocumentIR.document_version_id == document_version_id)
    else:
        # Không truyền id -> lấy tạm bản ghi mới nhất để xem thử.
        stmt = stmt.order_by(DocumentIR.created_at.desc()).limit(1)
    result = await session.execute(stmt)
    return result.scalar_one_or_none()


async def main(document_version_id: uuid.UUID | None) -> None:
    async with _session_factory()() as session:
        document_ir = await _fetch_document_ir(session, document_version_id)

        if document_ir is None:
            print("Không tìm thấy DocumentIR nào trong DB.")
            print(
                "-> Hãy upload + chờ 1 báo cáo PDF được xử lý xong (status done) "
                "rồi chạy lại."
            )
            return

        print(f"document_ir.id            = {document_ir.id}")
        print(f"document_version_id       = {document_ir.document_version_id}")
        print(f"parser_version            = {document_ir.parser_version}")
        print()

        chunks = build_chunks(document_ir.content)

        if not chunks:
            print(
                "build_chunks() trả về danh sách RỖNG — có thể content không có "
                "section/paragraph nào."
            )
            return

        print(f"Tổng số chunk: {len(chunks)}\n")
        for chunk in chunks:
            preview = chunk.text[:160].replace("\n", " ")
            if len(chunk.text) > 160:
                preview += "..."
            print(f"--- chunk #{chunk.chunk_index} ---")
            print(f"  section_path : {chunk.section_path}")
            print(f"  pages        : {chunk.page_start}-{chunk.page_end}")
            print(f"  paragraph_ids: {chunk.paragraph_ids}")
            print(f"  token_count  : {chunk.token_count}")
            print(f"  text preview : {preview}")
            print()


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--document-version-id",
        type=str,
        default=None,
        help=(
            "UUID của document_versions.id cần kiểm tra. "
            "Bỏ trống -> lấy DocumentIR mới nhất trong DB."
        ),
    )
    return parser.parse_args()


if __name__ == "__main__":
    args = _parse_args()
    dv_id = uuid.UUID(args.document_version_id) if args.document_version_id else None
    asyncio.run(main(dv_id))
