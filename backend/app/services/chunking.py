from __future__ import annotations

from dataclasses import dataclass
from typing import Any

# ~300–500 token/chunk
MAX_CHUNK_TOKENS = 450


def _estimate_tokens(text: str) -> int:
    return max(1, len(text) // 4)


@dataclass(frozen=True)
class ChunkDraft:
    """One chunk, before embedding — matches columns of `document_chunks`."""

    chunk_index: int
    section_path: str | None
    page_start: int
    page_end: int
    paragraph_ids: list[str]
    text: str
    token_count: int


def _build_section_paths(sections: list[dict[str, Any]]) -> dict[str, str]:
    """Map mỗi section_id -> đường dẫn mục dạng "Cha > Con"."""
    by_id = {section["id"]: section for section in sections}

    def path_for(section_id: str | None) -> str:
        if section_id is None or section_id not in by_id:
            return ""
        section = by_id[section_id]
        parent_path = path_for(section.get("parent_id"))
        heading = section["text"].strip()
        return f"{parent_path} > {heading}" if parent_path else heading

    return {section_id: path_for(section_id) for section_id in by_id}


def _split_oversized(paragraph: dict[str, Any]) -> list[dict[str, Any]]:
    """Tách paragraph vượt `MAX_CHUNK_TOKENS` thành nhiều mảnh theo ranh giới từ."""
    if _estimate_tokens(paragraph["text"]) <= MAX_CHUNK_TOKENS:
        return [paragraph]
    max_chars = MAX_CHUNK_TOKENS * 4
    pieces: list[str] = []
    current = ""
    for word in paragraph["text"].split():
        candidate = f"{current} {word}" if current else word
        if current and len(candidate) > max_chars:
            pieces.append(current)
            current = word
        else:
            current = candidate
    if current:
        pieces.append(current)
    return [{**paragraph, "text": piece} for piece in pieces]


def _flush(
    chunks: list[ChunkDraft],
    buffer: list[dict[str, Any]],
    section_path: str,
) -> None:
    if not buffer:
        return
    prefix = f"[{section_path}]\n" if section_path else ""
    text = prefix + " ".join(paragraph["text"] for paragraph in buffer)
    chunks.append(
        ChunkDraft(
            chunk_index=len(chunks),
            section_path=section_path or None,
            page_start=min(p["page_number"] for p in buffer),
            page_end=max(p["page_number"] for p in buffer),
            paragraph_ids=list(dict.fromkeys(p["id"] for p in buffer)),
            text=text,
            token_count=_estimate_tokens(text),
        )
    )


def _table_to_text(table: dict[str, Any]) -> str:
    rows_text = []
    for row in table.get("rows", []):
        cells = ["" if cell is None else str(cell) for cell in row.get("cells", [])]
        rows_text.append(" | ".join(cells))
    return "[Bảng]\n" + "\n".join(rows_text)


def build_chunks(content: dict[str, Any]) -> list[ChunkDraft]:
    """Cắt `DocumentIR.content` (mục 2 tài liệu pipeline) thành các ChunkDraft.

    Gom các paragraph liên tiếp cùng section lại với nhau cho tới khi vượt
    `MAX_CHUNK_TOKENS`, sau đó thêm mỗi bảng thành 1 chunk riêng.
    """
    # IR may carry malformed/empty paragraph nodes; they cannot be cited, skip them.
    paragraphs: list[dict[str, Any]] = [
        p
        for p in content.get("paragraphs", [])
        if isinstance(p.get("text"), str)
        and p["text"].strip()
        and isinstance(p.get("page_number"), int)
    ]
    sections: list[dict[str, Any]] = content.get("sections", [])
    tables: list[dict[str, Any]] = content.get("tables", [])
    section_paths = _build_section_paths(sections)

    chunks: list[ChunkDraft] = []
    buffer: list[dict[str, Any]] = []
    buffer_section_id: str | None = None
    buffer_tokens = 0

    for paragraph in (piece for p in paragraphs for piece in _split_oversized(p)):
        section_id = paragraph.get("section_id")
        tokens = _estimate_tokens(paragraph["text"])
        section_changed = bool(buffer) and section_id != buffer_section_id
        would_overflow = bool(buffer) and buffer_tokens + tokens > MAX_CHUNK_TOKENS
        if section_changed or would_overflow:
            _flush(chunks, buffer, section_paths.get(buffer_section_id, ""))
            buffer = []
            buffer_tokens = 0
        buffer.append(paragraph)
        buffer_section_id = section_id
        buffer_tokens += tokens

    _flush(chunks, buffer, section_paths.get(buffer_section_id, ""))

    for table in tables:
        if not table.get("rows"):
            continue
        text = _table_to_text(table)
        chunks.append(
            ChunkDraft(
                chunk_index=len(chunks),
                section_path=None,
                page_start=table["page_start"],
                page_end=table["page_end"],
                paragraph_ids=[],
                text=text,
                token_count=_estimate_tokens(text),
            )
        )

    return chunks
