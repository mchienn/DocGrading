"""Pure, bounded Document IR parser and structure extraction service."""

from __future__ import annotations

from dataclasses import dataclass
from io import BytesIO
from typing import Any, Sequence

import pdfplumber

from app.services.pdf_validation import (
    PDFValidationError,
    PDFValidationResult,
    validate_pdf,
)

SCHEMA_VERSION: int = 1
PARSER_VERSION: str = "pypdf-pdfplumber-v1"


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


def _parse_pages(
    pages: Sequence[Any],
    budget: _NodeBudget,
) -> list[dict[str, Any]]:
    """Extract bounded page geometry and initial structure containers."""
    parsed_pages: list[dict[str, Any]] = []
    for index, page in enumerate(pages, start=1):
        parsed_pages.append(
            {
                "number": index,
                "width": float(getattr(page, "width", 0.0)),
                "height": float(getattr(page, "height", 0.0)),
                "text": "",
                "headings": [],
                "paragraphs": [],
                "tables": [],
            }
        )
    return parsed_pages


def _assemble_ir(
    validation: PDFValidationResult,
    pages: list[dict[str, Any]],
    budget: _NodeBudget,
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
        "sections": [],
        "paragraphs": [],
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
    try:
        with pdfplumber.open(BytesIO(data)) as pdf:
            pages = _parse_pages(pdf.pages, budget)
    except PDFValidationError:
        raise
    except Exception as exc:
        raise DocumentIRExtractionError("Document IR extraction failed") from exc
    content = _assemble_ir(validation, pages, budget)
    return ParsedDocumentIR(validation=validation, content=content)
