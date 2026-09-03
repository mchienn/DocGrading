from io import BytesIO
from typing import Any

import pydantic
import pytest
from pypdf import PdfWriter
from pypdf.generic import (
    DecodedStreamObject,
    DictionaryObject,
    NameObject,
)

from app.core.config import Settings
from app.services import document_ir
from app.services.document_ir import (
    PARSER_VERSION,
    SCHEMA_VERSION,
    DocumentIRExtractionError,
    ParsedDocumentIR,
    _NodeBudget,
    parse_document_ir,
)
from app.services.pdf_validation import PDFValidationError


def _make_text_pdf(*page_texts: str) -> bytes:
    writer = PdfWriter()
    font = DictionaryObject(
        {
            NameObject("/Type"): NameObject("/Font"),
            NameObject("/Subtype"): NameObject("/Type1"),
            NameObject("/BaseFont"): NameObject("/Helvetica"),
        }
    )
    resources = DictionaryObject(
        {NameObject("/Font"): DictionaryObject({NameObject("/F1"): font})}
    )
    for text in page_texts:
        page = writer.add_blank_page(width=612, height=792)
        page[NameObject("/Resources")] = resources
        content = DecodedStreamObject()
        ops = [f"BT /F1 12 Tf 72 700 Td ({text}) Tj ET"]
        content.set_data("\n".join(ops).encode("ascii"))
        page[NameObject("/Contents")] = writer._add_object(content)
    output = BytesIO()
    writer.write(output)
    return output.getvalue()


def _make_active_pdf(*, js: bool = False, attachment: bool = False) -> bytes:
    writer = PdfWriter()
    font = DictionaryObject(
        {
            NameObject("/Type"): NameObject("/Font"),
            NameObject("/Subtype"): NameObject("/Type1"),
            NameObject("/BaseFont"): NameObject("/Helvetica"),
        }
    )
    resources = DictionaryObject(
        {NameObject("/Font"): DictionaryObject({NameObject("/F1"): font})}
    )
    page = writer.add_blank_page(width=612, height=792)
    page[NameObject("/Resources")] = resources
    content = DecodedStreamObject()
    content.set_data(b"BT /F1 12 Tf 72 700 Td (Valid text body for active test) Tj ET")
    page[NameObject("/Contents")] = writer._add_object(content)
    if js:
        writer.add_js("app.alert('malicious')")
    if attachment:
        writer.add_attachment("malicious.txt", b"malicious content")
    output = BytesIO()
    writer.write(output)
    return output.getvalue()


