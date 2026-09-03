"""Pure, bounded Document IR parser and structure extraction service."""

from __future__ import annotations

import asyncio
import math
import re
import uuid
from collections.abc import Mapping, Sequence
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from io import BytesIO
from statistics import median
from threading import RLock
from typing import Any

import pdfplumber
import sqlalchemy as sa
from pdfplumber.page import PDFPageAggregatorWithMarkedContent
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.models.analysis import DocumentIR
from app.models.submission import DocumentVersion, Submission
from app.services.pdf_validation import (
    PDFValidationError,
    PDFValidationResult,
    validate_pdf,
)

SCHEMA_VERSION: int = 1
PARSER_VERSION: str = "pypdf-pdfplumber-v1"

_TABLE_SOURCE_OBJECT_TYPES = ("line", "rect", "curve")
_MAX_TABLE_SOURCE_OBJECTS = 256
_MAX_TABLE_EDGES = 1024
_MAX_TABLE_INTERSECTIONS = 8192
_MAX_TABLE_CELLS = 4096
_MAX_TABLE_TEXT_CHARS = 100_000
_MAX_TABLE_TEXT_WORDS = 10_000
_TEXT_TABLE_MIN_WORDS_VERTICAL = 2
_TEXT_TABLE_MIN_WORDS_HORIZONTAL = 1
_TABLE_WORK_RESERVE = 4


# ponytail: this process-global hook is intentionally serialized for isolation.
_LAYOUT_HOOK_LOCK = RLock()
_ACTIVE_LAYOUT_BUDGET: ContextVar[_NodeBudget | None] = ContextVar(
    "active_layout_budget",
    default=None,
)


@contextmanager
def _bounded_layout_hook(budget: _NodeBudget):
    with _LAYOUT_HOOK_LOCK:
        original = PDFPageAggregatorWithMarkedContent.tag_cur_item

        def guarded_tag_cur_item(aggregator: Any) -> None:
            active_budget = _ACTIVE_LAYOUT_BUDGET.get()
            if active_budget is not None:
                active_budget.consume()
            original(aggregator)

        PDFPageAggregatorWithMarkedContent.tag_cur_item = guarded_tag_cur_item
        token = _ACTIVE_LAYOUT_BUDGET.set(budget)
        try:
            yield
        finally:
            _ACTIVE_LAYOUT_BUDGET.reset(token)
            PDFPageAggregatorWithMarkedContent.tag_cur_item = original


class DocumentIRExtractionError(RuntimeError):
    """Sanitized error raised when extraction fails unexpectedly."""

    def __init__(self, message: str = "Document IR extraction failed") -> None:
        super().__init__(message)


@dataclass(frozen=True)
class ParsedDocumentIR:
    """Immutable parsed Document IR alongside validation metadata."""

    validation: PDFValidationResult
    content: dict[str, Any]


async def get_or_build_document_ir(
    db: AsyncSession,
    document_version_id: uuid.UUID,
    data: bytes,
    *,
    rebuild: bool = False,
) -> DocumentIR:
    (
        await db.execute(
            sa.select(Submission)
            .join(DocumentVersion, DocumentVersion.submission_id == Submission.id)
            .where(DocumentVersion.id == document_version_id)
            .with_for_update(of=Submission)
        )
    ).scalar_one()
    document = (
        await db.execute(
            sa.select(DocumentVersion)
            .where(DocumentVersion.id == document_version_id)
            .with_for_update()
        )
    ).scalar_one()
    existing = (
        await db.execute(
            sa.select(DocumentIR).where(
                DocumentIR.document_version_id == document_version_id
            )
        )
    ).scalar_one_or_none()
    if existing is not None and not rebuild:
        return existing

    settings = get_settings()
    parsed = await asyncio.to_thread(
        parse_document_ir,
        data,
        max_size_bytes=settings.pdf_max_size_bytes,
        max_page_count=settings.pdf_max_page_count,
        max_nodes=settings.pdf_ir_max_nodes,
    )
    if (
        document.declared_sha256 is not None
        and document.declared_sha256 != parsed.validation.sha256
    ):
        raise PDFValidationError(
            "PDF_SHA256_MISMATCH",
            "PDF checksum does not match",
        )
    duplicate = (
        await db.execute(
            sa.select(DocumentVersion.id).where(
                DocumentVersion.submission_id == document.submission_id,
                DocumentVersion.sha256 == parsed.validation.sha256,
                DocumentVersion.id != document.id,
            )
        )
    ).scalar_one_or_none()
    if duplicate is not None:
        raise PDFValidationError("PDF_DUPLICATE", "Duplicate document version")

    if existing is None:
        existing = DocumentIR(
            document_version_id=document.id,
            schema_version=SCHEMA_VERSION,
            parser_version=PARSER_VERSION,
            content=parsed.content,
        )
        db.add(existing)
    else:
        existing.schema_version = SCHEMA_VERSION
        existing.parser_version = PARSER_VERSION
        existing.content = parsed.content
    await db.flush()
    return existing


