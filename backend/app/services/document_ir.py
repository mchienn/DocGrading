"""Pure, bounded Document IR parser and structure extraction service."""
from __future__ import annotations

import math
import re
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from io import BytesIO
from statistics import median
from threading import RLock
from typing import Any, Mapping, Sequence

import pdfplumber
from pdfplumber.page import PDFPageAggregatorWithMarkedContent

from app.services.pdf_validation import (
    PDFValidationError,
    PDFValidationResult,
    validate_pdf,
)

SCHEMA_VERSION: int = 1
PARSER_VERSION: str = "pypdf-pdfplumber-v1"


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
        bbox=_union_bbox(words[0].bbox, words[-1].bbox)
        if len(words) == 1
        else _union_words_bbox(words),
        font_size=max(word.font_size for word in words),
        font_name=font_name,
    )


def _union_words_bbox(words: Sequence[_Word]) -> _BBox:
    bbox = words[0].bbox
    for word in words[1:]:
        bbox = _union_bbox(bbox, word.bbox)
    return bbox


def _extract_lines(
    page: Any,
    *,
    page_width: float,
    page_height: float,
    budget: _NodeBudget,
) -> list[_Line]:
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
    words.sort(key=lambda word: (word.bbox.top, word.bbox.x0))
    grouped: list[list[_Word]] = []
    for word in words:
        if not grouped or abs(word.bbox.top - grouped[-1][0].bbox.top) > 3:
            grouped.append([word])
        else:
            grouped[-1].append(word)
    lines = []
    for group in grouped:
        group.sort(key=lambda word: word.bbox.x0)
        lines.append(_line_from_words(group))
    budget.consume(len(lines))
    return lines


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
        if (
            not line.text.rstrip().endswith((".", "!", "?"))
            and (
                level >= 2
                or numbering_has_nested_level
                or line.font_size >= median_body_size * 1.25
                or "bold" in line.font_name.lower()
            )
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
) -> list[dict[str, Any]]:
    """Extract bounded page geometry and structural containers."""
    all_sections = sections if sections is not None else []
    all_paragraphs = paragraphs if paragraphs is not None else []
    parsed_pages: list[dict[str, Any]] = []
    section_stack: list[tuple[int, str]] = []
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

        lines = _extract_lines(
            page,
            page_width=page_width,
            page_height=page_height,
            budget=budget,
        )
        typography_ranks = {
            size: rank
            for rank, size in enumerate(
                sorted({line.font_size for line in lines}, reverse=True),
                start=1,
            )
        }
        numbering_has_nested_level = any(
            match and match.group(1).count(".") + 1 >= 2
            for line in lines
            for match in [_NUMBERED_HEADING.match(line.text)]
        )
        body_like_sizes = [
            line.font_size
            for line in lines
            if (
                line.text.rstrip().endswith((".", "!", "?"))
                or len(line.text) >= 40
            )
        ]
        if body_like_sizes:
            median_body_size = median(body_like_sizes)
        else:
            lower_sizes = sorted(line.font_size for line in lines)
            lower_count = max(1, (len(lower_sizes) + 1) // 2)
            median_body_size = median(lower_sizes[:lower_count] or [0.0])
        heading_lines: set[int] = set()
        page_heading_ids: list[str] = []
        page_lines: list[str] = []
        current_section_id: str | None = (
            section_stack[-1][1] if section_stack else None
        )
        line_section_ids: dict[int, str | None] = {}
        for line_index, line in enumerate(lines):
            page_lines.append(line.text)
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
        for line_index, line in enumerate(lines):
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
                "tables": [],
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
        "tables": [],
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
    try:
        with pdfplumber.open(BytesIO(data)) as pdf:
            with _bounded_layout_hook(budget):
                pages = _parse_pages(pdf.pages, budget, sections, paragraphs)
    except PDFValidationError:
        raise
    except Exception as exc:
        for nested in (exc.__cause__, exc.__context__, *exc.args):
            if isinstance(nested, PDFValidationError):
                raise nested
        raise DocumentIRExtractionError("Document IR extraction failed") from exc
    content = _assemble_ir(validation, pages, sections, paragraphs)
    return ParsedDocumentIR(validation=validation, content=content)
