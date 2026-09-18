"""Bounded validation of untrusted PDF bytes."""

from __future__ import annotations

import hashlib
import logging
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from io import BytesIO
from math import isclose, isfinite
from threading import RLock
from typing import Any

from pypdf import PdfReader
from pypdf import filters as pdf_filters
from pypdf.errors import LimitReachedError, PdfReadError, PdfStreamError
from pypdf.generic import (
    ArrayObject,
    ByteStringObject,
    ContentStream,
    DictionaryObject,
    IndirectObject,
    NameObject,
    NullObject,
    StreamObject,
    TextStringObject,
)

_PYPDF_LOG_NAMESPACES = ("pypdf", "pdfminer", "pdfplumber")
_PDF_LOG_LOCK = RLock()
_PDF_LOGGING_SUPPRESSED: ContextVar[bool] = ContextVar(
    "pdf_logging_suppressed",
    default=False,
)


class _UntrustedPDFLogFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        if not _PDF_LOGGING_SUPPRESSED.get():
            return True
        return not any(
            record.name == namespace or record.name.startswith(f"{namespace}.")
            for namespace in _PYPDF_LOG_NAMESPACES
        )


@contextmanager
def _suppress_untrusted_pdf_logs() -> Iterator[None]:
    """Hide raw third-party parser records during untrusted PDF handling."""
    targets: list[logging.Filterer] = []
    seen: set[int] = set()

    def add_target(target: logging.Filterer) -> None:
        marker = id(target)
        if marker not in seen:
            seen.add(marker)
            targets.append(target)

    token = _PDF_LOGGING_SUPPRESSED.set(True)
    log_filter = _UntrustedPDFLogFilter()
    try:
        with _PDF_LOG_LOCK:
            root_logger = logging.getLogger()
            add_target(root_logger)
            existing_loggers = logging.Logger.manager.loggerDict.copy()
            for namespace in _PYPDF_LOG_NAMESPACES:
                for name, logger in existing_loggers.items():
                    if isinstance(logger, logging.Logger) and (
                        name == namespace or name.startswith(f"{namespace}.")
                    ):
                        add_target(logger)
            for target in tuple(targets):
                if isinstance(target, logging.Logger):
                    for handler in target.handlers:
                        add_target(handler)
            for handler in root_logger.handlers:
                add_target(handler)
            if logging.lastResort is not None:
                add_target(logging.lastResort)
            for target in targets:
                target.addFilter(log_filter)
        try:
            yield
        finally:
            with _PDF_LOG_LOCK:
                for target in targets:
                    target.removeFilter(log_filter)
    finally:
        _PDF_LOGGING_SUPPRESSED.reset(token)


@dataclass(frozen=True, slots=True)
class PDFDiagnostic:
    code: str
    category: str
    disposition: str
    scope: str = "DOCUMENT"
    page_number: int | None = None
    bbox: dict[str, float] | None = None
    metrics: dict[str, int | float] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "category": self.category,
            "disposition": self.disposition,
            "scope": self.scope,
            "page_number": self.page_number,
            "bbox": self.bbox,
            "metrics": self.metrics,
            "message_key": self.code.lower(),
            "action_key": _DIAGNOSTIC_ACTIONS.get(self.code),
        }


_DIAGNOSTIC_ACTIONS = {
    "NOT_A_PDF": "pdf.choose_pdf",
    "PDF_TOO_LARGE": "pdf.reduce_size",
    "PDF_ENCRYPTED": "pdf.remove_password",
    "PDF_PAGE_LIMIT": "pdf.reduce_pages",
    "PDF_DECODED_TOO_LARGE": "pdf.export_clean_copy",
    "PDF_STRUCTURE_UNRECOVERABLE": "pdf.export_clean_copy",
    "PDF_STRUCTURE_RECOVERED": "pdf.export_clean_copy",
    "PDF_ACTIVE_JAVASCRIPT": "pdf.remove_active_content",
    "PDF_ACTIVE_LAUNCH": "pdf.remove_active_content",
    "PDF_ACTIVE_FORM": "pdf.flatten_form",
    "PDF_ACTIVE_MEDIA": "pdf.remove_active_content",
    "PDF_ACTIVE_REMOTE_ACTION": "pdf.remove_active_content",
    "PDF_ACTIVE_AUTOMATIC_ACTION": "pdf.remove_active_content",
    "PDF_EMBEDDED_FILE": "pdf.remove_attachments",
    "PDF_SCAN_DETECTED": "pdf.run_ocr",
    "PDF_SCAN_ANALYSIS_UNSUPPORTED": "pdf.export_searchable_copy",
    "PDF_TEXT_LAYER_MISSING": "pdf.run_ocr",
}


@dataclass(frozen=True, slots=True)
class PDFLink:
    page_number: int
    bbox: dict[str, float] | None
    action_type: str
    target: str
    target_truncated: bool = False


@dataclass(frozen=True)
class PDFValidationResult:
    sha256: str
    size_bytes: int
    page_count: int
    has_text: bool
    diagnostics: tuple[PDFDiagnostic, ...] = ()
    links: tuple[PDFLink, ...] = ()

    @property
    def report(self) -> dict[str, Any]:
        return {
            "schema_version": 1,
            "outcome": ("ACCEPTED_WITH_WARNINGS" if self.diagnostics else "ACCEPTED"),
            "diagnostics": [item.to_dict() for item in self.diagnostics],
        }


class PDFValidationError(ValueError):
    def __init__(
        self,
        code: str,
        detail: str | None = None,
        *,
        diagnostic: PDFDiagnostic | None = None,
    ) -> None:
        self.code = code
        self.detail = detail or code
        self.diagnostic = diagnostic or PDFDiagnostic(
            code=code,
            category="COMPATIBILITY",
            disposition="BLOCK",
        )
        super().__init__(self.detail)

    @property
    def report(self) -> dict[str, Any]:
        return {
            "schema_version": 1,
            "outcome": "REJECTED",
            "diagnostics": [self.diagnostic.to_dict()],
        }


class _PDFScanLimit(Exception):
    pass


class _PDFGeometryLimit(Exception):
    pass


class _BoundedOperationList(list[tuple[Any, bytes]]):
    def __init__(self, limit: int) -> None:
        super().__init__()
        self.limit = limit

    def append(self, item: tuple[Any, bytes]) -> None:
        if len(self) >= self.limit:
            raise _PDFGeometryLimit
        super().append(item)


