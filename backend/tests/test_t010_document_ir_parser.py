import math
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
        *[[f"BT /F1 12 Tf 72 700 Td ({text}) Tj ET"] for text in page_texts]
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


def _make_ruled_table_page(
    rows: list[list[str]],
    *,
    y_lines: list[float],
    x_lines: list[float] | None = None,
    merge_last_row: bool = False,
    merge_first_row: bool = False,
) -> list[str]:
    x_lines = x_lines or [72, 300, 500]
    operations = [f"{x_lines[0]} {y} m {x_lines[-1]} {y} l S" for y in y_lines]

    def vertical_operation(x: float) -> str:
        inner = x not in (x_lines[0], x_lines[-1])
        start = y_lines[1] if merge_last_row and inner else y_lines[0]
        end = y_lines[1] if merge_first_row and inner else y_lines[-1]
        return f"{x} {start} m {x} {end} l S"

    operations.extend(vertical_operation(x) for x in x_lines)
    for row, (low, high) in zip(
        rows,
        reversed(list(zip(y_lines, y_lines[1:], strict=False))),
        strict=True,
    ):
        for text, x in zip(row, x_lines[:-1], strict=True):
            operations.append(
                f"BT /F1 11 Tf {x + 8} {(low + high) / 2 - 4} Td " f"({text}) Tj ET"
            )
    return operations


def _make_two_page_table_pdf(
    *,
    second_x_lines: list[float] | None = None,
) -> bytes:
    return _make_operations_pdf(
        _make_ruled_table_page(
            [["Name", "Value"], ["Alice", "1"]],
            y_lines=[92, 142, 192],
        ),
        _make_ruled_table_page(
            [["Name", "Value"], ["Bob", "2"]],
            y_lines=[592, 642, 692],
            x_lines=second_x_lines,
        ),
    )


def test_real_pdf_tables_merge_across_consecutive_pages() -> None:
    parsed = parse_document_ir(_make_two_page_table_pdf())

    assert len(parsed.content["tables"]) == 1
    table = parsed.content["tables"][0]
    assert table["id"] == "table-1"
    assert table["page_start"] == 1
    assert table["page_end"] == 2
    assert table["regions"] == [
        {
            "page_number": 1,
            "bbox": {"x0": 72.0, "top": 600.0, "x1": 500.0, "bottom": 700.0},
        },
        {
            "page_number": 2,
            "bbox": {"x0": 72.0, "top": 100.0, "x1": 500.0, "bottom": 200.0},
        },
    ]
    assert [[cell["text"] for cell in row["cells"]] for row in table["rows"]] == [
        ["Name", "Value"],
        ["Alice", "1"],
        ["Bob", "2"],
    ]
    assert [row["page_number"] for row in table["rows"]] == [1, 1, 2]
    assert parsed.content["pages"][0]["tables"] == ["table-1"]
    assert parsed.content["pages"][1]["tables"] == ["table-1"]


def test_real_pdf_table_cells_keep_geometry_and_missing_slots() -> None:
    parsed = parse_document_ir(
        _make_operations_pdf(
            _make_ruled_table_page(
                [["Name", "Value"], ["Alice", ""]],
                y_lines=[92, 142, 192],
                merge_last_row=True,
            )
        )
    )
    page = parsed.content["pages"][0]
    rows = parsed.content["tables"][0]["rows"]
    assert rows[1]["cells"][1] is None
    for row in rows:
        assert row["page_number"] == 1
        row_bbox = row["bbox"]
        assert 0 <= row_bbox["x0"] <= row_bbox["x1"] <= page["width"]
        assert 0 <= row_bbox["top"] <= row_bbox["bottom"] <= page["height"]
        for cell in row["cells"]:
            if cell is None:
                continue
            assert cell["text"]
            assert cell["page_number"] == 1
            bbox = cell["bbox"]
            assert all(math.isfinite(value) for value in bbox.values())
            assert 0 <= bbox["x0"] <= bbox["x1"] <= page["width"]
            assert 0 <= bbox["top"] <= bbox["bottom"] <= page["height"]


def test_incompatible_table_boundaries_do_not_merge() -> None:
    parsed = parse_document_ir(_make_two_page_table_pdf(second_x_lines=[72, 280, 500]))

    assert [table["id"] for table in parsed.content["tables"]] == [
        "table-1",
        "table-2",
    ]
    assert parsed.content["pages"][0]["tables"] == ["table-1"]
    assert parsed.content["pages"][1]["tables"] == ["table-2"]


