from io import BytesIO
from threading import Event, Thread
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
    return _make_operations_pdf(
        *[
            [f"BT /F1 12 Tf 72 700 Td ({text}) Tj ET"]
            for text in page_texts
        ]
    )


def _make_operations_pdf(*page_operations: list[str]) -> bytes:
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
    for operations in page_operations:
        page = writer.add_blank_page(width=612, height=792)
        page[NameObject("/Resources")] = resources
        content = DecodedStreamObject()
        content.set_data("\n".join(operations).encode("ascii"))
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


def test_document_without_headings_has_root_paragraphs() -> None:
    parsed = parse_document_ir(
        _make_operations_pdf(
            [
                "BT /F1 12 Tf 72 700 Td (Ordinary paragraph line one.) Tj ET",
                "BT /F1 12 Tf 72 684 Td (Ordinary paragraph line two.) Tj ET",
            ]
        )
    )
    assert parsed.content["sections"] == []
    assert [paragraph["section_id"] for paragraph in parsed.content["paragraphs"]] == [
        None
    ]
    assert parsed.content["paragraphs"][0]["text"] == (
        "Ordinary paragraph line one. Ordinary paragraph line two."
    )
    assert parsed.content["pages"][0]["text"] == (
        "Ordinary paragraph line one.\nOrdinary paragraph line two."
    )


def test_nested_numbered_headings_build_parent_chain() -> None:
    parsed = parse_document_ir(
        _make_operations_pdf(
            [
                "BT /F1 18 Tf 72 730 Td (1 Introduction) Tj ET",
                "BT /F1 12 Tf 72 710 Td (Root body text long enough.) Tj ET",
                "BT /F1 16 Tf 72 680 Td (1.1 Scope) Tj ET",
                "BT /F1 14 Tf 72 650 Td (1.1.1 Inputs) Tj ET",
                "BT /F1 13 Tf 72 620 Td (1.1.1.1 Validation) Tj ET",
                "BT /F1 12 Tf 72 590 Td (Nested body text long enough.) Tj ET",
            ]
        )
    )
    sections = parsed.content["sections"]
    assert [section["level"] for section in sections] == [1, 2, 3, 4]
    assert [section["parent_id"] for section in sections] == [
        None,
        sections[0]["id"],
        sections[1]["id"],
        sections[2]["id"],
    ]
    assert parsed.content["pages"][0]["headings"] == [
        section["id"] for section in sections
    ]


def test_skipped_numbered_heading_attaches_to_closest_lower_parent() -> None:
    parsed = parse_document_ir(
        _make_operations_pdf(
            [
                "BT /F1 18 Tf 72 730 Td (1 Introduction) Tj ET",
                "BT /F1 16 Tf 72 700 Td (1.1.1 Deep topic) Tj ET",
            ]
        )
    )
    sections = parsed.content["sections"]
    assert [section["level"] for section in sections] == [1, 3]
    assert sections[1]["parent_id"] == sections[0]["id"]


def test_blank_page_remains_after_text_page() -> None:
    parsed = parse_document_ir(
        _make_operations_pdf(
            ["BT /F1 12 Tf 72 700 Td (A body line with enough text.) Tj ET"],
            [],
        )
    )
    pages = parsed.content["pages"]
    assert len(pages) == 2
    assert pages[1]["text"] == ""
    assert pages[1]["headings"] == []
    assert pages[1]["paragraphs"] == []
    assert pages[1]["tables"] == []


def test_short_large_font_heading_detected_but_sentence_not() -> None:
    parsed = parse_document_ir(
        _make_operations_pdf(
            [
                "BT /F1 18 Tf 72 730 Td (Short heading) Tj ET",
                "BT /F1 12 Tf 72 700 Td (Ordinary Capitalized sentence.) Tj ET",
                "BT /F1 12 Tf 72 680 Td (Body text continues with enough words.) Tj ET",
            ]
        )
    )
    assert [section["text"] for section in parsed.content["sections"]] == [
        "Short heading"
    ]
    assert [paragraph["text"] for paragraph in parsed.content["paragraphs"]] == [
        "Ordinary Capitalized sentence. Body text continues with enough words."
    ]


def test_coordinates_are_finite_ordered_and_inside_page() -> None:
    parsed = parse_document_ir(
        _make_operations_pdf(
            [
                "BT /F1 18 Tf 72 730 Td (1 Heading) Tj ET",
                "BT /F1 12 Tf 72 700 Td (Body text with enough words.) Tj ET",
            ]
        )
    )
    page = parsed.content["pages"][0]
    for item in [*parsed.content["sections"], *parsed.content["paragraphs"]]:
        bbox = item["bbox"]
        assert all(isinstance(value, float) for value in bbox.values())
        assert all(
            value == value and abs(value) != float("inf")
            for value in bbox.values()
        )
        assert 0 <= bbox["x0"] <= bbox["x1"] <= page["width"]
        assert 0 <= bbox["top"] <= bbox["bottom"] <= page["height"]


def test_low_node_budget_fails_before_later_layout_objects() -> None:
    parsed_pdf = _make_operations_pdf(
        [
            "BT /F1 12 Tf 72 700 Td (First positioned text run.) Tj ET",
            "BT /F1 12 Tf 72 680 Td (Second positioned text run.) Tj ET",
        ]
    )
    with pytest.raises(PDFValidationError) as exc_info:
        parse_document_ir(parsed_pdf, max_nodes=2)
    assert exc_info.value.code == "PDF_STRUCTURE_LIMIT"