_PYPDF_DECODE_LOCK = RLock()
_PYPDF_DECODE_LIMIT_NAMES = (
    "JBIG2_MAX_OUTPUT_LENGTH",
    "LZW_MAX_OUTPUT_LENGTH",
    "RUN_LENGTH_MAX_OUTPUT_LENGTH",
    "ZLIB_MAX_OUTPUT_LENGTH",
    "FLATE_MAX_BUFFER_SIZE",
    "MAX_ARRAY_BASED_STREAM_OUTPUT_LENGTH",
)
_PYPDF_BOUNDED_FILTERS = {
    "/FlateDecode",
    "/Fl",
    "/LZWDecode",
    "/LZW",
    "/RunLengthDecode",
    "/RL",
    "/JBIG2Decode",
}
_IMAGE_COVERAGE_THRESHOLD = 0.80
_MIN_USEFUL_TEXT_CHARACTERS = 30
_MAX_FORM_DEPTH = 32
_MAX_GEOMETRY_OPERATIONS = 10_000
_MAX_CLIP_VERTICES = 256
_MAX_PAGE_TREE_NODES = 10_000
_MAX_PAGE_TREE_DEPTH = 100
_MAX_ACTIVE_CONTENT_NODES = 50_000
_MAX_STRUCT_TREE_NODES = 250_000
_GEOMETRY_OPERATOR_ARITY = {
    b"q": 0,
    b"Q": 0,
    b"cm": 6,
    b"re": 4,
    b"m": 2,
    b"l": 2,
    b"c": 6,
    b"v": 4,
    b"y": 4,
    b"h": 0,
    b"W": 0,
    b"W*": 0,
    b"S": 0,
    b"s": 0,
    b"f": 0,
    b"F": 0,
    b"f*": 0,
    b"B": 0,
    b"B*": 0,
    b"b": 0,
    b"b*": 0,
    b"n": 0,
    b"Do": 1,
}

type Matrix = tuple[float, float, float, float, float, float]
type Point = tuple[float, float]
type Polygon = list[Point]

_IDENTITY_MATRIX: Matrix = (1.0, 0.0, 0.0, 1.0, 0.0, 0.0)


def _resolve_page_tree_object(value: Any, work: list[int]) -> Any:
    while isinstance(value, IndirectObject):
        work[0] += 1
        if work[0] > _MAX_PAGE_TREE_NODES:
            raise PDFValidationError("PDF_MALFORMED")
        value = value.get_object()
    return value


def _preflight_page_tree(reader: PdfReader, max_page_count: int) -> int:
    """Count page leaves without invoking pypdf's flattening machinery."""
    work = [0]
    pages = _resolve_page_tree_object(reader.root_object.get("/Pages"), work)
    if not isinstance(pages, dict):
        raise PDFValidationError("PDF_MALFORMED")
    count = _resolve_page_tree_object(pages.get("/Count"), work)
    if (
        isinstance(count, int)
        and not isinstance(count, bool)
        and count > max_page_count
    ):
        raise PDFValidationError("PDF_PAGE_LIMIT")

    pending: list[tuple[Any, int]] = [(pages, 0)]
    seen: set[int] = set()
    page_count = 0
    node_count = 0
    while pending:
        value, depth = pending.pop()
        if depth > _MAX_PAGE_TREE_DEPTH:
            raise PDFValidationError("PDF_MALFORMED")
        resolved = _resolve_page_tree_object(value, work)
        marker = id(resolved)
        if marker in seen:
            raise PDFValidationError("PDF_MALFORMED")
        seen.add(marker)
        node_count += 1
        if node_count + work[0] > _MAX_PAGE_TREE_NODES:
            raise PDFValidationError("PDF_MALFORMED")
        if not isinstance(resolved, dict):
            raise PDFValidationError("PDF_MALFORMED")
        object_type = str(_resolve_page_tree_object(resolved.get("/Type"), work))
        if object_type == "/Page":
            page_count += 1
            if page_count > max_page_count:
                raise PDFValidationError("PDF_PAGE_LIMIT")
            continue
        if object_type != "/Pages":
            raise PDFValidationError("PDF_MALFORMED")
        kids = _resolve_page_tree_object(resolved.get("/Kids"), work)
        if not isinstance(kids, (ArrayObject, list, tuple)):
            raise PDFValidationError("PDF_MALFORMED")
        if len(kids) > (_MAX_PAGE_TREE_NODES - node_count - len(pending) - work[0]):
            raise PDFValidationError("PDF_MALFORMED")
        pending.extend((child, depth + 1) for child in kids)
    return page_count


@dataclass
class _RasterGeometryContext:
    decoded_limit: int
    remaining_decoded_bytes: int = field(init=False)
    form_contents: dict[int, ContentStream] = field(default_factory=dict)
    form_decoded_sizes: dict[int, int] = field(default_factory=dict)
    text_extraction_work_bytes: int = 0
    operation_count: int = 0

    def __post_init__(self) -> None:
        self.remaining_decoded_bytes = self.decoded_limit


def _resolve_pdf_object(value: Any) -> Any:
    while isinstance(value, IndirectObject):
        value = value.get_object()
    return value


def _page_content_streams(page: Any) -> tuple[list[StreamObject], bool]:
    try:
        contents = _resolve_pdf_object(page.raw_get("/Contents"))
    except KeyError:
        return [], False
    if isinstance(contents, NullObject):
        return [], False
    if isinstance(contents, ArrayObject):
        streams = [
            resolved
            for item in contents
            if isinstance(
                resolved := _resolve_pdf_object(item),
                StreamObject,
            )
        ]
        return streams, True
    if isinstance(contents, StreamObject):
        return [contents], False
    return [], False


def _ensure_unbounded_filter_stages_fit(
    stream: StreamObject, max_output_length: int
) -> None:
    filters = _resolve_pdf_object(stream.get("/Filter", ()))
    if not isinstance(filters, ArrayObject):
        filters = (filters,)
    stage_length = len(stream._data)
    for filter_value in filters:
        filter_name = str(_resolve_pdf_object(filter_value))
        if filter_name in _PYPDF_BOUNDED_FILTERS:
            stage_length = max_output_length
        elif filter_name in {"/ASCIIHexDecode", "/AHx"}:
            if stage_length > max_output_length:
                raise PDFValidationError("PDF_DECODED_TOO_LARGE")
            stage_length = (stage_length + 1) // 2
        elif filter_name in {"/ASCII85Decode", "/A85"}:
            stage_length *= 4
        elif filter_name in {"/CCITTFaxDecode", "/CCF"}:
            stage_length += 256
        if stage_length > max_output_length:
            raise PDFValidationError("PDF_DECODED_TOO_LARGE")


def _decode_page_content_size(page: Any, max_output_length: int) -> int:
    streams, is_array = _page_content_streams(page)
    decoded_size = 0
    for stream in streams:
        remaining = max_output_length - decoded_size
        _ensure_unbounded_filter_stages_fit(stream, remaining)
        with _bounded_pypdf_decode(remaining):
            try:
                decoded_data = stream.get_data()
            except LimitReachedError as exc:
                raise PDFValidationError("PDF_DECODED_TOO_LARGE") from exc
        decoded_size += len(decoded_data)
        if is_array and (not decoded_data or not decoded_data.endswith(b"\n")):
            decoded_size += 1
        if decoded_size > max_output_length:
            raise PDFValidationError("PDF_DECODED_TOO_LARGE")
    return decoded_size


def _multiply_matrix(m: Matrix, n: Matrix) -> Matrix:
    result = (
        m[0] * n[0] + m[1] * n[2],
        m[0] * n[1] + m[1] * n[3],
        m[2] * n[0] + m[3] * n[2],
        m[2] * n[1] + m[3] * n[3],
        m[4] * n[0] + m[5] * n[2] + n[4],
        m[4] * n[1] + m[5] * n[3] + n[5],
    )
    if not all(isfinite(coordinate) for coordinate in result):
        raise _PDFGeometryLimit
    return result


