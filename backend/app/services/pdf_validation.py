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
from pypdf.errors import LimitReachedError
from pypdf.generic import (
    ArrayObject,
    ContentStream,
    DictionaryObject,
    IndirectObject,
    NullObject,
    StreamObject,
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
            for namespace in _PYPDF_LOG_NAMESPACES:
                for name, logger in logging.Logger.manager.loggerDict.items():
                    if (
                        isinstance(logger, logging.Logger)
                        and (
                            name == namespace
                            or name.startswith(f"{namespace}.")
                        )
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


@dataclass(frozen=True)
class PDFValidationResult:
    sha256: str
    size_bytes: int
    page_count: int
    has_text: bool


class PDFValidationError(ValueError):
    def __init__(self, code: str, detail: str | None = None) -> None:
        self.code = code
        self.detail = detail or code
        super().__init__(self.detail)


class _PDFScanLimit(Exception):
    pass


class _PDFGeometryLimit(Exception):
    pass


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
    try:
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
            object_type = str(
                _resolve_page_tree_object(resolved.get("/Type"), work)
            )
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
            if len(kids) > (
                _MAX_PAGE_TREE_NODES - node_count - len(pending) - work[0]
            ):
                raise PDFValidationError("PDF_MALFORMED")
            pending.extend((child, depth + 1) for child in kids)
        return page_count
    except PDFValidationError:
        raise
    except Exception as exc:
        raise PDFValidationError("PDF_MALFORMED") from exc


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
    content = ContentStream(xobject, pdf, "bytes")
    context.form_contents[marker] = content
    context.form_decoded_sizes[marker] = decoded_size
    return content, decoded_size


def _walk_raster_coverage(
    content: ContentStream,
    resources: DictionaryObject,
    pdf: Any,
    context: _RasterGeometryContext,
    *,
    initial_matrix: Matrix,
    clip_polygon: Polygon,
    page_area: float,
    form_path: set[int],
    depth: int,
) -> float:
    if depth > _MAX_FORM_DEPTH:
        raise _PDFGeometryLimit
    initial_clip = clip_polygon.copy()
    current_matrix = initial_matrix
    current_clip = initial_clip.copy()
    current_path: Polygon | None = []
    clip_pending = False
    graphics_stack: list[tuple[Matrix, Polygon]] = []
    maximum_coverage = 0.0
    for operands, operator in content.operations:
        context.operation_count += 1
        if context.operation_count > _MAX_GEOMETRY_OPERATIONS:
            raise _PDFGeometryLimit
        if operator == b"q":
            graphics_stack.append((current_matrix, current_clip.copy()))
        elif operator == b"Q":
            if graphics_stack:
                current_matrix, current_clip = graphics_stack.pop()
            else:
                current_matrix = initial_matrix
                current_clip = initial_clip.copy()
        elif operator == b"cm" and len(operands) >= 6:
            matrix = tuple(map(float, operands[:6]))
            current_matrix = _multiply_matrix(
                _matrix_from_pdf(matrix),
                current_matrix,
            )
        elif operator == b"re" and len(operands) >= 4:
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
        elif operator == b"m" and len(operands) >= 2:
            if current_path:
                current_path = None
            elif current_path is not None:
                current_path.append(
                    _transform_polygon(
                        [(float(operands[0]), float(operands[1]))],
                        current_matrix,
                    )[0]
                )
        elif operator == b"l" and len(operands) >= 2:
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
            current_path = None
        elif operator == b"W":
            clip_pending = True
        elif operator == b"W*":
            clip_pending = True
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
                if not _is_convex_polygon(clip_path):
                    raise _PDFGeometryLimit
                current_clip = _clip_polygon(current_clip, clip_path)
            current_path = []
            clip_pending = False
        elif operator == b"INLINE IMAGE":
            maximum_coverage = max(
                maximum_coverage,
                _image_coverage(current_matrix, current_clip, page_area),
            )
        elif operator == b"Do" and operands:
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
                maximum_coverage = max(
                    maximum_coverage,
                    _image_coverage(
                        current_matrix,
                        current_clip,
                        page_area,
                    ),
                )
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


_ACTIVE_CONTENT_KEYS = {
    "/JS",
    "/JavaScript",
    "/OpenAction",
    "/AA",
    "/Launch",
    "/EmbeddedFiles",
    "/EmbeddedFile",
    "/Filespec",
    "/EF",
    "/RF",
    "/AF",
    "/XFA",
    "/AcroForm",
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
    "/GoToR",
    "/GoToE",
    "/SubmitForm",
    "/ImportData",
    "/ResetForm",
    "/URI",
    "/RichMediaExecute",
    "/Rendition",
    "/Movie",
    "/Sound",
    "/Hide",
    "/SetOCGState",
}
_ACTION_CHILD_KEYS = {"/A", "/AA", "/OpenAction", "/Next"}


def _resolve_active_object(value: Any, nodes: list[int]) -> Any:
    seen: set[int] = set()
    while isinstance(value, IndirectObject):
        nodes[0] += 1
        if nodes[0] > 10_000:
            raise _PDFScanLimit
        marker = id(value)
        if marker in seen:
            raise _PDFScanLimit
        seen.add(marker)
        try:
            value = value.get_object()
        except Exception as exc:
            raise _PDFScanLimit from exc
    return value


def _contains_active_content(
    value: Any,
    seen: set[tuple[int, bool]] | None = None,
    *,
    nodes: list[int] | None = None,
    _action_context: bool = False,
) -> bool:
    if seen is None:
        seen = set()
    if nodes is None:
        nodes = [0]
    nodes[0] += 1
    if nodes[0] > 10_000:
        raise _PDFScanLimit
    if isinstance(value, IndirectObject):
        value = _resolve_active_object(value, nodes)
    marker = (id(value), _action_context)
    if marker in seen:
        return False
    seen.add(marker)
    if isinstance(value, dict):
        try:
            object_type = _resolve_active_object(value.get("/Type"), nodes)
            subtype = _resolve_active_object(value.get("/Subtype"), nodes)
        except _PDFScanLimit:
            raise
        except Exception as exc:
            raise _PDFScanLimit from exc
        object_type_name = str(object_type)
        subtype_name = str(subtype)
        is_action = _action_context or object_type_name == "/Action"
        if (
            subtype_name in _ACTIVE_CONTENT_SUBTYPES
            or object_type_name in _ACTIVE_CONTENT_SUBTYPES
        ):
            return True
        for key, child in value.items():
            key_name = str(key)
            resolved_child = _resolve_active_object(child, nodes)
            if resolved_child is None or isinstance(resolved_child, NullObject):
                continue
            if key_name in _ACTIVE_CONTENT_KEYS:
                return True
            if (
                key_name == "/S"
                and is_action
                and str(resolved_child) in _ACTIVE_ACTION_TYPES
            ):
                return True
            if _contains_active_content(
                resolved_child,
                seen,
                nodes=nodes,
                _action_context=key_name in _ACTION_CHILD_KEYS,
            ):
                return True
    elif isinstance(value, (list, tuple)):
        return any(
            _contains_active_content(
                item,
                seen,
                nodes=nodes,
                _action_context=_action_context,
            )
            for item in value
        )
    return False


def validate_pdf(
    data: bytes,
    *,
    max_size_bytes: int = 50_000_000,
    max_page_count: int = 100,
) -> PDFValidationResult:
    if len(data) > max_size_bytes:
        raise PDFValidationError("PDF_TOO_LARGE")
    if not data.startswith(b"%PDF-"):
        raise PDFValidationError("NOT_A_PDF")
    try:
        with (
            _suppress_untrusted_pdf_logs(),
            _bounded_pypdf_decode(max_size_bytes),
        ):
            reader = PdfReader(BytesIO(data), strict=True)
            if reader.is_encrypted:
                raise PDFValidationError("PDF_ENCRYPTED")
            page_count = _preflight_page_tree(reader, max_page_count)
            pages = reader.pages
            if _contains_active_content(reader.trailer):
                raise PDFValidationError("PDF_ACTIVE_CONTENT")
            text_found = False
            geometry_context = _RasterGeometryContext(max_size_bytes)
            for page in pages:
                page_content_size = _decode_page_content_size(
                    page,
                    geometry_context.remaining_decoded_bytes,
                )
                geometry_context.remaining_decoded_bytes -= page_content_size
                image_coverage = _maximum_raster_coverage(
                    page,
                    geometry_context,
                )
                text = page.extract_text() or ""
                useful_character_count = sum(
                    not character.isspace() for character in text
                )
                if (
                    _coverage_reaches_threshold(image_coverage)
                    and useful_character_count < _MIN_USEFUL_TEXT_CHARACTERS
                ):
                    raise PDFValidationError("PDF_SCAN_ONLY")
                if useful_character_count:
                    text_found = True
            if not text_found:
                raise PDFValidationError("PDF_SCAN_ONLY")
    except PDFValidationError:
        raise
    except _PDFScanLimit as exc:
        raise PDFValidationError("PDF_ACTIVE_CONTENT") from exc
    except Exception as exc:
        raise PDFValidationError("PDF_MALFORMED") from exc
    return PDFValidationResult(
        sha256=hashlib.sha256(data).hexdigest(),
        size_bytes=len(data),
        page_count=page_count,
        has_text=text_found,
    )