def test_parser_validates_before_opening_pdf(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[str] = []

    def reject(_data: bytes, **_limits: Any) -> Any:
        calls.append("validate")
        raise PDFValidationError("PDF_ACTIVE_CONTENT")

    def must_not_open(_stream: BytesIO) -> Any:
        calls.append("open")
        raise AssertionError("pdfplumber must not open rejected bytes")

    monkeypatch.setattr(document_ir, "validate_pdf", reject)
    monkeypatch.setattr(document_ir.pdfplumber, "open", must_not_open)

    with pytest.raises(PDFValidationError, match="PDF_ACTIVE_CONTENT"):
        parse_document_ir(b"%PDF-rejected")
    assert calls == ["validate"]


def test_real_javascript_pdf_rejected_before_pdfplumber_open(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[str] = []

    def must_not_open(_stream: Any) -> Any:
        calls.append("open")
        raise AssertionError("pdfplumber.open must not be called for active JS PDF")

    monkeypatch.setattr(document_ir.pdfplumber, "open", must_not_open)

    js_pdf = _make_active_pdf(js=True)
    with pytest.raises(PDFValidationError) as exc_info:
        parse_document_ir(js_pdf)

    assert exc_info.value.code == "PDF_ACTIVE_CONTENT"
    assert calls == []


def test_real_attachment_pdf_rejected_before_pdfplumber_open(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[str] = []

    def must_not_open(_stream: Any) -> Any:
        calls.append("open")
        raise AssertionError("pdfplumber.open must not be called for attachment PDF")

    monkeypatch.setattr(document_ir.pdfplumber, "open", must_not_open)

    attachment_pdf = _make_active_pdf(attachment=True)
    with pytest.raises(PDFValidationError) as exc_info:
        parse_document_ir(attachment_pdf)

    assert exc_info.value.code == "PDF_ACTIVE_CONTENT"
    assert calls == []


def test_node_budget_fails_closed_on_overflow_and_negative() -> None:
    budget = _NodeBudget(limit=2)
    budget.consume()
    assert budget.used == 1
    budget.consume()
    assert budget.used == 2
    with pytest.raises(PDFValidationError) as exc_info:
        budget.consume()
    assert exc_info.value.code == "PDF_STRUCTURE_LIMIT"

    with pytest.raises(PDFValidationError) as negative_exc:
        budget.consume(-1)
    assert negative_exc.value.code == "PDF_STRUCTURE_LIMIT"

    zero_budget = _NodeBudget(limit=0)
    with pytest.raises(PDFValidationError) as zero_exc:
        zero_budget.consume(1)
    assert zero_exc.value.code == "PDF_STRUCTURE_LIMIT"

    large_budget = _NodeBudget(limit=5)
    with pytest.raises(PDFValidationError) as overflow_exc:
        large_budget.consume(6)
    assert overflow_exc.value.code == "PDF_STRUCTURE_LIMIT"


def test_page_count_exceeding_budget_prevents_pdfplumber_open(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pdf_bytes = _make_text_pdf(
        "Page one content with enough characters for test",
        "Page two content with enough characters for test",
        "Page three content with enough characters for test",
        "Page four content with enough characters for test",
        "Page five content with enough characters for test",
    )

    def must_not_open(_stream: Any) -> Any:
        raise AssertionError(
            "pdfplumber.open must not be called when page_count exceeds budget"
        )

    monkeypatch.setattr(document_ir.pdfplumber, "open", must_not_open)

    with pytest.raises(PDFValidationError) as exc_info:
        parse_document_ir(pdf_bytes, max_nodes=3)

    assert exc_info.value.code == "PDF_STRUCTURE_LIMIT"


def test_config_rejects_non_positive_node_budget() -> None:
    with pytest.raises(pydantic.ValidationError):
        Settings(
            postgres_db="test",
            postgres_user="test",
            postgres_password="test",
            pdf_ir_max_nodes=0,
        )

    with pytest.raises(pydantic.ValidationError):
        Settings(
            postgres_db="test",
            postgres_user="test",
            postgres_password="test",
            pdf_ir_max_nodes=-10,
        )

    valid_settings = Settings(
        postgres_db="test",
        postgres_user="test",
        postgres_password="test",
        pdf_ir_max_nodes=100_000,
    )
    assert valid_settings.pdf_ir_max_nodes == 100_000


def test_unexpected_extractor_error_is_sanitized(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pdf_bytes = _make_text_pdf("Valid page text content for test scenario")

    def broken_open(_stream: Any) -> Any:
        raise RuntimeError("Secret server internal path /var/secret/leaked_token")

    monkeypatch.setattr(document_ir.pdfplumber, "open", broken_open)

    with pytest.raises(DocumentIRExtractionError) as exc_info:
        parse_document_ir(pdf_bytes)

    assert str(exc_info.value) == "Document IR extraction failed"
    assert "leaked_token" not in str(exc_info.value)


def test_minimal_valid_text_pdf_returns_ir_payload() -> None:
    pdf_bytes = _make_text_pdf(
        "This is a valid document text content for testing parser boundary."
    )
    parsed = parse_document_ir(pdf_bytes)

    assert isinstance(parsed, ParsedDocumentIR)
    assert parsed.validation.has_text is True
    assert parsed.validation.page_count == 1
    assert parsed.validation.size_bytes == len(pdf_bytes)

    content = parsed.content
    assert content["schema_version"] == SCHEMA_VERSION
    assert SCHEMA_VERSION == 1
    assert PARSER_VERSION == "pypdf-pdfplumber-v1"

    assert content["source"] == {
        "sha256": parsed.validation.sha256,
        "size_bytes": parsed.validation.size_bytes,
        "page_count": 1,
    }
    assert len(content["pages"]) == 1
    page = content["pages"][0]
    assert page["number"] == 1
    assert page["width"] == 612.0
    assert page["height"] == 792.0
    assert page["text"] == ""
    assert page["headings"] == []
    assert page["paragraphs"] == []
    assert page["tables"] == []

    assert content["sections"] == []
    assert content["paragraphs"] == []
    assert content["tables"] == []