def _transform_polygon(polygon: Polygon, matrix: Matrix) -> Polygon:
    transformed = [
        (
            x * matrix[0] + y * matrix[2] + matrix[4],
            x * matrix[1] + y * matrix[3] + matrix[5],
        )
        for x, y in polygon
    ]
    if not all(isfinite(coordinate) for point in transformed for coordinate in point):
        raise _PDFGeometryLimit
    return transformed


def _signed_polygon_area(polygon: Polygon) -> float:
    area = 0.0
    for (x1, y1), (x2, y2) in zip(
        polygon,
        polygon[1:] + polygon[:1],
        strict=True,
    ):
        term = x1 * y2 - x2 * y1
        if not isfinite(term):
            raise _PDFGeometryLimit
        area += term
        if not isfinite(area):
            raise _PDFGeometryLimit
    area *= 0.5
    if not isfinite(area):
        raise _PDFGeometryLimit
    return area


def _polygon_area(polygon: Polygon) -> float:
    area = abs(_signed_polygon_area(polygon))
    if not isfinite(area):
        raise _PDFGeometryLimit
    return area


def _clip_polygon(subject: Polygon, clip: Polygon) -> Polygon:
    if len(subject) > _MAX_CLIP_VERTICES or len(clip) > _MAX_CLIP_VERTICES:
        raise _PDFGeometryLimit
    if len(subject) < 3 or len(clip) < 3:
        return []
    orientation = 1.0 if _signed_polygon_area(clip) >= 0 else -1.0
    output = subject

    def inside(point: Point, start: Point, end: Point) -> bool:
        dx = end[0] - start[0]
        dy = end[1] - start[1]
        point_dx = point[0] - start[0]
        point_dy = point[1] - start[1]
        if not all(isfinite(value) for value in (dx, dy, point_dx, point_dy)):
            raise _PDFGeometryLimit
        cross = dx * point_dy - dy * point_dx
        if not isfinite(cross):
            raise _PDFGeometryLimit
        return orientation * cross >= -1e-9

    def intersection(
        segment_start: Point,
        segment_end: Point,
        clip_start: Point,
        clip_end: Point,
    ) -> Point:
        segment_dx = segment_end[0] - segment_start[0]
        segment_dy = segment_end[1] - segment_start[1]
        clip_dx = clip_end[0] - clip_start[0]
        clip_dy = clip_end[1] - clip_start[1]
        if not all(
            isfinite(value) for value in (segment_dx, segment_dy, clip_dx, clip_dy)
        ):
            raise _PDFGeometryLimit
        denominator = segment_dx * clip_dy - segment_dy * clip_dx
        if not isfinite(denominator):
            raise _PDFGeometryLimit
        if abs(denominator) < 1e-12:
            if not all(isfinite(coordinate) for coordinate in segment_end):
                raise _PDFGeometryLimit
            return segment_end
        numerator = (clip_start[0] - segment_start[0]) * clip_dy - (
            clip_start[1] - segment_start[1]
        ) * clip_dx
        if not isfinite(numerator):
            raise _PDFGeometryLimit
        distance = numerator / denominator
        if not isfinite(distance):
            raise _PDFGeometryLimit
        intersection_point = (
            segment_start[0] + distance * segment_dx,
            segment_start[1] + distance * segment_dy,
        )
        if not all(isfinite(coordinate) for coordinate in intersection_point):
            raise _PDFGeometryLimit
        return intersection_point

    for clip_start, clip_end in zip(clip, clip[1:] + clip[:1], strict=True):
        input_polygon = output
        output = []
        if not input_polygon:
            break
        segment_start = input_polygon[-1]
        for segment_end in input_polygon:
            end_inside = inside(segment_end, clip_start, clip_end)
            start_inside = inside(segment_start, clip_start, clip_end)
            if end_inside:
                if not start_inside:
                    output.append(
                        intersection(
                            segment_start,
                            segment_end,
                            clip_start,
                            clip_end,
                        )
                    )
                output.append(segment_end)
            elif start_inside:
                output.append(
                    intersection(
                        segment_start,
                        segment_end,
                        clip_start,
                        clip_end,
                    )
                )
            segment_start = segment_end
        if len(output) > _MAX_CLIP_VERTICES:
            raise _PDFGeometryLimit
    return output


def _polygon_cross(first: Point, second: Point, third: Point) -> float:
    return (second[0] - first[0]) * (third[1] - second[1]) - (second[1] - first[1]) * (
        third[0] - second[0]
    )


def _point_on_segment(point: Point, start: Point, end: Point) -> bool:
    return (
        isclose(_polygon_cross(start, end, point), 0.0, abs_tol=1e-9)
        and min(start[0], end[0]) - 1e-9 <= point[0] <= max(start[0], end[0]) + 1e-9
        and min(start[1], end[1]) - 1e-9 <= point[1] <= max(start[1], end[1]) + 1e-9
    )


def _segments_intersect(
    first_start: Point,
    first_end: Point,
    second_start: Point,
    second_end: Point,
) -> bool:
    first_turn = _polygon_cross(first_start, first_end, second_start)
    second_turn = _polygon_cross(first_start, first_end, second_end)
    third_turn = _polygon_cross(second_start, second_end, first_start)
    fourth_turn = _polygon_cross(second_start, second_end, first_end)
    proper_intersection = (
        first_turn > 0 > second_turn or first_turn < 0 < second_turn
    ) and (third_turn > 0 > fourth_turn or third_turn < 0 < fourth_turn)
    return proper_intersection or (
        (
            isclose(first_turn, 0.0, abs_tol=1e-9)
            and _point_on_segment(second_start, first_start, first_end)
        )
        or (
            isclose(second_turn, 0.0, abs_tol=1e-9)
            and _point_on_segment(second_end, first_start, first_end)
        )
        or (
            isclose(third_turn, 0.0, abs_tol=1e-9)
            and _point_on_segment(first_start, second_start, second_end)
        )
        or (
            isclose(fourth_turn, 0.0, abs_tol=1e-9)
            and _point_on_segment(first_end, second_start, second_end)
        )
    )


def _without_repeated_closing_point(polygon: Polygon) -> Polygon:
    if len(polygon) > 1 and all(
        isclose(first, second, abs_tol=1e-9)
        for first, second in zip(polygon[0], polygon[-1], strict=True)
    ):
        return polygon[:-1]
    return polygon


def _is_simple_polygon(polygon: Polygon) -> bool:
    if len(polygon) > _MAX_CLIP_VERTICES:
        return False
    edges = list(zip(polygon, polygon[1:] + polygon[:1], strict=True))
    for first_index, (first_start, first_end) in enumerate(edges):
        for second_index in range(first_index + 1, len(edges)):
            if second_index in {
                first_index,
                (first_index - 1) % len(edges),
                (first_index + 1) % len(edges),
            }:
                continue
            second_start, second_end = edges[second_index]
            if _segments_intersect(
                first_start,
                first_end,
                second_start,
                second_end,
            ):
                return False
    return True


def _is_convex_polygon(polygon: Polygon) -> bool:
    polygon = _without_repeated_closing_point(polygon)
    if len(polygon) < 3 or not all(
        isfinite(coordinate) for point in polygon for coordinate in point
    ):
        return False
    if not _is_simple_polygon(polygon):
        return False
    direction = 0
    for first, second, third in zip(
        polygon,
        polygon[1:] + polygon[:1],
        polygon[2:] + polygon[:2],
        strict=True,
    ):
        cross_product = _polygon_cross(first, second, third)
        if not isfinite(cross_product):
            return False
        if isclose(cross_product, 0.0, abs_tol=1e-12):
            continue
        current_direction = 1 if cross_product > 0 else -1
        if direction and current_direction != direction:
            return False
        direction = current_direction
    return direction != 0


