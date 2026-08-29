"""Bounded validation of untrusted PDF bytes."""

from __future__ import annotations

import hashlib
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from io import BytesIO
from threading import RLock
from typing import Any

from pypdf import PdfReader
from pypdf import filters as pdf_filters
from pypdf.errors import LimitReachedError
from pypdf.generic import (
    ArrayObject,
    IndirectObject,
    NullObject,
    StreamObject,
)


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


def _contains_active_content(
    value: Any,
    seen: set[int] | None = None,
    *,
    nodes: list[int] | None = None,
) -> bool:
    if seen is None:
        seen = set()
    if nodes is None:
        nodes = [0]
    nodes[0] += 1
    if nodes[0] > 10_000:
        raise _PDFScanLimit
    marker = id(value)
    if marker in seen:
        return False
    seen.add(marker)
    if isinstance(value, IndirectObject):
        try:
            resolved = value.get_object()
        except Exception as exc:
            raise _PDFScanLimit from exc
        return _contains_active_content(resolved, seen, nodes=nodes)
    if isinstance(value, dict):
        for key, child in value.items():
            key_name = str(key)
            if key_name in {
                "/JavaScript",
                "/JS",
                "/OpenAction",
                "/AA",
                "/RichMedia",
                "/Launch",
                "/SubmitForm",
                "/GoToR",
                "/EmbeddedFiles",
                "/Filespec",
            }:
                return True
            if _contains_active_content(child, seen, nodes=nodes):
                return True
    elif isinstance(value, (list, tuple)):
        return any(_contains_active_content(item, seen, nodes=nodes) for item in value)
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
        with _bounded_pypdf_decode(max_size_bytes):
            reader = PdfReader(BytesIO(data), strict=True)
            if reader.is_encrypted:
                raise PDFValidationError("PDF_ENCRYPTED")
            page_count = len(reader.pages)
            if page_count > max_page_count:
                raise PDFValidationError("PDF_PAGE_LIMIT")
            if _contains_active_content(reader.trailer):
                raise PDFValidationError("PDF_ACTIVE_CONTENT")
            text_found = False
            decoded_size = 0
            for page in reader.pages:
                remaining_bytes = max_size_bytes - decoded_size
                decoded_size += _decode_page_content_size(page, remaining_bytes)
                text = page.extract_text() or ""
                if text.strip():
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
