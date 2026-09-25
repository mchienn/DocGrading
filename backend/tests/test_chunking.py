from __future__ import annotations

from app.services.chunking import MAX_CHUNK_TOKENS, build_chunks

_SAMPLE_CONTENT = {
    "schema_version": 1,
    "source": {"sha256": "a" * 64, "size_bytes": 100, "page_count": 2},
    "pages": [],
    "sections": [
        {
            "id": "section-1",
            "text": "2. Functional Requirements",
            "level": 1,
            "parent_id": None,
            "page_number": 1,
            "bbox": {},
        },
        {
            "id": "section-2",
            "text": "2.3 Use Cases",
            "level": 2,
            "parent_id": "section-1",
            "page_number": 2,
            "bbox": {},
        },
    ],
    "paragraphs": [
        {
            "id": "paragraph-1",
            "text": "FR-12: He thong phai cho phep dang nhap.",
            "section_id": "section-1",
            "page_number": 1,
            "bbox": {},
        },
        {
            "id": "paragraph-2",
            "text": "FR-13: He thong phai ghi log truy cap.",
            "section_id": "section-1",
            "page_number": 1,
            "bbox": {},
        },
        {
            "id": "paragraph-3",
            "text": "UC-01: Sinh vien dang nhap he thong.",
            "section_id": "section-2",
            "page_number": 2,
            "bbox": {},
        },
    ],
    "tables": [
        {
            "page_start": 2,
            "page_end": 2,
            "regions": [],
            "rows": [{"bbox": {}, "cells": ["Ten", "Vai tro"]}],
        }
    ],
}


def test_paragraphs_group_by_section() -> None:
    chunks = build_chunks(_SAMPLE_CONTENT)
    # 2 nhóm paragraph (section-1, section-2) + 1 chunk bảng = 3 chunk.
    assert len(chunks) == 3
    assert chunks[0].paragraph_ids == ["paragraph-1", "paragraph-2"]
    assert chunks[1].paragraph_ids == ["paragraph-3"]


def test_section_path_includes_parent() -> None:
    chunks = build_chunks(_SAMPLE_CONTENT)
    assert chunks[0].section_path == "2. Functional Requirements"
    assert chunks[1].section_path == "2. Functional Requirements > 2.3 Use Cases"


def test_table_becomes_its_own_chunk() -> None:
    chunks = build_chunks(_SAMPLE_CONTENT)
    table_chunk = chunks[-1]
    assert table_chunk.paragraph_ids == []
    assert "Ten | Vai tro" in table_chunk.text
    assert table_chunk.page_start == 2


def test_page_range_spans_grouped_paragraphs() -> None:
    chunks = build_chunks(_SAMPLE_CONTENT)
    assert chunks[0].page_start == 1
    assert chunks[0].page_end == 1


def test_long_section_splits_on_token_budget() -> None:
    long_paragraph_text = "Yeu cau dai. " * 200  # vượt xa MAX_CHUNK_TOKENS
    content = {
        **_SAMPLE_CONTENT,
        "paragraphs": [
            {
                "id": "paragraph-1",
                "text": long_paragraph_text,
                "section_id": "section-1",
                "page_number": 1,
                "bbox": {},
            },
            {
                "id": "paragraph-2",
                "text": "Cau ngan.",
                "section_id": "section-1",
                "page_number": 1,
                "bbox": {},
            },
        ],
        "tables": [],
    }
    chunks = build_chunks(content)
    assert len(chunks) == 2
    assert chunks[0].token_count <= MAX_CHUNK_TOKENS + 50  # nới lỏng nhẹ cho ước lượng


def test_malformed_or_empty_paragraphs_are_skipped() -> None:
    content = {
        **_SAMPLE_CONTENT,
        "paragraphs": [
            *_SAMPLE_CONTENT["paragraphs"],
            {"id": "no-text", "page_number": 1},
            {"id": "blank", "text": "   ", "section_id": "section-1", "page_number": 1},
            {"id": "no-page", "text": "Mồ côi", "section_id": "section-1"},
        ],
        "tables": [],
    }
    chunks = build_chunks(content)
    all_ids = [pid for chunk in chunks for pid in chunk.paragraph_ids]
    assert all_ids == ["paragraph-1", "paragraph-2", "paragraph-3"]