def _rectangle_polygon(values: Any, *, required: bool = False) -> Polygon:
    resolved = _resolve_pdf_object(values)
    if not isinstance(resolved, (list, tuple)) or len(resolved) < 4:
        if required:
            raise _PDFGeometryLimit
        return []
    left, bottom, right, top = map(float, resolved[:4])
    rectangle = [
        (left, bottom),
        (right, bottom),
        (right, top),
        (left, top),
    ]
    if (
        not all(isfinite(coordinate) for point in rectangle for coordinate in point)
        or right <= left
        or top <= bottom
    ):
        raise _PDFGeometryLimit
    return rectangle


def _bounding_box_polygon(points: Polygon) -> Polygon:
    if not points or len(points) > _MAX_CLIP_VERTICES:
        raise _PDFGeometryLimit
    return _rectangle_polygon(
        (
            min(point[0] for point in points),
            min(point[1] for point in points),
            max(point[0] for point in points),
            max(point[1] for point in points),
        ),
        required=True,
    )


def _matrix_from_pdf(value: Any) -> Matrix:
    resolved = _resolve_pdf_object(value)
    if not isinstance(resolved, (list, tuple)) or len(resolved) < 6:
        raise _PDFGeometryLimit
    matrix = tuple(map(float, resolved[:6]))
    if not all(isfinite(coordinate) for coordinate in matrix):
        raise _PDFGeometryLimit
    return matrix


def _image_coverage(
    matrix: Matrix,
    clip_polygon: Polygon,
    page_area: float,
) -> float:
    image_polygon = _transform_polygon(
        [(0.0, 0.0), (1.0, 0.0), (1.0, 1.0), (0.0, 1.0)],
        matrix,
    )
    visible_polygon = _clip_polygon(image_polygon, clip_polygon)
    coverage = _polygon_area(visible_polygon) / page_area
    if not isfinite(coverage):
        raise _PDFGeometryLimit
    return coverage


def _coverage_reaches_threshold(coverage: float) -> bool:
    return coverage > _IMAGE_COVERAGE_THRESHOLD or isclose(
        coverage,
        _IMAGE_COVERAGE_THRESHOLD,
        rel_tol=1e-9,
        abs_tol=1e-12,
    )


def _account_form_stream(
    xobject: StreamObject,
    context: _RasterGeometryContext,
) -> int:
    marker = id(xobject)
    if marker in context.form_decoded_sizes:
        return context.form_decoded_sizes[marker]
    remaining = context.remaining_decoded_bytes
    _ensure_unbounded_filter_stages_fit(xobject, remaining)
    with _bounded_pypdf_decode(remaining):
        try:
            decoded_data = xobject.get_data()
        except LimitReachedError as exc:
            raise PDFValidationError("PDF_DECODED_TOO_LARGE") from exc
    decoded_size = len(decoded_data)
    if decoded_size > remaining:
        raise PDFValidationError("PDF_DECODED_TOO_LARGE")
    context.remaining_decoded_bytes -= decoded_size
    context.form_decoded_sizes[marker] = decoded_size
    return decoded_size


def _load_form_content(
    xobject: StreamObject,
    pdf: Any,
    context: _RasterGeometryContext,
) -> tuple[ContentStream, int]:
    marker = id(xobject)
    if marker in context.form_contents:
        return (
            context.form_contents[marker],
            context.form_decoded_sizes[marker],
        )
    decoded_size = _account_form_stream(xobject, context)
    with _bounded_pypdf_decode(decoded_size):
        content = ContentStream(xobject, pdf, "bytes")
    context.form_contents[marker] = content
    return content, decoded_size


def _preflight_form_streams(page: Any, context: _RasterGeometryContext) -> None:
    pending: list[tuple[Any, int]] = [(page, 0)]
    seen: set[int] = set()
    while pending:
        container, depth = pending.pop()
        if depth > _MAX_FORM_DEPTH:
            raise _PDFGeometryLimit
        resources = _resolve_pdf_object(container.get("/Resources"))
        if not isinstance(resources, dict):
            continue
        xobjects = _resolve_pdf_object(resources.get("/XObject"))
        if not isinstance(xobjects, dict):
            continue
        for raw_xobject in xobjects.values():
            xobject = _resolve_pdf_object(raw_xobject)
            if not isinstance(xobject, StreamObject):
                continue
            subtype = _resolve_pdf_object(xobject.get("/Subtype"))
            if str(subtype) != "/Form":
                continue
            marker = id(xobject)
            if marker in seen:
                continue
            seen.add(marker)
            if len(seen) > _MAX_PAGE_TREE_NODES:
                raise _PDFGeometryLimit
            _account_form_stream(xobject, context)
            pending.append((xobject, depth + 1))


def _bounded_content_operations(
    content: ContentStream,
    remaining_operations: int,
) -> list[tuple[Any, bytes]]:
    if remaining_operations < 0:
        raise _PDFGeometryLimit
    if not content._operations and content._data:
        content._operations = _BoundedOperationList(remaining_operations)
    operations = content.operations
    if len(operations) > remaining_operations:
        raise _PDFGeometryLimit
    return operations