@dataclass
class _NodeBudget:
    """Tracks and bounds structural node creation during parsing."""

    limit: int
    used: int = 0

    def consume(self, count: int = 1) -> None:
        if count < 0 or self.used + count > self.limit:
            raise PDFValidationError("PDF_STRUCTURE_LIMIT")
        self.used += count


@dataclass(frozen=True)
class _BBox:
    x0: float
    top: float
    x1: float
    bottom: float


@dataclass(frozen=True)
class _Word:
    text: str
    bbox: _BBox
    font_size: float
    font_name: str


@dataclass(frozen=True)
class _Line:
    text: str
    bbox: _BBox
    font_size: float
    font_name: str


_NUMBERED_HEADING = re.compile(r"^(\d+(?:\.\d+)*)(?:[.)])?\s+\S")


def _safe_bbox(
    values: Mapping[str, Any],
    *,
    page_width: float,
    page_height: float,
) -> _BBox:
    if (
        not math.isfinite(page_width)
        or not math.isfinite(page_height)
        or page_width <= 0
        or page_height <= 0
    ):
        raise PDFValidationError("PDF_IR_MALFORMED")
    try:
        coordinates = tuple(
            float(values[name]) for name in ("x0", "top", "x1", "bottom")
        )
    except (KeyError, TypeError, ValueError, OverflowError) as exc:
        raise PDFValidationError("PDF_IR_MALFORMED") from exc
    if not all(math.isfinite(value) for value in coordinates):
        raise PDFValidationError("PDF_IR_MALFORMED")
    x0, top, x1, bottom = coordinates
    if (
        x0 < 0
        or top < 0
        or x1 < x0
        or bottom < top
        or x1 > page_width
        or bottom > page_height
    ):
        raise PDFValidationError("PDF_IR_MALFORMED")
    return _BBox(*(round(value, 3) for value in coordinates))


def _word_from_pdf(
    word: Mapping[str, Any],
    *,
    page_width: float,
    page_height: float,
) -> _Word:
    bbox = _safe_bbox(word, page_width=page_width, page_height=page_height)
    try:
        font_size = float(word.get("size", 0.0))
    except (TypeError, ValueError, OverflowError) as exc:
        raise PDFValidationError("PDF_IR_MALFORMED") from exc
    if not math.isfinite(font_size) or font_size < 0:
        raise PDFValidationError("PDF_IR_MALFORMED")
    return _Word(
        text=str(word.get("text", "")),
        bbox=bbox,
        font_size=font_size,
        font_name=str(word.get("fontname", "")),
    )


def _union_bbox(first: _BBox, second: _BBox) -> _BBox:
    return _BBox(
        x0=round(min(first.x0, second.x0), 3),
        top=round(min(first.top, second.top), 3),
        x1=round(max(first.x1, second.x1), 3),
        bottom=round(max(first.bottom, second.bottom), 3),
    )


