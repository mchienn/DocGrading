"""Pure, bounded Document IR parser and structure extraction service."""

from __future__ import annotations

import asyncio
import math
import re
import unicodedata
import uuid
from collections import Counter
from collections.abc import Mapping, Sequence
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from heapq import nsmallest
from io import BytesIO
from statistics import median
from threading import RLock
from typing import Any
from urllib.parse import urlsplit, urlunsplit

import pdfplumber
import sqlalchemy as sa
from pdfplumber.page import PDFPageAggregatorWithMarkedContent
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.models.analysis import DocumentIR
from app.models.submission import DocumentVersion, Submission
from app.services.pdf_validation import (
    PDFLink,
    PDFValidationError,
    PDFValidationResult,
    _suppress_untrusted_pdf_logs,
    validate_pdf,
)

SCHEMA_VERSION: int = 2
PARSER_VERSION: str = "pypdf-pdfplumber-v5"

_TABLE_SOURCE_OBJECT_TYPES = ("line", "rect", "curve")
_MAX_TABLE_SOURCE_OBJECTS = 256
_MAX_TABLE_EDGES = 1024
_MAX_TABLE_INTERSECTIONS = 8192
_MAX_TABLE_FINDER_WORK = 1_000_000
_MAX_TEXT_TABLE_FINDER_WORK = 2_000_000
_MIN_RULED_TABLE_INTERSECTIONS = 4
_MAX_TABLE_CELLS = 4096
_MAX_TABLE_TEXT_CHARS = 100_000
_MAX_VECTOR_SOURCE_OBJECTS = 512
_MAX_VECTOR_EDGES = 1024
_MAX_TABLE_TEXT_WORDS = 10_000
_TEXT_TABLE_MIN_WORDS_VERTICAL = 2
_TEXT_TABLE_MIN_WORDS_HORIZONTAL = 1
_TABLE_WORK_RESERVE = 4
_MAX_LINK_LABEL_WORK = 100_000
_MAX_LINK_LABEL_WORDS = 256
_MAX_LINK_LABEL_CHARS = 2_048
_MAX_VISIBLE_URL_PARTS = 64

_BIBLIOGRAPHY_HEADING = re.compile(
    r"^(?:references?|bibliography|works cited|literature cited|"
    r"references and bibliography|tai lieu tham khao)$",
    re.IGNORECASE,
)
_PAGE_NUMBER = re.compile(
    r"^(?:[-–—|]\s*)?(?:page\s*)?\d+" r"(?:(?:\s*(?:/|\||of)\s*)\d+)?(?:\s*[-–—|])?$",
    re.IGNORECASE,
)


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


def _validate_persisted_document_ir(ir: DocumentIR) -> None:
    content = ir.content
    if not isinstance(content, Mapping):
        raise DocumentIRExtractionError()
    schema_version = content.get("schema_version")
    if (
        type(schema_version) is not int
        or schema_version <= 0
        or schema_version != ir.schema_version
        or any(
            not isinstance(content.get(field), list)
            for field in (
                "pages",
                "sections",
                "paragraphs",
                "tables",
                *(("links",) if schema_version >= 2 else ()),
            )
        )
    ):
        raise DocumentIRExtractionError()

    source = content.get("source")
    if not isinstance(source, Mapping):
        raise DocumentIRExtractionError()
    sha256 = source.get("sha256")
    size_bytes = source.get("size_bytes")
    page_count = source.get("page_count")
    if (
        not isinstance(sha256, str)
        or re.fullmatch(r"[0-9a-f]{64}", sha256) is None
        or type(size_bytes) is not int
        or size_bytes <= 0
        or type(page_count) is not int
        or page_count <= 0
    ):
        raise DocumentIRExtractionError()


def _validation_report_with_links(
    validation: PDFValidationResult,
    content: Mapping[str, Any],
) -> dict[str, Any]:
    report = validation.report
    diagnostics = list(report["diagnostics"])
    for link in content.get("links", ()):
        status = link.get("status")
        if status not in {"MISMATCH", "NEEDS_REVIEW"} or len(diagnostics) >= 25:
            continue
        bbox = link.get("bbox")
        diagnostics.append(
            {
                "code": (
                    "PDF_LINK_TARGET_MISMATCH"
                    if status == "MISMATCH"
                    else "PDF_LINK_TARGET_UNVERIFIED"
                ),
                "category": "INTEGRITY",
                "disposition": "REVIEW",
                "scope": "REGION" if bbox is not None else "PAGE",
                "page_number": link["page_number"],
                "bbox": bbox,
                "metrics": {},
                "message_key": (
                    "pdf_link_target_mismatch"
                    if status == "MISMATCH"
                    else "pdf_link_target_unverified"
                ),
                "action_key": "pdf.review_link_target",
            }
        )
    if diagnostics:
        report["outcome"] = "ACCEPTED_WITH_WARNINGS"
    report["diagnostics"] = diagnostics
    return report