def _walk_raster_coverage(
    content: ContentStream,
    resources: DictionaryObject,
    pdf: Any,
    context: _RasterGeometryContext,
    *,
    initial_matrix: Matrix,
    clip_polygon: Polygon,
    clip_is_conservative: bool,
    page_area: float,
    form_path: set[int],
    depth: int,
) -> float:
    if depth > _MAX_FORM_DEPTH:
        raise _PDFGeometryLimit
    initial_clip = clip_polygon.copy()
    current_matrix = initial_matrix
    current_clip = initial_clip.copy()
    current_clip_is_conservative = clip_is_conservative
    current_path: Polygon | None = []
    clip_pending = False
    current_path_uses_curve = False
    graphics_stack: list[tuple[Matrix, Polygon, bool]] = []
    maximum_coverage = 0.0
    operations = _bounded_content_operations(
        content,
        _MAX_GEOMETRY_OPERATIONS - context.operation_count,
    )
    for operands, operator in operations:
        context.operation_count += 1
        if context.operation_count > _MAX_GEOMETRY_OPERATIONS:
            raise _PDFGeometryLimit
        expected_arity = _GEOMETRY_OPERATOR_ARITY.get(operator)
        if expected_arity is not None and len(operands) != expected_arity:
            raise _PDFGeometryLimit
        if operator == b"q":
            graphics_stack.append(
                (current_matrix, current_clip.copy(), current_clip_is_conservative)
            )
        elif operator == b"Q":
            if graphics_stack:
                current_matrix, current_clip, current_clip_is_conservative = (
                    graphics_stack.pop()
                )
            else:
                current_matrix = initial_matrix
                current_clip = initial_clip.copy()
                current_clip_is_conservative = clip_is_conservative
        elif operator == b"cm":
            matrix = tuple(map(float, operands[:6]))
            current_matrix = _multiply_matrix(
                _matrix_from_pdf(matrix),
                current_matrix,
            )
        elif operator == b"re":
            if current_path:
                current_path = None
            elif current_path is not None:
                x, y, width, height = map(float, operands[:4])
                current_path = _transform_polygon(
                    [
                        (x, y),
                        (x + width, y),
                        (x + width, y + height),
                        (x, y + height),
                    ],
                    current_matrix,
                )
                current_path_uses_curve = False
        elif operator == b"m":
            if current_path:
                current_path = None
            elif current_path is not None:
                current_path.append(
                    _transform_polygon(
                        [(float(operands[0]), float(operands[1]))],
                        current_matrix,
                    )[0]
                )
                current_path_uses_curve = False
        elif operator == b"l":
            if current_path:
                current_path.append(
                    _transform_polygon(
                        [(float(operands[0]), float(operands[1]))],
                        current_matrix,
                    )[0]
                )
            else:
                current_path = None
        elif operator in {b"c", b"v", b"y"}:
            coordinate_count = _GEOMETRY_OPERATOR_ARITY[operator]
            if current_path:
                current_path.extend(
                    _transform_polygon(
                        [
                            (float(operands[index]), float(operands[index + 1]))
                            for index in range(0, coordinate_count, 2)
                        ],
                        current_matrix,
                    )
                )
                current_path_uses_curve = True
            else:
                current_path = None
        elif operator == b"W":
            clip_pending = True
        elif operator == b"W*":
            clip_pending = True
            if current_path_uses_curve:
                current_path = None
        elif operator in {
            b"S",
            b"s",
            b"f",
            b"F",
            b"f*",
            b"B",
            b"B*",
            b"b",
            b"b*",
            b"n",
        }:
            if clip_pending:
                if current_path is None:
                    raise _PDFGeometryLimit
                clip_path = _without_repeated_closing_point(current_path)
                if current_path_uses_curve:
                    # Control-point bounds are safe only below the scan threshold.
                    clip_path = _bounding_box_polygon(clip_path)
                    current_clip_is_conservative = True
                elif not _is_convex_polygon(clip_path):
                    raise _PDFGeometryLimit
                current_clip = _clip_polygon(current_clip, clip_path)
            current_path = []
            current_path_uses_curve = False
            clip_pending = False
        elif operator == b"INLINE IMAGE":
            coverage = _image_coverage(current_matrix, current_clip, page_area)
            if current_clip_is_conservative and _coverage_reaches_threshold(coverage):
                raise _PDFGeometryLimit
            maximum_coverage = max(maximum_coverage, coverage)
        elif operator == b"Do":
            xobjects = _resolve_pdf_object(
                resources.get("/XObject", DictionaryObject())
            )
            if not isinstance(xobjects, dict) or operands[0] not in xobjects:
                continue
            xobject = _resolve_pdf_object(xobjects[operands[0]])
            if not isinstance(xobject, StreamObject):
                continue
            subtype = str(xobject.get("/Subtype", ""))
            if subtype == "/Image":
                coverage = _image_coverage(
                    current_matrix,
                    current_clip,
                    page_area,
                )
                if current_clip_is_conservative and _coverage_reaches_threshold(
                    coverage
                ):
                    raise _PDFGeometryLimit
                maximum_coverage = max(maximum_coverage, coverage)
            elif subtype == "/Form":
                marker = id(xobject)
                if marker in form_path:
                    raise _PDFGeometryLimit
                form_matrix = _multiply_matrix(
                    _matrix_from_pdf(xobject.get("/Matrix", _IDENTITY_MATRIX)),
                    current_matrix,
                )
                form_bbox = _rectangle_polygon(
                    xobject.get("/BBox", ()),
                    required=True,
                )
                transformed_bbox = _transform_polygon(
                    form_bbox,
                    form_matrix,
                )
                form_clip = _clip_polygon(
                    current_clip,
                    transformed_bbox,
                )
                form_resources = _resolve_pdf_object(
                    xobject.get("/Resources", resources)
                )
                if not isinstance(form_resources, DictionaryObject):
                    form_resources = resources
                form_content, form_size = _load_form_content(
                    xobject,
                    pdf,
                    context,
                )
                context.text_extraction_work_bytes += form_size
                if context.text_extraction_work_bytes > context.decoded_limit:
                    raise _PDFGeometryLimit
                maximum_coverage = max(
                    maximum_coverage,
                    _walk_raster_coverage(
                        form_content,
                        form_resources,
                        pdf,
                        context,
                        initial_matrix=form_matrix,
                        clip_polygon=form_clip,
                        clip_is_conservative=current_clip_is_conservative,
                        page_area=page_area,
                        form_path=form_path | {marker},
                        depth=depth + 1,
                    ),
                )
    return maximum_coverage


def _maximum_raster_coverage(
    page: Any,
    context: _RasterGeometryContext,
) -> float:
    context.operation_count = 0
    content = page.get_contents()
    if content is None:
        return 0.0
    resources = _resolve_pdf_object(page.get("/Resources", DictionaryObject()))
    if not isinstance(resources, DictionaryObject):
        return 0.0
    page_polygon = _rectangle_polygon(page.cropbox, required=True)
    page_area = _polygon_area(page_polygon)
    if page_area <= 0:
        raise _PDFGeometryLimit
    return _walk_raster_coverage(
        content,
        resources,
        page.pdf,
        context,
        initial_matrix=_IDENTITY_MATRIX,
        clip_polygon=page_polygon,
        clip_is_conservative=False,
        page_area=page_area,
        form_path=set(),
        depth=0,
    )


@contextmanager
def _bounded_pypdf_decode(max_output_length: int) -> Iterator[None]:
    """Apply a process-safe pypdf output cap before any stream is decoded."""
    limit = max(1, max_output_length)
    with _PYPDF_DECODE_LOCK:
        previous = {
            name: getattr(pdf_filters, name) for name in _PYPDF_DECODE_LIMIT_NAMES
        }
        try:
            for name in _PYPDF_DECODE_LIMIT_NAMES:
                setattr(pdf_filters, name, min(previous[name], limit))
            yield
        finally:
            for name, value in previous.items():
                setattr(pdf_filters, name, value)


_MAX_LINK_ANNOTATIONS = 500
_MAX_LINK_TARGET_CHARACTERS = 2_048


_ACTIVE_CONTENT_KEYS = {
    "/JS",
    "/JavaScript",
    "/AA",
    "/Launch",
    "/EmbeddedFiles",
    "/EmbeddedFile",
    "/Filespec",
    "/EF",
    "/RF",
    "/AF",
    "/XFA",
    "/RichMedia",
    "/RichMediaConfiguration",
    "/RichMediaAssets",
}
_ACTIVE_CONTENT_SUBTYPES = {
    "/EmbeddedFile",
    "/Filespec",
    "/RichMedia",
    "/3D",
    "/Screen",
    "/Movie",
    "/Sound",
    "/FileAttachment",
}
_ACTIVE_ACTION_TYPES = {
    "/JavaScript",
    "/Launch",
    "/GoToE",
    "/SubmitForm",
    "/ImportData",
    "/ResetForm",
    "/RichMediaExecute",
    "/Rendition",
    "/Movie",
    "/Sound",
    "/Hide",
    "/SetOCGState",
}


