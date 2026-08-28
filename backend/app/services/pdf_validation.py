"""Bounded validation of untrusted PDF bytes."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from io import BytesIO
from typing import Any

from pypdf import PdfReader
from pypdf.generic import IndirectObject


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
        reader = PdfReader(BytesIO(data), strict=True)
        if reader.is_encrypted:
            raise PDFValidationError("PDF_ENCRYPTED")
        page_count = len(reader.pages)
        if page_count > max_page_count:
            raise PDFValidationError("PDF_PAGE_LIMIT")
        if _contains_active_content(reader.trailer):
            raise PDFValidationError("PDF_ACTIVE_CONTENT")
        text_found = False
        for page in reader.pages:
            contents = page.get_contents()
            if contents is not None:
                decoded_data = contents.get_data()
                if decoded_data is not None and len(decoded_data) > max_size_bytes:
                    raise PDFValidationError("PDF_DECODED_TOO_LARGE")
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