def _line_from_words(words: Sequence[_Word]) -> _Line:
    font_counts: dict[str, int] = {}
    for word in words:
        font_counts[word.font_name] = font_counts.get(word.font_name, 0) + 1
    font_name = min(
        font_counts,
        key=lambda name: (-font_counts[name], name),
    )
    return _Line(
        text=" ".join(word.text for word in words if word.text),
        bbox=(
            _union_bbox(words[0].bbox, words[-1].bbox)
            if len(words) == 1
            else _union_words_bbox(words)
        ),
        font_size=max(word.font_size for word in words),
        font_name=font_name,
    )


def _union_words_bbox(words: Sequence[_Word]) -> _BBox:
    bbox = words[0].bbox
    for word in words[1:]:
        bbox = _union_bbox(bbox, word.bbox)
    return bbox


def _group_lines(words: Sequence[_Word]) -> list[_Line]:
    ordered = sorted(words, key=lambda word: (word.bbox.top, word.bbox.x0))
    grouped: list[list[_Word]] = []
    for word in ordered:
        if not grouped or abs(word.bbox.top - grouped[-1][0].bbox.top) > 3:
            grouped.append([word])
        else:
            grouped[-1].append(word)
    return [
        _line_from_words(sorted(group, key=lambda word: word.bbox.x0))
        for group in grouped
    ]


def _extract_lines(
    page: Any,
    *,
    page_width: float,
    page_height: float,
    budget: _NodeBudget,
    excluded_bboxes: Sequence[_BBox] = (),
) -> tuple[list[_Line], list[_Line]]:
    extracted = page.extract_words(extra_attrs=["fontname", "size"])
    budget.consume(len(extracted))
    words = [
        _word_from_pdf(
            word,
            page_width=page_width,
            page_height=page_height,
        )
        for word in extracted
    ]
    all_lines = _group_lines(words)
    budget.consume(len(all_lines))
    if not excluded_bboxes:
        return all_lines, all_lines
    content_words = [
        word
        for word in words
        if not any(
            bbox.x0 <= (word.bbox.x0 + word.bbox.x1) / 2 <= bbox.x1
            and bbox.top <= (word.bbox.top + word.bbox.bottom) / 2 <= bbox.bottom
            for bbox in excluded_bboxes
        )
    ]
    content_lines = _group_lines(content_words)
    budget.consume(len(content_lines))
    return all_lines, content_lines


def _table_bbox(
    values: Any,
    *,
    page_width: float,
    page_height: float,
) -> _BBox:
    try:
        coordinates = tuple(float(value) for value in values)
    except (TypeError, ValueError, OverflowError) as exc:
        raise PDFValidationError("PDF_IR_MALFORMED") from exc
    if len(coordinates) != 4:
        raise PDFValidationError("PDF_IR_MALFORMED")
    return _safe_bbox(
        dict(zip(("x0", "top", "x1", "bottom"), coordinates, strict=True)),
        page_width=page_width,
        page_height=page_height,
    )


def _normalized_cell_boundaries(
    rows: Sequence[Sequence[Any]],
    *,
    page_width: float,
    page_height: float,
) -> list[tuple[float, float]]:
    boundaries: set[tuple[float, float]] = set()
    for row in rows:
        row_cells = getattr(row, "cells", row)
        for cell in row_cells:
            if cell is None:
                continue
            cell_bbox = _table_bbox(
                cell,
                page_width=page_width,
                page_height=page_height,
            )
            boundaries.add(
                (
                    round(cell_bbox.x0 / page_width, 3),
                    round(cell_bbox.x1 / page_width, 3),
                )
            )
    return sorted(boundaries)


def _table_bboxes_overlap(first: _BBox, second: _BBox) -> bool:
    intersection_width = min(first.x1, second.x1) - max(first.x0, second.x0)
    intersection_height = min(first.bottom, second.bottom) - max(
        first.top,
        second.top,
    )
    if intersection_width <= 0 or intersection_height <= 0:
        return False
    intersection = intersection_width * intersection_height
    first_area = (first.x1 - first.x0) * (first.bottom - first.top)
    second_area = (second.x1 - second.x0) * (second.bottom - second.top)
    return intersection / min(first_area, second_area) >= 0.8