def _active_diagnostic_code(value: str) -> str:
    if value in {"/JS", "/JavaScript"}:
        return "PDF_ACTIVE_JAVASCRIPT"
    if value == "/Launch":
        return "PDF_ACTIVE_LAUNCH"
    if value in {
        "/EmbeddedFiles",
        "/EmbeddedFile",
        "/Filespec",
        "/EF",
        "/RF",
        "/AF",
        "/FileAttachment",
    }:
        return "PDF_EMBEDDED_FILE"
    if value in {"/AcroForm", "/XFA", "/SubmitForm", "/ImportData", "/ResetForm"}:
        return "PDF_ACTIVE_FORM"
    if value in {
        "/RichMedia",
        "/RichMediaConfiguration",
        "/RichMediaAssets",
        "/RichMediaExecute",
        "/Rendition",
        "/3D",
        "/Screen",
        "/Movie",
        "/Sound",
    }:
        return "PDF_ACTIVE_MEDIA"
    if value in {"/URI", "/GoToR", "/GoToE"}:
        return "PDF_ACTIVE_REMOTE_ACTION"
    if value in {"/AA", "/OpenAction", "/Next"}:
        return "PDF_ACTIVE_AUTOMATIC_ACTION"
    return "PDF_ACTIVE_CONTENT"


def _active_result(detected: list[str] | None, value: str) -> bool:
    if detected is not None and not detected:
        detected.append(_active_diagnostic_code(value))
    return True


def _resolve_active_object(
    value: Any,
    nodes: list[int],
    max_nodes: int | None = None,
) -> Any:
    if max_nodes is None:
        max_nodes = _MAX_ACTIVE_CONTENT_NODES
    seen: set[int] = set()
    while isinstance(value, IndirectObject):
        nodes[0] += 1
        if nodes[0] > max_nodes:
            raise _PDFScanLimit
        marker = id(value)
        if marker in seen:
            raise PDFValidationError("PDF_MALFORMED")
        seen.add(marker)
        value = value.get_object()
    return value


@dataclass(slots=True)
class _ActiveScanFrame:
    children: Iterator[Any]
    dictionary_children: bool
    is_page: bool = False
    is_link_annotation: bool = False
    clicked_gotor: bool = False
    annots_array_context: bool = False


def _contains_active_content(
    value: Any,
    seen: dict[tuple[Any, ...], Any] | None = None,
    *,
    nodes: list[int] | None = None,
    detected: list[str] | None = None,
    max_nodes: int | None = None,
    scan_struct_tree: bool = False,
) -> bool:
    if seen is None:
        seen = {}
    if nodes is None:
        nodes = [0]
    if max_nodes is None:
        max_nodes = _MAX_ACTIVE_CONTENT_NODES
    frames: list[_ActiveScanFrame] = []
    current = value
    direct_link_action_context = False
    gotor_file_context = False
    annots_array_context = False
    page_annotation_context = False
    key_name: str | None = None
    while True:
        visit_current = True
        if key_name is not None:
            if key_name == "/StructTreeRoot" and not scan_struct_tree:
                if _contains_active_content(
                    current,
                    nodes=[0],
                    detected=detected,
                    max_nodes=_MAX_STRUCT_TREE_NODES,
                    scan_struct_tree=True,
                ):
                    return True
                visit_current = False
            elif key_name in {"/P", "/Parent", "/Dest", "/D"} or (
                scan_struct_tree and key_name in {"/Pg", "/Obj"}
            ):
                visit_current = False
            else:
                current = _resolve_active_object(current, nodes, max_nodes)
                if current is None or isinstance(current, NullObject):
                    visit_current = False
                elif key_name == "/AcroForm":
                    if not isinstance(current, dict):
                        return _active_result(detected, key_name)
                    fields = _resolve_active_object(
                        current.get("/Fields"),
                        nodes,
                        max_nodes,
                    )
                    if (
                        fields is not None
                        and not isinstance(fields, NullObject)
                        and (not isinstance(fields, (list, tuple)) or fields)
                    ):
                        return _active_result(detected, key_name)
                    for active_key in ("/XFA", "/JS"):
                        active_value = _resolve_active_object(
                            current.get(active_key),
                            nodes,
                            max_nodes,
                        )
                        if active_value is not None and not isinstance(
                            active_value,
                            NullObject,
                        ):
                            return _active_result(detected, active_key)
                elif key_name == "/OpenAction":
                    if isinstance(current, (list, tuple)):
                        visit_current = False
                    elif isinstance(current, dict):
                        action_type = _resolve_active_object(
                            current.get("/S"),
                            nodes,
                            max_nodes,
                        )
                        if not (
                            isinstance(action_type, NameObject)
                            and action_type == "/GoTo"
                        ):
                            return _active_result(
                                detected, str(action_type or key_name)
                            )
                elif key_name in _ACTIVE_CONTENT_KEYS:
                    return _active_result(detected, key_name)

        if visit_current:
            nodes[0] += 1
            if nodes[0] > max_nodes:
                raise _PDFScanLimit
            if isinstance(current, IndirectObject):
                current = _resolve_active_object(current, nodes, max_nodes)
            marker = (
                id(current),
                direct_link_action_context,
                gotor_file_context,
                annots_array_context,
                page_annotation_context,
            )
            if marker not in seen or seen[marker] is not current:
                seen[marker] = current
                if isinstance(current, dict):
                    object_type = _resolve_active_object(
                        current.get("/Type"),
                        nodes,
                        max_nodes,
                    )
                    subtype = _resolve_active_object(
                        current.get("/Subtype"),
                        nodes,
                        max_nodes,
                    )
                    object_type_name = str(object_type)
                    subtype_name = str(subtype)
                    is_page = (
                        isinstance(object_type, NameObject) and object_type == "/Page"
                    )
                    is_link_annotation = (
                        page_annotation_context
                        and isinstance(subtype, NameObject)
                        and subtype == "/Link"
                    )
                    filespec_exception = gotor_file_context and (
                        (
                            isinstance(object_type, NameObject)
                            and object_type == "/Filespec"
                        )
                        or (isinstance(subtype, NameObject) and subtype == "/Filespec")
                    )
                    if (
                        subtype_name in _ACTIVE_CONTENT_SUBTYPES
                        or object_type_name in _ACTIVE_CONTENT_SUBTYPES
                    ) and not filespec_exception:
                        return _active_result(
                            detected,
                            (
                                subtype_name
                                if subtype_name in _ACTIVE_CONTENT_SUBTYPES
                                else object_type_name
                            ),
                        )
                    action_type = _resolve_active_object(
                        current.get("/S"),
                        nodes,
                        max_nodes,
                    )
                    action_type_name = str(action_type)
                    direct_link_action = (
                        direct_link_action_context
                        and isinstance(action_type, NameObject)
                        and action_type_name in {"/URI", "/GoToR"}
                    )
                    if (
                        action_type_name in _ACTIVE_ACTION_TYPES
                        or action_type_name in {"/URI", "/GoToR"}
                    ) and not direct_link_action:
                        return _active_result(detected, action_type_name)
                    clicked_gotor = direct_link_action and action_type_name == "/GoToR"
                    if clicked_gotor:
                        target = _resolve_active_object(
                            current.get("/F"),
                            nodes,
                            max_nodes,
                        )
                        target_type = (
                            _resolve_active_object(
                                target.get("/Type"),
                                nodes,
                                max_nodes,
                            )
                            if isinstance(target, DictionaryObject)
                            else None
                        )
                        if not (
                            isinstance(target, (TextStringObject, ByteStringObject))
                            or (
                                isinstance(target, DictionaryObject)
                                and not isinstance(target, StreamObject)
                                and isinstance(target_type, NameObject)
                                and target_type == "/Filespec"
                            )
                        ):
                            return _active_result(detected, "/GoToR")
                    frames.append(
                        _ActiveScanFrame(
                            children=iter(current.items()),
                            dictionary_children=True,
                            is_page=is_page,
                            is_link_annotation=is_link_annotation,
                            clicked_gotor=clicked_gotor,
                        )
                    )
                elif isinstance(current, (list, tuple)):
                    frames.append(
                        _ActiveScanFrame(
                            children=iter(current),
                            dictionary_children=False,
                            annots_array_context=annots_array_context,
                        )
                    )

        while frames:
            frame = frames[-1]
            try:
                child = next(frame.children)
            except StopIteration:
                frames.pop()
                continue
            if frame.dictionary_children:
                key, current = child
                key_name = str(key)
                direct_link_action_context = (
                    frame.is_link_annotation and key_name == "/A"
                )
                gotor_file_context = frame.clicked_gotor and key_name == "/F"
                annots_array_context = frame.is_page and key_name == "/Annots"
                page_annotation_context = False
            else:
                current = child
                direct_link_action_context = False
                gotor_file_context = False
                annots_array_context = False
                page_annotation_context = frame.annots_array_context
                key_name = None
            break
        else:
            return False