def test_many_typography_sizes_have_deterministic_levels() -> None:
    operations = [
        f"BT /F1 {size} Tf 72 {750 - index * 20} Td (Heading {size}) Tj ET"
        for index, size in enumerate((24, 23, 22, 21, 20))
    ]
    operations.append(
        "BT /F1 12 Tf 72 620 Td (Body sentence ending in a period.) Tj ET"
    )
    parsed = parse_document_ir(_make_operations_pdf(operations))
    assert [section["level"] for section in parsed.content["sections"]] == [
        1,
        2,
        3,
        4,
        5,
    ]


def test_typography_baseline_ignores_many_large_headings() -> None:
    operations = [
        f"BT /F1 18 Tf 72 {750 - index * 20} Td (Large heading {index}) Tj ET"
        for index in range(3)
    ]
    operations.append(
        "BT /F1 12 Tf 72 680 Td (Ordinary body sentence ending in a period.) Tj ET"
    )
    parsed = parse_document_ir(_make_operations_pdf(operations))
    assert len(parsed.content["sections"]) == 3
    assert parsed.content["paragraphs"][0]["text"] == (
        "Ordinary body sentence ending in a period."
    )


def test_ordered_list_sentences_are_not_numbered_headings() -> None:
    parsed = parse_document_ir(
        _make_operations_pdf(
            [
                "BT /F1 12 Tf 72 700 Td (1. First item.) Tj ET",
                "BT /F1 12 Tf 72 680 Td (2. Second item.) Tj ET",
            ]
        )
    )
    assert parsed.content["sections"] == []
    assert parsed.content["paragraphs"][0]["text"] == (
        "1. First item. 2. Second item."
    )


def test_top_level_unpunctuated_ordered_list_is_not_a_heading() -> None:
    parsed = parse_document_ir(
        _make_operations_pdf(
            [
                "BT /F1 12 Tf 72 700 Td (1 First item) Tj ET",
                "BT /F1 12 Tf 72 680 Td (2 Second item) Tj ET",
            ]
        )
    )
    assert parsed.content["sections"] == []
    assert (
        parsed.content["paragraphs"][0]["text"] == "1 First item 2 Second item"
    )


def test_layout_hook_stops_and_restores_aggregator_method(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[object] = []

    def record(self: object) -> None:
        calls.append(self)

    monkeypatch.setattr(
        document_ir.PDFPageAggregatorWithMarkedContent,
        "tag_cur_item",
        record,
    )
    budget = _NodeBudget(limit=1)
    with pytest.raises(PDFValidationError) as exc_info:
        with document_ir._bounded_layout_hook(budget):
            document_ir.PDFPageAggregatorWithMarkedContent.tag_cur_item(object())
            document_ir.PDFPageAggregatorWithMarkedContent.tag_cur_item(object())
    assert exc_info.value.code == "PDF_STRUCTURE_LIMIT"
    assert len(calls) == 1
    assert (
        document_ir.PDFPageAggregatorWithMarkedContent.tag_cur_item is record
    )

    with document_ir._bounded_layout_hook(_NodeBudget(limit=1)):
        document_ir.PDFPageAggregatorWithMarkedContent.tag_cur_item(object())
    assert document_ir.PDFPageAggregatorWithMarkedContent.tag_cur_item is record


def test_layout_hook_budgets_do_not_cross_contaminate_threads(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        document_ir.PDFPageAggregatorWithMarkedContent,
        "tag_cur_item",
        lambda _self: None,
    )
    budgets = [_NodeBudget(limit=1), _NodeBudget(limit=1)]
    errors: list[Exception] = []

    def consume_one(budget: _NodeBudget) -> None:
        try:
            with document_ir._bounded_layout_hook(budget):
                document_ir.PDFPageAggregatorWithMarkedContent.tag_cur_item(
                    object()
                )
        except Exception as exc:  # pragma: no cover - assertion captures
            errors.append(exc)

    threads = [Thread(target=consume_one, args=(budget,)) for budget in budgets]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=2)
    assert errors == []
    assert [budget.used for budget in budgets] == [1, 1]


def test_layout_hook_is_context_local_for_unrelated_threads(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[object] = []
    monkeypatch.setattr(
        document_ir.PDFPageAggregatorWithMarkedContent,
        "tag_cur_item",
        lambda self: calls.append(self),
    )
    budget = _NodeBudget(limit=1)
    hook_ready = Event()
    external_done = Event()
    errors: list[Exception] = []

    def parser_thread() -> None:
        try:
            with document_ir._bounded_layout_hook(budget):
                hook_ready.set()
                assert external_done.wait(timeout=2)
                document_ir.PDFPageAggregatorWithMarkedContent.tag_cur_item(
                    object()
                )
        except Exception as exc:  # pragma: no cover - assertion captures
            errors.append(exc)

    def unrelated_thread() -> None:
        try:
            assert hook_ready.wait(timeout=2)
            document_ir.PDFPageAggregatorWithMarkedContent.tag_cur_item(object())
            external_done.set()
        except Exception as exc:  # pragma: no cover - assertion captures
            errors.append(exc)

    parser = Thread(target=parser_thread)
    unrelated = Thread(target=unrelated_thread)
    parser.start()
    unrelated.start()
    parser.join(timeout=2)
    unrelated.join(timeout=2)
    assert errors == []
    assert budget.used == 1
    assert len(calls) == 2




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
    assert page["text"] == (
        "This is a valid document text content for testing parser boundary."
    )
    assert page["headings"] == []
    assert len(page["paragraphs"]) == 1
    assert content["sections"] == []
    assert len(content["paragraphs"]) == 1
    assert content["tables"] == []