def _cluster_count(
    values: Sequence[float],
    *,
    tolerance: float = 1.0,
    min_size: int = 1,
) -> int:
    ordered = sorted(values)
    if not ordered:
        return 0
    count = 0
    cluster_size = 1
    previous = ordered[0]
    for value in ordered[1:]:
        if value > previous + tolerance:
            count += cluster_size >= min_size
            cluster_size = 1
        else:
            cluster_size += 1
        previous = value
    return count + (cluster_size >= min_size)


def _estimate_text_edges(words: Sequence[Mapping[str, Any]]) -> int:
    vertical_clusters = sum(
        _cluster_count(
            [float(word[key]) for word in words],
            min_size=_TEXT_TABLE_MIN_WORDS_VERTICAL,
        )
        for key in ("x0", "x1")
    )
    vertical_clusters += _cluster_count(
        [
            (float(word["x0"]) + float(word["x1"])) / 2
            for word in words
        ],
        min_size=_TEXT_TABLE_MIN_WORDS_VERTICAL,
    )
    horizontal_clusters = _cluster_count(
        [float(word["top"]) for word in words],
        min_size=_TEXT_TABLE_MIN_WORDS_HORIZONTAL,
    )
    return (vertical_clusters + 1 if vertical_clusters else 0) + (
        horizontal_clusters * 2
    )


def _text_table_has_column_gap(
    words: Sequence[Mapping[str, Any]],
    table_bbox: _BBox,
    *,
    page_width: float,
) -> bool:
    in_table = [
        word
        for word in words
        if table_bbox.x0 <= (word["x0"] + word["x1"]) / 2 <= table_bbox.x1
        and table_bbox.top <= (word["top"] + word["bottom"]) / 2 <= table_bbox.bottom
    ]
    in_table.sort(key=lambda word: (word["top"], word["x0"]))
    return any(
        next_word["x0"] - word["x1"] >= max(12.0, page_width * 0.02)
        for word, next_word in zip(in_table, in_table[1:])
        if abs(next_word["top"] - word["top"]) <= 3
    )