def _page_geometry(page: Any) -> tuple[float, float, float, float, int] | None:
    try:
        width = float(page.mediabox.width)
        height = float(page.mediabox.height)
        left = float(page.mediabox.left)
        bottom = float(page.mediabox.bottom)
        rotation = int(page.rotation) % 360
    except (AttributeError, TypeError, ValueError, OverflowError):
        return None
    if (
        not all(isfinite(value) for value in (width, height, left, bottom))
        or width <= 0
        or height <= 0
        or rotation not in {0, 90, 180, 270}
    ):
        return None
    return width, height, left, bottom, rotation


def _page_bbox(page: Any) -> dict[str, float] | None:
    geometry = _page_geometry(page)
    if geometry is None:
        return None
    width, height, _left, _bottom, rotation = geometry
    if rotation in {90, 270}:
        width, height = height, width
    return {"x0": 0.0, "top": 0.0, "x1": width, "bottom": height}


def _annotation_bbox(
    annotation: dict[str, Any],
    page: Any,
    nodes: list[int],
) -> dict[str, float] | None:
    geometry = _page_geometry(page)
    page_bbox = _page_bbox(page)
    if geometry is None or page_bbox is None:
        return None
    rect = _resolve_active_object(annotation.get("/Rect"), nodes)
    if not isinstance(rect, (list, tuple)) or len(rect) != 4:
        return None
    try:
        coordinates = [float(value) for value in rect]
    except (TypeError, ValueError, OverflowError):
        return None
    width, height, page_left, page_bottom, rotation = geometry
    if not all(isfinite(value) for value in coordinates):
        return None
    first_x, first_y, second_x, second_y = coordinates
    x0 = min(first_x, second_x) - page_left
    x1 = max(first_x, second_x) - page_left
    y0 = min(first_y, second_y) - page_bottom
    y1 = max(first_y, second_y) - page_bottom
    if x0 < 0 or y0 < 0 or x1 > width or y1 > height or x0 > x1 or y0 > y1:
        return None
    if rotation == 0:
        transformed = (x0, height - y1, x1, height - y0)
    elif rotation == 90:
        transformed = (y0, x0, y1, x1)
    elif rotation == 180:
        transformed = (width - x1, y0, width - x0, y1)
    else:
        transformed = (height - y1, width - x1, height - y0, width - x0)
    left, top, right, bottom = transformed
    if (
        left < 0
        or top < 0
        or right > page_bbox["x1"]
        or bottom > page_bbox["bottom"]
        or left > right
        or top > bottom
    ):
        return None
    return {"x0": left, "top": top, "x1": right, "bottom": bottom}


def _pdf_string(value: Any) -> str | None:
    if isinstance(value, TextStringObject):
        return str(value)
    if isinstance(value, ByteStringObject):
        return bytes(value).decode("utf-8", errors="replace")
    return None


def _safe_link(
    annotation: dict[str, Any],
    page: Any,
    page_number: int,
    nodes: list[int],
) -> PDFLink | None:
    subtype = _resolve_active_object(annotation.get("/Subtype"), nodes)
    if not isinstance(subtype, NameObject) or subtype != "/Link":
        return None
    action = _resolve_active_object(annotation.get("/A"), nodes)
    if not isinstance(action, dict):
        return None
    action_type = _resolve_active_object(action.get("/S"), nodes)
    if not isinstance(action_type, NameObject) or action_type not in {
        "/URI",
        "/GoToR",
    }:
        return None
    if action_type == "/URI":
        target = _pdf_string(_resolve_active_object(action.get("/URI"), nodes))
    else:
        raw_target = _resolve_active_object(action.get("/F"), nodes)
        target = _pdf_string(raw_target)
        if isinstance(raw_target, dict):
            target = _pdf_string(
                _resolve_active_object(
                    raw_target.get("/UF", raw_target.get("/F")),
                    nodes,
                )
            )
    if target is None:
        target = ""
    truncated = len(target) > _MAX_LINK_TARGET_CHARACTERS
    return PDFLink(
        page_number=page_number,
        bbox=_annotation_bbox(annotation, page, nodes),
        action_type=str(action_type).removeprefix("/"),
        target=target[:_MAX_LINK_TARGET_CHARACTERS],
        target_truncated=truncated,
    )


def _active_content_and_links(
    reader: PdfReader,
    pages: Any,
) -> tuple[PDFDiagnostic | None, tuple[PDFLink, ...]]:
    nodes = [0]
    links: list[PDFLink] = []
    for page_number, page in enumerate(pages, start=1):
        annots = _resolve_active_object(page.get("/Annots"), nodes)
        if annots is None or isinstance(annots, NullObject):
            continue
        if not isinstance(annots, (list, tuple)):
            raise PDFValidationError("PDF_MALFORMED")
        for raw_annotation in annots:
            annotation = _resolve_active_object(raw_annotation, nodes)
            if not isinstance(annotation, dict):
                raise PDFValidationError("PDF_MALFORMED")
            detected: list[str] = []
            local_annotation = DictionaryObject(
                {
                    key: value
                    for key, value in annotation.items()
                    if str(key) not in {"/P", "/Parent"}
                }
            )
            wrapped_page = {
                NameObject("/Type"): NameObject("/Page"),
                NameObject("/Annots"): [local_annotation],
            }
            if _contains_active_content(
                wrapped_page,
                nodes=nodes,
                detected=detected,
            ):
                bbox = _annotation_bbox(annotation, page, nodes)
                return (
                    PDFDiagnostic(
                        code=detected[0] if detected else "PDF_ACTIVE_CONTENT",
                        category="SECURITY",
                        disposition="BLOCK",
                        scope="REGION" if bbox is not None else "PAGE",
                        page_number=page_number,
                        bbox=bbox or _page_bbox(page),
                    ),
                    tuple(links),
                )
            link = _safe_link(annotation, page, page_number, nodes)
            if link is not None:
                if len(links) >= _MAX_LINK_ANNOTATIONS:
                    raise PDFValidationError("PDF_STRUCTURE_LIMIT")
                links.append(link)

    detected = []
    if _contains_active_content(reader.trailer, detected=detected):
        return (
            PDFDiagnostic(
                code=detected[0] if detected else "PDF_ACTIVE_CONTENT",
                category="SECURITY",
                disposition="BLOCK",
            ),
            tuple(links),
        )
    return None, tuple(links)