def test_present_empty_cell_keeps_cell_object() -> None:
    parsed = parse_document_ir(
        _make_operations_pdf(
            _make_ruled_table_page(
                [["Name", "Value"], ["Alice", ""]],
                y_lines=[92, 142, 192],
            )
        )
    )

    cell = parsed.content["tables"][0]["rows"][1]["cells"][1]
    assert cell is not None
    assert cell["text"] == ""
    assert cell["page_number"] == 1
    assert cell["bbox"] == {
        "x0": 300.0,
        "top": 650.0,
        "x1": 500.0,
        "bottom": 700.0,
    }


def test_table_words_filtered_before_line_grouping() -> None:
    parsed = parse_document_ir(
        _make_operations_pdf(
            _make_ruled_table_page(
                [["Name", "Value"], ["Alice", "1"]],
                y_lines=[92, 142, 192],
            )
            + [
                "BT /F1 11 Tf 520 163 Td (Outside.) Tj ET",
                "BT /F1 12 Tf 72 400 Td (Body paragraph.) Tj ET",
            ]
        )
    )

    assert "Name" in parsed.content["pages"][0]["text"]
    assert any(
        paragraph["text"] == "Outside." for paragraph in parsed.content["paragraphs"]
    )
    assert all(
        "Name" not in item["text"] and "Alice" not in item["text"]
        for item in [
            *parsed.content["sections"],
            *parsed.content["paragraphs"],
        ]
    )


def test_table_budget_fails_before_find_tables(monkeypatch: pytest.MonkeyPatch) -> None:
    pdf_bytes = _make_operations_pdf(
        _make_ruled_table_page(
            [["Name", "Value"], ["Alice", "1"]],
            y_lines=[92, 142, 192],
        )
    )
    called = False

    def must_not_extract(_page: Any) -> list[Any]:
        nonlocal called
        called = True
        raise AssertionError("find_tables called after edge budget exhausted")

    monkeypatch.setattr(
        document_ir.pdfplumber.page.Page,
        "find_tables",
        must_not_extract,
    )
    with pytest.raises(PDFValidationError) as exc_info:
        parse_document_ir(pdf_bytes, max_nodes=10)
    assert exc_info.value.code == "PDF_STRUCTURE_LIMIT"
    assert called is False