def _extract_tables(
    page: Any,
    *,
    page_number: int,
    page_width: float,
    page_height: float,
    budget: _NodeBudget,
) -> list[tuple[dict[str, Any], list[tuple[float, float]], int, list[_BBox]]]:
    objects = page.objects
    source_count = sum(
        len(objects.get(object_type, ()))
        for object_type in _TABLE_SOURCE_OBJECT_TYPES
    )
    estimated_edges = (
        len(objects.get("line", ()))
        + (4 * len(objects.get("rect", ())))
        + sum(
            max(0, len(curve.get("pts", ())) - 1)
            for curve in objects.get("curve", ())
        )
    )
    if (
        source_count > _MAX_TABLE_SOURCE_OBJECTS
        or estimated_edges > _MAX_TABLE_EDGES
        or estimated_edges * estimated_edges > _MAX_TABLE_INTERSECTIONS
        or estimated_edges * estimated_edges > _MAX_TABLE_CELLS
        or budget.used + estimated_edges + _TABLE_WORK_RESERVE > budget.limit
    ):
        raise PDFValidationError("PDF_STRUCTURE_LIMIT")
    edges = page.edges
    if len(edges) > _MAX_TABLE_EDGES:
        raise PDFValidationError("PDF_STRUCTURE_LIMIT")
    budget.consume(len(edges))
    if len(edges) * len(edges) > _MAX_TABLE_INTERSECTIONS:
        raise PDFValidationError("PDF_STRUCTURE_LIMIT")

    ruled_tables = page.find_tables()
    ruled_bboxes = [
        _table_bbox(
            table.bbox,
            page_width=page_width,
            page_height=page_height,
        )
        for table in ruled_tables
    ]
    candidates: list[tuple[Any, Any, _BBox, bool]] = [
        (page, table, bbox, False)
        for table, bbox in zip(ruled_tables, ruled_bboxes, strict=True)
    ]

    def keep_object(obj: Mapping[str, Any]) -> bool:
        try:
            center_x = (float(obj["x0"]) + float(obj["x1"])) / 2
            center_y = (float(obj["top"]) + float(obj["bottom"])) / 2
        except (KeyError, TypeError, ValueError, OverflowError):
            return True
        return not any(
            bbox.x0 <= center_x <= bbox.x1
            and bbox.top <= center_y <= bbox.bottom
            for bbox in ruled_bboxes
        )

    text_page = page.filter(keep_object)
    text_char_count = len(text_page.objects.get("char", ()))
    if text_char_count > _MAX_TABLE_TEXT_CHARS:
        raise PDFValidationError("PDF_STRUCTURE_LIMIT")
    text_words = text_page.extract_words()
    if len(text_words) > _MAX_TABLE_TEXT_WORDS:
        raise PDFValidationError("PDF_STRUCTURE_LIMIT")
    budget.consume(len(text_words))
    text_edges = _estimate_text_edges(text_words)
    if (
        text_edges > _MAX_TABLE_EDGES
        or text_edges * text_edges > _MAX_TABLE_INTERSECTIONS
        or text_edges * text_edges > _MAX_TABLE_CELLS
        or budget.used + _TABLE_WORK_RESERVE > budget.limit
    ):
        raise PDFValidationError("PDF_STRUCTURE_LIMIT")
    text_tables = text_page.find_tables(
        {
            "vertical_strategy": "text",
            "horizontal_strategy": "text",
            "min_words_vertical": _TEXT_TABLE_MIN_WORDS_VERTICAL,
            "min_words_horizontal": _TEXT_TABLE_MIN_WORDS_HORIZONTAL,
        }
    )
    for table in text_tables:
        table_bbox = _table_bbox(
            table.bbox,
            page_width=page_width,
            page_height=page_height,
        )
        if (
            _text_table_has_column_gap(
                text_words,
                table_bbox,
                page_width=page_width,
            )
            and not any(
                _table_bboxes_overlap(table_bbox, ruled_bbox)
                for ruled_bbox in ruled_bboxes
            )
            and not any(
                _table_bboxes_overlap(table_bbox, candidate_bbox)
                for (
                    _candidate_page,
                    _candidate,
                    candidate_bbox,
                    _is_text,
                ) in candidates
            )
        ):
            candidates.append((text_page, table, table_bbox, True))

    candidates.sort(
        key=lambda candidate: (
            candidate[2].top,
            candidate[2].x0,
            candidate[2].bottom,
            candidate[2].x1,
        )
    )
    parsed_tables = []
    for _table_page, table, table_bbox, is_text in candidates:
        budget.consume(2)
        table_bbox = _table_bbox(
            table.bbox,
            page_width=page_width,
            page_height=page_height,
        )
        try:
            extracted_rows = table.extract()
            table_rows = table.rows
        except (AttributeError, TypeError, ValueError, IndexError) as exc:
            raise PDFValidationError("PDF_IR_MALFORMED") from exc
        rows: list[dict[str, Any]] = []
        try:
            row_pairs = zip(extracted_rows, table_rows, strict=True)
            for extracted_row, table_row in row_pairs:
                budget.consume()
                row_bbox = _table_bbox(
                    table_row.bbox,
                    page_width=page_width,
                    page_height=page_height,
                )
                cell_values: list[dict[str, Any] | None] = []
                for text, cell in zip(
                    extracted_row,
                    table_row.cells,
                    strict=True,
                ):
                    budget.consume()
                    if cell is None:
                        cell_values.append(None)
                        continue
                    cell_bbox = _table_bbox(
                        cell,
                        page_width=page_width,
                        page_height=page_height,
                    )
                    cell_text = "" if text is None else " ".join(str(text).split())
                    cell_values.append(
                        {
                            "text": cell_text,
                            "page_number": page_number,
                            "bbox": {
                                "x0": cell_bbox.x0,
                                "top": cell_bbox.top,
                                "x1": cell_bbox.x1,
                                "bottom": cell_bbox.bottom,
                            },
                        }
                    )
                if is_text and not any(
                    cell is not None and cell["text"] for cell in cell_values
                ):
                    continue
                rows.append(
                    {
                        "page_number": page_number,
                        "bbox": {
                            "x0": row_bbox.x0,
                            "top": row_bbox.top,
                            "x1": row_bbox.x1,
                            "bottom": row_bbox.bottom,
                        },
                        "cells": cell_values,
                    }
                )
        except PDFValidationError:
            raise
        except (AttributeError, TypeError, ValueError, IndexError) as exc:
            raise PDFValidationError("PDF_IR_MALFORMED") from exc
        parsed_tables.append(
            (
                {
                    "page_start": page_number,
                    "page_end": page_number,
                    "regions": [
                        {
                            "page_number": page_number,
                            "bbox": {
                                "x0": table_bbox.x0,
                                "top": table_bbox.top,
                                "x1": table_bbox.x1,
                                "bottom": table_bbox.bottom,
                            },
                        }
                    ],
                    "rows": rows,
                },
                _normalized_cell_boundaries(
                    table_rows,
                    page_width=page_width,
                    page_height=page_height,
                ),
                len(table_rows[0].cells) if table_rows else 0,
                [table_bbox],
            )
        )
    return parsed_tables