def _accepted_replay_report(report: object) -> dict[str, Any]:
    diagnostics: list[dict[str, Any]] = []
    if isinstance(report, Mapping):
        stored_diagnostics = report.get("diagnostics")
        if isinstance(stored_diagnostics, list):
            diagnostics = [
                item.copy()
                for item in stored_diagnostics
                if isinstance(item, dict)
                and item.get("category") != "SYSTEM"
                and item.get("disposition") in {"WARN", "REVIEW"}
            ][:25]
    return {
        "schema_version": 1,
        "outcome": "ACCEPTED_WITH_WARNINGS" if diagnostics else "ACCEPTED",
        "diagnostics": diagnostics,
    }


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
    if (
        existing is not None
        and not rebuild
        and existing.schema_version == SCHEMA_VERSION
        and existing.parser_version == PARSER_VERSION
    ):
        _validate_persisted_document_ir(existing)
        document.validation_report = _accepted_replay_report(
            getattr(document, "validation_report", None)
        )
        return existing

    settings = get_settings()
    parsed = await asyncio.to_thread(
        parse_document_ir,
        data,
        max_size_bytes=settings.pdf_max_size_bytes,
        max_decoded_bytes=settings.pdf_max_decoded_bytes,
        max_page_count=settings.pdf_max_page_count,
        max_nodes=settings.pdf_ir_max_nodes,
    )
    document.validation_report = _validation_report_with_links(
        parsed.validation,
        parsed.content,
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
    superscript_markers: tuple[tuple[int, int, int], ...] = ()


_NUMBERED_HEADING = re.compile(r"^(\d+(?:\.\d+)*)(?:[.)])?\s+\S")


def _safe_bbox(
    values: Mapping[str, Any],
    *,
    page_width: float,
    page_height: float,
    clip_to_page: bool = False,
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
    if x1 < x0 or bottom < top:
        raise PDFValidationError("PDF_IR_MALFORMED")
    if clip_to_page:
        if x1 <= 0 or bottom <= 0 or x0 >= page_width or top >= page_height:
            raise PDFValidationError("PDF_IR_MALFORMED")
        x0 = min(max(x0, 0.0), page_width)
        top = min(max(top, 0.0), page_height)
        x1 = min(max(x1, 0.0), page_width)
        bottom = min(max(bottom, 0.0), page_height)
    elif x0 < 0 or top < 0 or x1 > page_width or bottom > page_height:
        raise PDFValidationError("PDF_IR_MALFORMED")
    if x1 < x0 or bottom < top:
        raise PDFValidationError("PDF_IR_MALFORMED")
    return _BBox(*(round(value, 3) for value in (x0, top, x1, bottom)))


def _word_from_pdf(
    word: Mapping[str, Any],
    *,
    page_width: float,
    page_height: float,
) -> _Word:
    bbox = _safe_bbox(
        word,
        page_width=page_width,
        page_height=page_height,
        clip_to_page=True,
    )
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


def _union_words_bbox(words: Sequence[_Word]) -> _BBox:
    first = words[0].bbox
    for word in words[1:]:
        first = _union_bbox(first, word.bbox)
    return first


def _line_from_words(words: Sequence[_Word]) -> _Line:
    visible = [word for word in words if word.text]
    body_size = median([word.font_size for word in visible])
    body_bottom = median(
        [word.bbox.bottom for word in visible if word.font_size >= body_size * 0.9]
    )
    parts: list[str] = []
    markers: list[tuple[int, int, int]] = []
    offset = 0
    for index, word in enumerate(visible):
        if parts:
            offset += 1
        start = offset
        parts.append(word.text)
        offset += len(word.text)
        previous = visible[index - 1] if index > 0 else None
        previous_letters = (
            re.findall(r"[A-Za-zÀ-ỹ]", previous.text) if previous is not None else []
        )
        adjacent_to_text = bool(
            previous is not None
            and len(previous_letters) >= 2
            and word.bbox.x0 - previous.bbox.x1 <= max(1.5, body_size * 0.2)
        )
        if (
            previous is not None
            and re.fullmatch(r"[1-9]\d{0,3}", word.text)
            and (
                previous.text.rstrip().endswith((".", ",", ";", ":", "!", "?"))
                or adjacent_to_text
            )
            and word.font_size <= body_size * 0.8
            and word.bbox.bottom <= body_bottom - body_size * 0.2
        ):
            markers.append((start, offset, int(word.text)))
    font_counts: dict[str, int] = {}
    for word in visible:
        font_counts[word.font_name] = font_counts.get(word.font_name, 0) + 1
    font_name = min(
        font_counts,
        key=lambda name: (-font_counts[name], name),
    )
    return _Line(
        text=" ".join(parts),
        bbox=_union_words_bbox(visible),
        font_size=max(word.font_size for word in visible),
        font_name=font_name,
        superscript_markers=tuple(markers),
    )


def _normalize_heading(text: str) -> str:
    normalized = unicodedata.normalize("NFKD", text)
    normalized = "".join(char for char in normalized if not unicodedata.combining(char))
    return " ".join(normalized.casefold().split()).strip(" .:")


def _is_margin_noise(line: _Line, *, page_height: float) -> bool:
    if line.bbox.top > 48 and line.bbox.bottom < page_height - 48:
        return False
    return bool(_PAGE_NUMBER.fullmatch(line.text.strip()))


def _word_rows(words: Sequence[_Word]) -> list[list[_Word]]:
    rows: list[list[_Word]] = []
    for word in sorted(words, key=lambda item: (item.bbox.top, item.bbox.x0)):
        if not rows or abs(word.bbox.top - rows[-1][0].bbox.top) > 3:
            rows.append([word])
        else:
            rows[-1].append(word)
    return [sorted(row, key=lambda item: item.bbox.x0) for row in rows]


def _column_split(
    words: Sequence[_Word],
    rows: Sequence[Sequence[_Word]],
    *,
    page_width: float,
) -> float | None:
    if len(words) < 16 or len(rows) < 6:
        return None
    ordered = sorted(words, key=lambda word: word.bbox.x0)
    best_gap: tuple[float, float] | None = None
    minimum_gap = max(48.0, page_width * 0.08)
    minimum_words = max(8, len(words) // 6)
    for index, (left, right) in enumerate(zip(ordered, ordered[1:], strict=False)):
        gap = right.bbox.x0 - left.bbox.x0
        split = (left.bbox.x0 + right.bbox.x0) / 2
        if (
            gap < minimum_gap
            or not page_width * 0.15 < split < page_width * 0.85
            or index + 1 < minimum_words
            or len(words) - index - 1 < minimum_words
        ):
            continue
        left_words = ordered[: index + 1]
        right_words = ordered[index + 1 :]
        left_extent = max(word.bbox.x1 for word in left_words) - min(
            word.bbox.x0 for word in left_words
        )
        right_extent = max(word.bbox.x1 for word in right_words) - min(
            word.bbox.x0 for word in right_words
        )
        left_top = min(word.bbox.top for word in left_words)
        left_bottom = max(word.bbox.bottom for word in left_words)
        right_top = min(word.bbox.top for word in right_words)
        right_bottom = max(word.bbox.bottom for word in right_words)
        vertical_overlap = max(
            0.0, min(left_bottom, right_bottom) - max(left_top, right_top)
        )
        minimum_span = min(left_bottom - left_top, right_bottom - right_top)
        overlap_top = max(left_top, right_top)
        overlap_bottom = min(left_bottom, right_bottom)
        left_rows = sum(
            any(word.bbox.x0 <= split for word in row)
            and row[0].bbox.top <= overlap_bottom
            and max(word.bbox.bottom for word in row) >= overlap_top
            for row in rows
        )
        right_rows = sum(
            any(word.bbox.x0 > split for word in row)
            and row[0].bbox.top <= overlap_bottom
            and max(word.bbox.bottom for word in row) >= overlap_top
            for row in rows
        )
        if (
            left_extent >= page_width * 0.18
            and right_extent >= page_width * 0.18
            and minimum_span > 0
            and vertical_overlap >= minimum_span * 0.5
            and left_rows >= 3
            and right_rows >= 3
            and (best_gap is None or gap > best_gap[0])
        ):
            best_gap = (gap, split)
    return best_gap[1] if best_gap else None


def _split_columns(words: Sequence[_Word], *, page_width: float) -> list[list[_Word]]:
    split = _column_split(words, _word_rows(words), page_width=page_width)
    if split is None:
        return [list(words)]
    return [
        [word for word in words if word.bbox.x0 <= split],
        [word for word in words if word.bbox.x0 > split],
    ]


def _group_lines(
    words: Sequence[_Word], *, page_width: float | None = None
) -> list[_Line]:
    rows = _word_rows(words)
    if page_width is None:
        return [_line_from_words(row) for row in rows]
    split = _column_split(words, rows, page_width=page_width)
    if split is None:
        return [_line_from_words(row) for row in rows]

    body_size = median([word.font_size for word in words]) if words else 0.0
    minimum_gutter = max(36.0, page_width * 0.06)
    lines: list[_Line] = []
    segment: list[list[_Word]] = []

    def flush_segment() -> None:
        if not segment:
            return
        left_rows: list[list[_Word]] = []
        right_rows: list[list[_Word]] = []
        for row in segment:
            left = [word for word in row if word.bbox.x0 <= split]
            right = [word for word in row if word.bbox.x0 > split]
            if left:
                left_rows.append(left)
            if right:
                right_rows.append(right)
        if not left_rows or not right_rows:
            lines.extend(_line_from_words(row) for row in segment)
        else:
            lines.extend(_line_from_words(row) for row in left_rows)
            lines.extend(_line_from_words(row) for row in right_rows)
        segment.clear()

    for row in rows:
        left = [word for word in row if word.bbox.x0 <= split]
        right = [word for word in row if word.bbox.x0 > split]
        crosses_gutter = any(word.bbox.x0 < split < word.bbox.x1 for word in row)
        between_gap = (
            min(word.bbox.x0 for word in right) - max(word.bbox.x1 for word in left)
            if left and right
            else float("inf")
        )
        typography_spans = (
            left
            and right
            and len(row) <= 16
            and max(word.font_size for word in row) >= body_size * 1.2
        )
        if crosses_gutter or between_gap < minimum_gutter or typography_spans:
            flush_segment()
            lines.append(_line_from_words(row))
        else:
            segment.append(row)
    flush_segment()
    return lines


def _extract_lines(
    page: Any,
    *,
    page_width: float,
    page_height: float,
    budget: _NodeBudget,
    excluded_bboxes: Sequence[_BBox] = (),
) -> tuple[list[_Line], list[_Line], list[_Word]]:
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
    all_lines = _group_lines(words, page_width=page_width)
    budget.consume(len(all_lines))
    if not excluded_bboxes:
        content_words = words
    else:
        content_words = [
            word
            for word in words
            if not any(
                bbox.x0 <= (word.bbox.x0 + word.bbox.x1) / 2 <= bbox.x1
                and bbox.top <= (word.bbox.top + word.bbox.bottom) / 2 <= bbox.bottom
                for bbox in excluded_bboxes
            )
        ]
    content_lines = _group_lines(content_words, page_width=page_width)
    content_lines = [
        line
        for line in content_lines
        if not _is_margin_noise(line, page_height=page_height)
    ]
    if excluded_bboxes:
        budget.consume(len(content_lines))
    return all_lines, content_lines, words


_VISIBLE_URL = re.compile(r"(?:https?://|www\.)[^\s<>()]+", re.IGNORECASE)


def _link_display_text(words: Sequence[_Word], bbox: _BBox | None) -> str:
    if bbox is None:
        return ""
    selected = nsmallest(
        _MAX_LINK_LABEL_WORDS,
        (
            word
            for word in words
            if word.text
            and bbox.x0 - 2 <= (word.bbox.x0 + word.bbox.x1) / 2 <= bbox.x1 + 2
            and bbox.top - 2
            <= (word.bbox.top + word.bbox.bottom) / 2
            <= bbox.bottom + 2
        ),
        key=lambda item: (item.bbox.top, item.bbox.x0),
    )
    parts: list[str] = []
    remaining = _MAX_LINK_LABEL_CHARS
    for word in selected:
        separator = 1 if parts else 0
        if remaining <= separator:
            break
        part = word.text[: remaining - separator]
        if not part:
            break
        parts.append(part)
        remaining -= separator + len(part)
    return " ".join(parts).strip()


def _normalize_url(value: str) -> str | None:
    compact = re.sub(r"\s+", "", value).rstrip(".,;:!?)]}")
    if compact.lower().startswith("www."):
        compact = f"https://{compact}"
    try:
        parts = urlsplit(compact)
    except ValueError:
        return None
    if parts.scheme.lower() not in {"http", "https"} or not parts.netloc:
        return None
    return urlunsplit(
        (
            parts.scheme.lower(),
            parts.netloc.lower(),
            parts.path.rstrip("/"),
            parts.query,
            parts.fragment,
        )
    )


def _link_status(link: PDFLink, display_text: str) -> str:
    if link.target_truncated or not display_text or not link.target:
        return "NEEDS_REVIEW"
    visible_match = _VISIBLE_URL.search(display_text)
    if visible_match is not None:
        target_url = _normalize_url(link.target)
        visible_parts = display_text[visible_match.start() :].split()[
            :_MAX_VISIBLE_URL_PARTS
        ]
        candidate = ""
        for part in visible_parts:
            candidate += part
            visible_url = _normalize_url(candidate)
            if target_url is not None and visible_url == target_url:
                return "MATCH"
        return "MISMATCH"
    if (
        link.action_type == "GoToR"
        and re.sub(r"\s+", "", display_text).casefold()
        == re.sub(r"\s+", "", link.target).casefold()
    ):
        return "MATCH"
    return "NEEDS_REVIEW"


def _document_link(
    link: PDFLink,
    *,
    link_id: str,
    words: Sequence[_Word],
    page_width: float,
    page_height: float,
) -> dict[str, Any]:
    bbox = (
        _safe_bbox(
            link.bbox,
            page_width=page_width,
            page_height=page_height,
        )
        if link.bbox is not None
        else None
    )
    display_text = _link_display_text(words, bbox)
    return {
        "id": link_id,
        "page_number": link.page_number,
        "bbox": (
            {
                "x0": bbox.x0,
                "top": bbox.top,
                "x1": bbox.x1,
                "bottom": bbox.bottom,
            }
            if bbox is not None
            else None
        ),
        "display_text": display_text,
        "target": link.target,
        "action_type": link.action_type,
        "status": _link_status(link, display_text),
    }


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


def _object_overlaps_table(
    value: Mapping[str, Any],
    table_bboxes: Sequence[_BBox],
) -> bool:
    try:
        x0 = float(value["x0"])
        x1 = float(value["x1"])
        top = float(value["top"])
        bottom = float(value["bottom"])
    except (KeyError, TypeError, ValueError, OverflowError):
        return True
    if not all(math.isfinite(coordinate) for coordinate in (x0, x1, top, bottom)):
        return True
    left, right = sorted((x0, x1))
    upper, lower = sorted((top, bottom))
    return any(
        left <= table_bbox.x1
        and right >= table_bbox.x0
        and upper <= table_bbox.bottom
        and lower >= table_bbox.top
        for table_bbox in table_bboxes
    )


def _count_ruled_table_intersections(
    edges: Sequence[Mapping[str, Any]],
) -> int:
    vertical = [edge for edge in edges if edge.get("orientation") == "v"]
    horizontal = [edge for edge in edges if edge.get("orientation") == "h"]
    count = 0
    try:
        for vertical_edge in vertical:
            for horizontal_edge in horizontal:
                if (
                    vertical_edge["top"] <= horizontal_edge["top"] + 3
                    and vertical_edge["bottom"] >= horizontal_edge["top"] - 3
                    and vertical_edge["x0"] >= horizontal_edge["x0"] - 3
                    and vertical_edge["x0"] <= horizontal_edge["x1"] + 3
                ):
                    count += 1
                    if count > _MAX_TABLE_INTERSECTIONS:
                        raise PDFValidationError("PDF_STRUCTURE_LIMIT")
    except PDFValidationError:
        raise
    except (KeyError, TypeError, ValueError, OverflowError) as exc:
        raise PDFValidationError("PDF_IR_MALFORMED") from exc
    return count


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
        [(float(word["x0"]) + float(word["x1"])) / 2 for word in words],
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
        for word, next_word in zip(in_table, in_table[1:], strict=False)
        if abs(next_word["top"] - word["top"]) <= 3
    )


def _text_table_rows_are_consistent(rows: Sequence[Sequence[Any]]) -> bool:
    occupancies = [
        sum(bool(cell and str(cell).strip()) for cell in row)
        for row in rows
        if any(cell and str(cell).strip() for cell in row)
    ]
    if len(occupancies) < 2:
        return False
    dominant_occupancy, dominant_count = Counter(occupancies).most_common(1)[0]
    return dominant_occupancy >= 2 and dominant_count * 2 > len(occupancies)


def _extract_tables(
    page: Any,
    *,
    page_number: int,
    page_width: float,
    page_height: float,
    budget: _NodeBudget,
) -> tuple[
    list[tuple[dict[str, Any], list[tuple[float, float]], int, list[_BBox]]],
    bool,
]:
    objects = page.objects
    source_count = sum(
        len(objects.get(object_type, ())) for object_type in _TABLE_SOURCE_OBJECT_TYPES
    )
    estimated_edges = (
        len(objects.get("line", ()))
        + (4 * len(objects.get("rect", ())))
        + sum(
            max(0, len(curve.get("pts", ())) - 1) for curve in objects.get("curve", ())
        )
    )
    vector_needs_review = (
        source_count > _MAX_TABLE_SOURCE_OBJECTS
        or estimated_edges > _MAX_TABLE_EDGES
        or estimated_edges * estimated_edges > _MAX_TABLE_INTERSECTIONS
    )
    if (
        source_count > _MAX_VECTOR_SOURCE_OBJECTS
        or estimated_edges > _MAX_VECTOR_EDGES
        or budget.used + _TABLE_WORK_RESERVE > budget.limit
    ):
        raise PDFValidationError("PDF_STRUCTURE_LIMIT")

    edges = page.edges
    if len(edges) > _MAX_VECTOR_EDGES:
        raise PDFValidationError("PDF_STRUCTURE_LIMIT")
    intersection_count = _count_ruled_table_intersections(edges)
    has_ruled_table_candidate = intersection_count >= _MIN_RULED_TABLE_INTERSECTIONS
    finder_needs_review = (
        intersection_count * intersection_count > _MAX_TABLE_FINDER_WORK
    )

    ruled_tables = (
        []
        if finder_needs_review or not has_ruled_table_candidate
        else page.find_tables()
    )
    ruled_bboxes = [
        _table_bbox(
            table.bbox,
            page_width=page_width,
            page_height=page_height,
        )
        for table in ruled_tables
    ]
    if ruled_tables:
        table_source_count = sum(
            _object_overlaps_table(source, ruled_bboxes)
            for object_type in _TABLE_SOURCE_OBJECT_TYPES
            for source in objects.get(object_type, ())
        )
        table_edge_count = sum(
            _object_overlaps_table(edge, ruled_bboxes) for edge in edges
        )
        if (
            table_source_count > _MAX_TABLE_SOURCE_OBJECTS
            or table_edge_count > _MAX_TABLE_EDGES
            or budget.used + table_edge_count + intersection_count + _TABLE_WORK_RESERVE
            > budget.limit
        ):
            raise PDFValidationError("PDF_STRUCTURE_LIMIT")
        budget.consume(table_edge_count + intersection_count)

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
            bbox.x0 <= center_x <= bbox.x1 and bbox.top <= center_y <= bbox.bottom
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
    estimated_text_intersections = (text_edges // 2) * (text_edges - (text_edges // 2))
    text_needs_review = finder_needs_review or (
        text_edges > _MAX_TABLE_EDGES
        or text_edges * text_edges > _MAX_TABLE_INTERSECTIONS
        or estimated_text_intersections * estimated_text_intersections
        > _MAX_TEXT_TABLE_FINDER_WORK
    )
    if budget.used + _TABLE_WORK_RESERVE > budget.limit:
        raise PDFValidationError("PDF_STRUCTURE_LIMIT")
    text_tables = (
        []
        if text_needs_review
        else text_page.find_tables(
            {
                "vertical_strategy": "text",
                "horizontal_strategy": "text",
                "min_words_vertical": _TEXT_TABLE_MIN_WORDS_VERTICAL,
                "min_words_horizontal": _TEXT_TABLE_MIN_WORDS_HORIZONTAL,
            }
        )
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
    cell_count = 0
    for _table_page, table, table_bbox, is_text in candidates:
        budget.consume(2)
        table_bbox = _table_bbox(
            table.bbox,
            page_width=page_width,
            page_height=page_height,
        )
        try:
            table_rows = table.rows
            cell_count += sum(len(row.cells) for row in table_rows)
            if cell_count > _MAX_TABLE_CELLS:
                raise PDFValidationError("PDF_STRUCTURE_LIMIT")
            extracted_rows = table.extract()
            if is_text and not _text_table_rows_are_consistent(extracted_rows):
                continue
        except PDFValidationError:
            raise
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
        if not rows:
            continue
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
    return (
        parsed_tables,
        text_needs_review or (vector_needs_review and not parsed_tables),
    )


def _is_heading(
    line: _Line,
    *,
    median_body_size: float,
    typography_ranks: Mapping[float, int],
    numbering_has_nested_level: bool = False,
) -> tuple[bool, int]:
    if _BIBLIOGRAPHY_HEADING.fullmatch(_normalize_heading(line.text)):
        return True, 1
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
    *,
    pdf_links: Sequence[PDFLink] = (),
    links: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    """Extract bounded page geometry and structural containers."""
    all_sections = sections if sections is not None else []
    all_paragraphs = paragraphs if paragraphs is not None else []
    all_tables = tables if tables is not None else []
    all_links = links if links is not None else []
    parsed_pages: list[dict[str, Any]] = []
    section_stack: list[tuple[int, str]] = []
    previous_page_table: (
        tuple[dict[str, Any], list[tuple[float, float]], int, float] | None
    ) = None
    for page_number, page in enumerate(pages, start=1):
        section_start = len(all_sections)
        paragraph_start = len(all_paragraphs)
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

        page_table_regions, table_needs_review = _extract_tables(
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
                can_merge = bool(
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
        all_lines, content_lines, words = _extract_lines(
            page,
            page_width=page_width,
            page_height=page_height,
            budget=budget,
            excluded_bboxes=table_bboxes,
        )
        page_link_ids: list[str] = []
        page_links = [
            source_link
            for source_link in pdf_links
            if source_link.page_number == page_number
        ]
        link_words: Sequence[_Word] = (
            words if len(page_links) * len(words) <= _MAX_LINK_LABEL_WORK else ()
        )
        for source_link in page_links:
            budget.consume()
            link_id = f"link-{len(all_links) + 1}"
            all_links.append(
                _document_link(
                    source_link,
                    link_id=link_id,
                    words=link_words,
                    page_width=page_width,
                    page_height=page_height,
                )
            )
            page_link_ids.append(link_id)
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
        paragraph_lines: list[tuple[_Line, str | None, int]] = []
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
                previous, previous_section, _previous_index = paragraph_lines[-1]
                vertical_gap = line.bbox.top - previous.bbox.bottom
                if (
                    section_id != previous_section
                    or abs(line.bbox.x0 - previous.bbox.x0) > 36
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
            paragraph_lines.append((line, section_id, line_index))
        if paragraph_lines:
            budget.consume()
            _append_paragraph(
                paragraph_lines,
                page_number,
                all_paragraphs,
                page_paragraph_ids,
            )
        if table_needs_review:
            for index in range(section_start, len(all_sections)):
                all_sections[index]["needs_review"] = True
            for index in range(paragraph_start, len(all_paragraphs)):
                all_paragraphs[index]["needs_review"] = True
        parsed_pages.append(
            {
                "number": page_number,
                "width": round(page_width, 3),
                "height": round(page_height, 3),
                "text": "\n".join(page_lines),
                "headings": page_heading_ids,
                "paragraphs": page_paragraph_ids,
                "tables": page_table_ids,
                "links": page_link_ids,
            }
        )
    _drop_repeated_margin_elements(parsed_pages, all_sections, all_paragraphs)
    return parsed_pages


def _drop_repeated_margin_elements(
    pages: list[dict[str, Any]],
    sections: list[dict[str, Any]],
    paragraphs: list[dict[str, Any]],
) -> None:
    page_heights = {
        int(page["number"]): float(page["height"])
        for page in pages
        if page.get("number") is not None and page.get("height") is not None
    }

    def at_margin(element: Mapping[str, Any]) -> bool:
        page_number = int(element.get("page_number", 0) or 0)
        bbox = element.get("bbox", {})
        return (
            float(bbox.get("top", 0)) <= 72
            or float(bbox.get("bottom", 0)) >= page_heights.get(page_number, 792.0) - 72
        )

    occurrences: dict[str, list[dict[str, Any]]] = {}
    for element in (*sections, *paragraphs):
        text = " ".join(str(element.get("text", "")).split())
        if text and len(text) <= 160 and at_margin(element):
            occurrences.setdefault(_normalize_heading(text), []).append(element)

    repeated = {
        text
        for text, items in occurrences.items()
        if text and len({int(item.get("page_number", 0)) for item in items}) >= 2
    }
    dropped_paragraph_ids = {
        str(paragraph["id"])
        for paragraph in paragraphs
        if _normalize_heading(str(paragraph.get("text", ""))) in repeated
        and at_margin(paragraph)
    }
    dropped_section_ids: set[str] = set()
    kept_bibliography_heading: set[str] = set()
    for section in sections:
        normalized = _normalize_heading(str(section.get("text", "")))
        if normalized not in repeated or not at_margin(section):
            continue
        if _BIBLIOGRAPHY_HEADING.fullmatch(normalized):
            if normalized in kept_bibliography_heading:
                dropped_section_ids.add(str(section["id"]))
            else:
                kept_bibliography_heading.add(normalized)
        else:
            dropped_section_ids.add(str(section["id"]))

    if dropped_paragraph_ids:
        paragraphs[:] = [
            paragraph
            for paragraph in paragraphs
            if paragraph["id"] not in dropped_paragraph_ids
        ]
    if dropped_section_ids:
        original_sections = list(sections)
        retained_bibliography = {
            _normalize_heading(str(section.get("text", ""))): str(section["id"])
            for section in original_sections
            if str(section["id"]) not in dropped_section_ids
            and _BIBLIOGRAPHY_HEADING.fullmatch(
                _normalize_heading(str(section.get("text", "")))
            )
        }
        replacement_ids: dict[str, str | None] = {}
        section_stack: list[dict[str, Any]] = []
        for section in original_sections:
            section_id = str(section["id"])
            normalized = _normalize_heading(str(section.get("text", "")))
            if section_id in dropped_section_ids:
                replacement_ids[section_id] = retained_bibliography.get(
                    normalized,
                    str(section_stack[-1]["id"]) if section_stack else None,
                )
                continue
            level = int(section.get("level", 1) or 1)
            while section_stack and int(section_stack[-1]["level"]) >= level:
                section_stack.pop()
            section["parent_id"] = (
                str(section_stack[-1]["id"]) if section_stack else None
            )
            section_stack.append(section)
        sections[:] = [
            section
            for section in original_sections
            if str(section["id"]) not in dropped_section_ids
        ]
        for paragraph in paragraphs:
            section_id = paragraph.get("section_id")
            if isinstance(section_id, str) and section_id in replacement_ids:
                paragraph["section_id"] = replacement_ids[section_id]

    for page in pages:
        page["headings"] = [
            section_id
            for section_id in page["headings"]
            if section_id not in dropped_section_ids
        ]
        page["paragraphs"] = [
            paragraph_id
            for paragraph_id in page["paragraphs"]
            if paragraph_id not in dropped_paragraph_ids
        ]


def _append_paragraph(
    lines: Sequence[tuple[_Line, str | None, int]],
    page_number: int,
    paragraphs: list[dict[str, Any]],
    page_paragraph_ids: list[str],
) -> None:
    first_line = lines[0][0]
    bbox = first_line.bbox
    text_parts: list[str] = []
    superscript_markers: list[dict[str, Any]] = []
    offset = 0
    for line, _section_id, _line_index in lines:
        if text_parts:
            offset += 1
        line_start = offset
        text_parts.append(line.text)
        offset += len(line.text)
        superscript_markers.extend(
            {
                "raw": line.text[start:end],
                "number": number,
                "start": line_start + start,
                "end": line_start + end,
            }
            for start, end, number in line.superscript_markers
        )
        bbox = _union_bbox(bbox, line.bbox)
    paragraph_id = f"paragraph-{len(paragraphs) + 1}"
    paragraph = {
        "id": paragraph_id,
        "text": " ".join(text_parts),
        "section_id": lines[0][1],
        "page_number": page_number,
        "line_start": lines[0][2],
        "line_end": lines[-1][2],
        "bbox": {
            "x0": bbox.x0,
            "top": bbox.top,
            "x1": bbox.x1,
            "bottom": bbox.bottom,
        },
    }
    if superscript_markers:
        paragraph["superscript_markers"] = superscript_markers
    paragraphs.append(paragraph)
    page_paragraph_ids.append(paragraph_id)


def _assemble_ir(
    validation: PDFValidationResult,
    pages: list[dict[str, Any]],
    sections: list[dict[str, Any]],
    paragraphs: list[dict[str, Any]],
    tables: list[dict[str, Any]],
    links: list[dict[str, Any]],
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
        "links": links,
    }


def parse_document_ir(
    data: bytes,
    *,
    max_size_bytes: int = 100_000_000,
    max_decoded_bytes: int = 50_000_000,
    max_page_count: int = 100,
    max_nodes: int = 100_000,
) -> ParsedDocumentIR:
    """Validate untrusted PDF bytes and extract bounded Document IR."""
    validation = validate_pdf(
        data,
        max_size_bytes=max_size_bytes,
        max_decoded_bytes=max_decoded_bytes,
        max_page_count=max_page_count,
    )
    budget = _NodeBudget(limit=max_nodes)
    budget.consume(validation.page_count)
    sections: list[dict[str, Any]] = []
    paragraphs: list[dict[str, Any]] = []
    tables: list[dict[str, Any]] = []
    links: list[dict[str, Any]] = []
    try:
        with (
            _suppress_untrusted_pdf_logs(),
            pdfplumber.open(BytesIO(data)) as pdf,
            _bounded_layout_hook(budget),
        ):
            pages = _parse_pages(
                pdf.pages,
                budget,
                sections,
                paragraphs,
                tables,
                pdf_links=validation.links,
                links=links,
            )
    except PDFValidationError:
        raise
    except Exception as exc:
        for nested in (exc.__cause__, exc.__context__, *exc.args):
            if isinstance(nested, PDFValidationError):
                raise nested from None
        raise DocumentIRExtractionError("Document IR extraction failed") from exc
    content = _assemble_ir(validation, pages, sections, paragraphs, tables, links)
    return ParsedDocumentIR(validation=validation, content=content)