def test_dense_table_source_objects_fail_before_edge_materialization(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    edge_accessed = False
    original_edges = document_ir.pdfplumber.page.Page.edges

    def track_edges(page: Any) -> list[Any]:
        nonlocal edge_accessed
        edge_accessed = True
        return original_edges.fget(page)

    monkeypatch.setattr(
        document_ir.pdfplumber.page.Page,
        "edges",
        property(track_edges),
    )
    operations = [f"72 {y} m 500 {y} l S" for y in range(20, 780, 2)]
    operations.append("BT /F1 12 Tf 72 10 Td (Dense source text.) Tj ET")
    called = False

    def must_not_find_tables(_page: Any) -> list[Any]:
        nonlocal called
        called = True
        raise AssertionError("find_tables called after dense preflight")

    monkeypatch.setattr(
        document_ir.pdfplumber.page.Page,
        "find_tables",
        must_not_find_tables,
    )
    with pytest.raises(PDFValidationError) as exc_info:
        parse_document_ir(_make_operations_pdf(operations))
    assert exc_info.value.code == "PDF_STRUCTURE_LIMIT"
    assert called is False
    assert edge_accessed is False


def test_later_row_geometry_prevents_table_merge() -> None:
    parsed = parse_document_ir(
        _make_operations_pdf(
            _make_ruled_table_page(
                [["A", "B", "C"], ["1", "2", "3"]],
                y_lines=[92, 142, 192],
                x_lines=[72, 250, 380, 500],
            ),
            _make_ruled_table_page(
                [["A", "B", "C"], ["4", "5", "6"]],
                y_lines=[592, 642, 692],
                x_lines=[72, 250, 380, 500],
                merge_last_row=True,
            ),
        )
    )

    assert len(parsed.content["tables"]) == 2


def test_table_merge_requires_first_row_slot_count_match() -> None:
    parsed = parse_document_ir(
        _make_operations_pdf(
            _make_ruled_table_page(
                [["Name", ""], ["Alice", "1"]],
                y_lines=[92, 142, 192],
                merge_first_row=True,
            ),
            _make_ruled_table_page(
                [["Name", "", ""], ["Bob", "2", "3"]],
                y_lines=[592, 642, 692],
                x_lines=[72, 250, 380, 500],
                merge_first_row=True,
            ),
        )
    )

    assert len(parsed.content["tables"]) == 2
    assert [table["id"] for table in parsed.content["tables"]] == [
        "table-1",
        "table-2",
    ]


def test_same_columns_with_different_row_counts_merge() -> None:
    parsed = parse_document_ir(
        _make_operations_pdf(
            _make_ruled_table_page(
                [["A", "B"], ["1", "2"], ["3", "4"]],
                y_lines=[92, 125, 158, 192],
            ),
            _make_ruled_table_page(
                [["A", "B"], ["5", "6"]],
                y_lines=[592, 642, 692],
            ),
        )
    )

    assert len(parsed.content["tables"]) == 1
    assert parsed.content["tables"][0]["page_end"] == 2


def test_parser_builds_layout_inside_bounded_hook(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[object] = []
    original = document_ir.PDFPageAggregatorWithMarkedContent.tag_cur_item

    def record(self: object) -> None:
        calls.append(self)
        original(self)

    monkeypatch.setattr(
        document_ir.PDFPageAggregatorWithMarkedContent,
        "tag_cur_item",
        record,
    )
    parse_document_ir(_make_text_pdf("Body text under layout hook."))
    assert calls


@pytest.mark.parametrize(
    ("table_bbox", "row_bbox", "cell_bbox"),
    [
        ((500, 600, 100, 700), (100, 600, 500, 700), (100, 600, 300, 650)),
        ((100, 600, 500, 700), (500, 600, 100, 650), (100, 600, 300, 650)),
        ((100, 600, 500, 700), (-1, 600, 500, 650), (100, 600, 300, 650)),
        ((100, 600, 500, 700), (100, 600, 500, 700), (500, 600, 100, 650)),
        ((100, 600, 500, 700), (100, 600, 500, 700), (100, 600, 700, 650)),
    ],
)
def test_malformed_table_row_or_cell_bbox_rejected(
    monkeypatch: pytest.MonkeyPatch,
    table_bbox: tuple[float, float, float, float],
    row_bbox: tuple[float, float, float, float],
    cell_bbox: tuple[float, float, float, float],
) -> None:
    class FakeRow:
        bbox = row_bbox
        cells = [cell_bbox, (300, 600, 500, 650)]

    class FakeTable:
        bbox = table_bbox
        rows = [FakeRow()]

        def extract(self) -> list[list[str]]:
            return [["Name", "Value"]]

    monkeypatch.setattr(
        document_ir.pdfplumber.page.Page,
        "find_tables",
        lambda _page: [FakeTable()],
    )
    with pytest.raises(PDFValidationError) as exc_info:
        parse_document_ir(
            _make_operations_pdf(
                _make_ruled_table_page(
                    [["Name", "Value"], ["Alice", "1"]],
                    y_lines=[92, 142, 192],
                )
            )
        )
    assert exc_info.value.code == "PDF_IR_MALFORMED"


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
            value == value and abs(value) != float("inf") for value in bbox.values()
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
    assert parsed.content["paragraphs"][0]["text"] == ("1. First item. 2. Second item.")


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
    assert parsed.content["paragraphs"][0]["text"] == "1 First item 2 Second item"


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
    with (
        pytest.raises(PDFValidationError) as exc_info,
        document_ir._bounded_layout_hook(budget),
    ):
        document_ir.PDFPageAggregatorWithMarkedContent.tag_cur_item(object())
        document_ir.PDFPageAggregatorWithMarkedContent.tag_cur_item(object())
    assert exc_info.value.code == "PDF_STRUCTURE_LIMIT"
    assert len(calls) == 1
    assert document_ir.PDFPageAggregatorWithMarkedContent.tag_cur_item is record

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
                document_ir.PDFPageAggregatorWithMarkedContent.tag_cur_item(object())
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
                document_ir.PDFPageAggregatorWithMarkedContent.tag_cur_item(object())
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