def _is_heading(
    line: _Line,
    *,
    median_body_size: float,
    typography_ranks: Mapping[float, int],
    numbering_has_nested_level: bool = False,
) -> tuple[bool, int]:
    numbered = _NUMBERED_HEADING.match(line.text)
    if numbered:
        level = numbered.group(1).count(".") + 1
        if not line.text.rstrip().endswith((".", "!", "?")) and (
            level >= 2
            or numbering_has_nested_level
            or line.font_size >= median_body_size * 1.25
            or "bold" in line.font_name.lower()
        ):
            return True, level
        return False, 0
    stripped = line.text.rstrip()
    if (
        not stripped
        or len(stripped) > 80
        or stripped.endswith((".", "!", "?"))
        or (
            line.font_size < median_body_size * 1.25
            and "bold" not in line.font_name.lower()
        )
    ):
        return False, 0
    return True, typography_ranks[line.font_size]


def _parse_pages(
    pages: Sequence[Any],
    budget: _NodeBudget,
    sections: list[dict[str, Any]] | None = None,
    paragraphs: list[dict[str, Any]] | None = None,
    tables: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    """Extract bounded page geometry and structural containers."""
    all_sections = sections if sections is not None else []
    all_paragraphs = paragraphs if paragraphs is not None else []
    all_tables = tables if tables is not None else []
    parsed_pages: list[dict[str, Any]] = []
    section_stack: list[tuple[int, str]] = []
    previous_page_table: (
        tuple[dict[str, Any], list[tuple[float, float]], int, float] | None
    ) = None
    for page_number, page in enumerate(pages, start=1):
        try:
            page_width = float(page.width)
            page_height = float(page.height)
        except (AttributeError, TypeError, ValueError, OverflowError) as exc:
            raise PDFValidationError("PDF_IR_MALFORMED") from exc
        if (
            not math.isfinite(page_width)
            or not math.isfinite(page_height)
            or page_width <= 0
            or page_height <= 0
        ):
            raise PDFValidationError("PDF_IR_MALFORMED")

        page_table_regions = _extract_tables(
            page,
            page_number=page_number,
            page_width=page_width,
            page_height=page_height,
            budget=budget,
        )
        page_table_ids: list[str] = []
        current_page_table = None
        for local_table, boundaries, slot_count, _table_bboxes in page_table_regions:
            if previous_page_table is not None:
                (
                    prior_table,
                    prior_boundaries,
                    prior_slots,
                    prior_height,
                ) = previous_page_table
                prior_region = prior_table["regions"][-1]["bbox"]
                current_region = local_table["regions"][0]["bbox"]
                can_merge = (
                    prior_table["page_end"] == page_number - 1
                    and prior_region["bottom"] >= 0.8 * prior_height
                    and current_region["top"] <= 0.2 * page_height
                    and prior_slots == slot_count
                    and len(prior_boundaries) == len(boundaries)
                    and boundaries
                    and max(
                        max(abs(left - prior_left), abs(right - prior_right))
                        for (left, right), (prior_left, prior_right) in zip(
                            boundaries,
                            prior_boundaries,
                            strict=True,
                        )
                    )
                    <= 0.02
                )
            else:
                can_merge = False
            if can_merge:
                (
                    prior_table,
                    _prior_boundaries,
                    _prior_slots,
                    _prior_height,
                ) = previous_page_table
                if prior_table["rows"] and local_table["rows"]:
                    prior_header = [
                        cell["text"] if cell is not None else None
                        for cell in prior_table["rows"][0]["cells"]
                    ]
                    current_header = [
                        cell["text"] if cell is not None else None
                        for cell in local_table["rows"][0]["cells"]
                    ]
                    if current_header == prior_header:
                        local_table["rows"] = local_table["rows"][1:]
                prior_table["rows"].extend(local_table["rows"])
                prior_table["regions"].extend(local_table["regions"])
                prior_table["page_end"] = page_number
                table_id = prior_table["id"]
                current_page_table = (
                    prior_table,
                    boundaries,
                    slot_count,
                    page_height,
                )
            else:
                table_id = f"table-{len(all_tables) + 1}"
                local_table["id"] = table_id
                all_tables.append(local_table)
                current_page_table = (
                    local_table,
                    boundaries,
                    slot_count,
                    page_height,
                )
            page_table_ids.append(table_id)
        previous_page_table = current_page_table
        table_bboxes = [
            bbox
            for _local_table, _boundaries, _slot_count, bboxes in page_table_regions
            for bbox in bboxes
        ]
        all_lines, content_lines = _extract_lines(
            page,
            page_width=page_width,
            page_height=page_height,
            budget=budget,
            excluded_bboxes=table_bboxes,
        )
        typography_ranks = {
            size: rank
            for rank, size in enumerate(
                sorted({line.font_size for line in content_lines}, reverse=True),
                start=1,
            )
        }
        numbering_has_nested_level = any(
            match and match.group(1).count(".") + 1 >= 2
            for line in content_lines
            for match in [_NUMBERED_HEADING.match(line.text)]
        )
        body_like_sizes = [
            line.font_size
            for line in content_lines
            if (line.text.rstrip().endswith((".", "!", "?")) or len(line.text) >= 40)
        ]
        if body_like_sizes:
            median_body_size = median(body_like_sizes)
        else:
            lower_sizes = sorted(line.font_size for line in content_lines)
            lower_count = max(1, (len(lower_sizes) + 1) // 2)
            median_body_size = median(lower_sizes[:lower_count] or [0.0])
        heading_lines: set[int] = set()
        page_heading_ids: list[str] = []
        page_lines = [line.text for line in all_lines]
        current_section_id: str | None = section_stack[-1][1] if section_stack else None
        line_section_ids: dict[int, str | None] = {}
        for line_index, line in enumerate(content_lines):
            is_heading, level = _is_heading(
                line,
                median_body_size=median_body_size,
                typography_ranks=typography_ranks,
                numbering_has_nested_level=numbering_has_nested_level,
            )
            if is_heading:
                budget.consume()
                while section_stack and section_stack[-1][0] >= level:
                    section_stack.pop()
                parent_id = section_stack[-1][1] if section_stack else None
                section_id = f"section-{len(all_sections) + 1}"
                all_sections.append(
                    {
                        "id": section_id,
                        "text": line.text,
                        "level": level,
                        "parent_id": parent_id,
                        "page_number": page_number,
                        "bbox": {
                            "x0": line.bbox.x0,
                            "top": line.bbox.top,
                            "x1": line.bbox.x1,
                            "bottom": line.bbox.bottom,
                        },
                    }
                )
                section_stack.append((level, section_id))
                current_section_id = section_id
                heading_lines.add(line_index)
                page_heading_ids.append(section_id)
            else:
                line_section_ids[line_index] = current_section_id

        page_paragraph_ids: list[str] = []
        paragraph_lines: list[tuple[_Line, str | None]] = []
        for line_index, line in enumerate(content_lines):
            if line_index in heading_lines or not line.text:
                if paragraph_lines:
                    budget.consume()
                    _append_paragraph(
                        paragraph_lines,
                        page_number,
                        all_paragraphs,
                        page_paragraph_ids,
                    )
                    paragraph_lines = []
                continue
            section_id = line_section_ids[line_index]
            if paragraph_lines:
                previous, previous_section = paragraph_lines[-1]
                vertical_gap = line.bbox.top - previous.bbox.bottom
                if (
                    section_id != previous_section
                    or abs(line.bbox.x0 - previous.bbox.x0) > 12
                    or vertical_gap
                    > max(6, (previous.bbox.bottom - previous.bbox.top) * 1.5)
                ):
                    budget.consume()
                    _append_paragraph(
                        paragraph_lines,
                        page_number,
                        all_paragraphs,
                        page_paragraph_ids,
                    )
                    paragraph_lines = []
            paragraph_lines.append((line, section_id))
        if paragraph_lines:
            budget.consume()
            _append_paragraph(
                paragraph_lines,
                page_number,
                all_paragraphs,
                page_paragraph_ids,
            )
        parsed_pages.append(
            {
                "number": page_number,
                "width": round(page_width, 3),
                "height": round(page_height, 3),
                "text": "\n".join(page_lines),
                "headings": page_heading_ids,
                "paragraphs": page_paragraph_ids,
                "tables": page_table_ids,
            }
        )
    return parsed_pages


def _append_paragraph(
    lines: Sequence[tuple[_Line, str | None]],
    page_number: int,
    paragraphs: list[dict[str, Any]],
    page_paragraph_ids: list[str],
) -> None:
    first_line = lines[0][0]
    bbox = first_line.bbox
    for line, _section_id in lines[1:]:
        bbox = _union_bbox(bbox, line.bbox)
    paragraph_id = f"paragraph-{len(paragraphs) + 1}"
    paragraphs.append(
        {
            "id": paragraph_id,
            "text": " ".join(line.text for line, _section_id in lines),
            "section_id": lines[0][1],
            "page_number": page_number,
            "bbox": {
                "x0": bbox.x0,
                "top": bbox.top,
                "x1": bbox.x1,
                "bottom": bbox.bottom,
            },
        }
    )
    page_paragraph_ids.append(paragraph_id)


def _assemble_ir(
    validation: PDFValidationResult,
    pages: list[dict[str, Any]],
    sections: list[dict[str, Any]],
    paragraphs: list[dict[str, Any]],
    tables: list[dict[str, Any]],
) -> dict[str, Any]:
    """Assemble versioned root Document IR payload."""
    return {
        "schema_version": SCHEMA_VERSION,
        "source": {
            "sha256": validation.sha256,
            "size_bytes": validation.size_bytes,
            "page_count": validation.page_count,
        },
        "pages": pages,
        "sections": sections,
        "paragraphs": paragraphs,
        "tables": tables,
    }


def parse_document_ir(
    data: bytes,
    *,
    max_size_bytes: int = 50_000_000,
    max_page_count: int = 100,
    max_nodes: int = 100_000,
) -> ParsedDocumentIR:
    """Validate untrusted PDF bytes and extract bounded Document IR."""
    validation = validate_pdf(
        data,
        max_size_bytes=max_size_bytes,
        max_page_count=max_page_count,
    )
    budget = _NodeBudget(limit=max_nodes)
    budget.consume(validation.page_count)
    sections: list[dict[str, Any]] = []
    paragraphs: list[dict[str, Any]] = []
    tables: list[dict[str, Any]] = []
    try:
        with (
            pdfplumber.open(BytesIO(data)) as pdf,
            _bounded_layout_hook(budget),
        ):
            pages = _parse_pages(
                pdf.pages,
                budget,
                sections,
                paragraphs,
                tables,
            )
    except PDFValidationError:
        raise
    except Exception as exc:
        for nested in (exc.__cause__, exc.__context__, *exc.args):
            if isinstance(nested, PDFValidationError):
                raise nested from None
        raise DocumentIRExtractionError("Document IR extraction failed") from exc
    content = _assemble_ir(validation, pages, sections, paragraphs, tables)
    return ParsedDocumentIR(validation=validation, content=content)