def _validate_pdf_once(
    data: bytes,
    *,
    strict: bool,
    max_page_count: int,
    max_decoded_bytes: int,
) -> tuple[int, bool, tuple[PDFLink, ...]]:
    try:
        with (
            _suppress_untrusted_pdf_logs(),
            _bounded_pypdf_decode(max_decoded_bytes),
        ):
            reader = PdfReader(BytesIO(data), strict=strict)
            if reader.is_encrypted:
                raise PDFValidationError(
                    "PDF_ENCRYPTED",
                    diagnostic=PDFDiagnostic(
                        code="PDF_ENCRYPTED",
                        category="SECURITY",
                        disposition="BLOCK",
                    ),
                )
            page_count = _preflight_page_tree(reader, max_page_count)
            pages = reader.pages
            active_diagnostic, links = _active_content_and_links(reader, pages)
            if active_diagnostic is not None:
                raise PDFValidationError(
                    "PDF_ACTIVE_CONTENT",
                    diagnostic=active_diagnostic,
                )

            text_found = False
            geometry_context = _RasterGeometryContext(max_decoded_bytes)
            for page_number, page in enumerate(pages, start=1):
                page_content_size = _decode_page_content_size(
                    page,
                    geometry_context.remaining_decoded_bytes,
                )
                geometry_context.remaining_decoded_bytes -= page_content_size
                useful_character_count = 0
                try:
                    _preflight_form_streams(page, geometry_context)
                    text = page.extract_text() or ""
                    useful_character_count = sum(
                        not character.isspace() for character in text
                    )
                    if useful_character_count:
                        text_found = True
                    if useful_character_count >= _MIN_USEFUL_TEXT_CHARACTERS:
                        continue
                    image_coverage = _maximum_raster_coverage(
                        page,
                        geometry_context,
                    )
                except _PDFGeometryLimit as exc:
                    raise PDFValidationError(
                        "PDF_SCAN_ANALYSIS_UNSUPPORTED",
                        diagnostic=PDFDiagnostic(
                            code="PDF_SCAN_ANALYSIS_UNSUPPORTED",
                            category="COMPATIBILITY",
                            disposition="BLOCK",
                            scope="PAGE",
                            page_number=page_number,
                            bbox=_page_bbox(page),
                            metrics={"useful_characters": useful_character_count},
                        ),
                    ) from exc
                if _coverage_reaches_threshold(image_coverage):
                    raise PDFValidationError(
                        "PDF_SCAN_ONLY",
                        diagnostic=PDFDiagnostic(
                            code="PDF_SCAN_DETECTED",
                            category="COMPATIBILITY",
                            disposition="BLOCK",
                            scope="PAGE",
                            page_number=page_number,
                            bbox=_page_bbox(page),
                            metrics={
                                "useful_characters": useful_character_count,
                                "image_coverage_percent": round(
                                    image_coverage * 100,
                                    2,
                                ),
                            },
                        ),
                    )
            if not text_found:
                raise PDFValidationError(
                    "PDF_SCAN_ONLY",
                    diagnostic=PDFDiagnostic(
                        code="PDF_TEXT_LAYER_MISSING",
                        category="COMPATIBILITY",
                        disposition="BLOCK",
                    ),
                )
            return page_count, text_found, links
    except PDFValidationError:
        raise
    except _PDFScanLimit as exc:
        raise PDFValidationError(
            "PDF_SCAN_LIMIT",
            diagnostic=PDFDiagnostic(
                code="PDF_SCAN_LIMIT",
                category="SECURITY",
                disposition="BLOCK",
            ),
        ) from exc
    except LimitReachedError as exc:
        raise PDFValidationError("PDF_DECODED_TOO_LARGE") from exc
    except (PdfReadError, PdfStreamError) as exc:
        raise PDFValidationError("PDF_MALFORMED") from exc


def _caused_by_parser_error(error: BaseException) -> bool:
    current: BaseException | None = error
    seen: set[int] = set()
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        if isinstance(current, (PdfReadError, PdfStreamError)):
            return True
        current = current.__cause__ or current.__context__
    return False


def _unrecoverable(error: PDFValidationError) -> PDFValidationError:
    return PDFValidationError(
        "PDF_MALFORMED",
        diagnostic=PDFDiagnostic(
            code="PDF_STRUCTURE_UNRECOVERABLE",
            category="COMPATIBILITY",
            disposition="BLOCK",
        ),
    )


def validate_pdf(
    data: bytes,
    *,
    max_size_bytes: int = 100_000_000,
    max_decoded_bytes: int = 50_000_000,
    max_page_count: int = 100,
) -> PDFValidationResult:
    if len(data) > max_size_bytes:
        raise PDFValidationError(
            "PDF_TOO_LARGE",
            diagnostic=PDFDiagnostic(
                code="PDF_TOO_LARGE",
                category="RESOURCE",
                disposition="BLOCK",
                metrics={"observed_bytes": len(data), "limit_bytes": max_size_bytes},
            ),
        )
    if not data.startswith(b"%PDF-"):
        raise PDFValidationError(
            "NOT_A_PDF",
            diagnostic=PDFDiagnostic(
                code="NOT_A_PDF",
                category="FORMAT",
                disposition="BLOCK",
            ),
        )

    diagnostics: tuple[PDFDiagnostic, ...] = ()
    try:
        page_count, text_found, links = _validate_pdf_once(
            data,
            strict=True,
            max_page_count=max_page_count,
            max_decoded_bytes=max_decoded_bytes,
        )
    except PDFValidationError as strict_error:
        if strict_error.code != "PDF_MALFORMED" or not _caused_by_parser_error(
            strict_error
        ):
            if strict_error.code == "PDF_MALFORMED":
                raise _unrecoverable(strict_error) from strict_error
            raise
        try:
            page_count, text_found, links = _validate_pdf_once(
                data,
                strict=False,
                max_page_count=max_page_count,
                max_decoded_bytes=max_decoded_bytes,
            )
        except PDFValidationError as lenient_error:
            if lenient_error.code == "PDF_MALFORMED":
                raise _unrecoverable(lenient_error) from lenient_error
            raise
        diagnostics = (
            PDFDiagnostic(
                code="PDF_STRUCTURE_RECOVERED",
                category="COMPATIBILITY",
                disposition="WARN",
            ),
        )

    return PDFValidationResult(
        sha256=hashlib.sha256(data).hexdigest(),
        size_bytes=len(data),
        page_count=page_count,
        has_text=text_found,
        diagnostics=diagnostics,
        links=links,
    )
