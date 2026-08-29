import zlib
from io import BytesIO

import pytest
from pypdf import PdfWriter
from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject

from app.services.pdf_validation import PDFValidationError, validate_pdf


def _make_pdf_with_stream(
    stream_bytes_list: list[bytes], *, compress: bool = True
) -> bytes:
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
    for stream_bytes in stream_bytes_list:
        page = writer.add_blank_page(width=72, height=72)
        page[NameObject("/Resources")] = resources
        stream_obj = DecodedStreamObject()
        if compress:
            stream_obj.set_data(zlib.compress(stream_bytes))
            stream_obj[NameObject("/Filter")] = NameObject("/FlateDecode")
        else:
            stream_obj.set_data(stream_bytes)
        page[NameObject("/Contents")] = stream_obj
    out = BytesIO()
    writer.write(out)
    return out.getvalue()


def test_valid_pdf_passes_validation() -> None:
    # PDF with simple text content
    pdf_bytes = _make_pdf_with_stream([b"BT /F1 12 Tf 10 10 Td (Hello World) Tj ET"])
    result = validate_pdf(pdf_bytes, max_size_bytes=5000)
    assert result.page_count == 1
    assert result.has_text is True


def test_pdf_decoded_too_large_raises_error_before_extract_text() -> None:
    # 2500 bytes decoded content, compressed to ~600 bytes. File limit is 1500 bytes.
    # Raw file size is < 1500 bytes, but decoded stream size > 1500 bytes.
    large_stream = b"BT /F1 12 Tf 10 10 Td (" + b"A" * 2500 + b") Tj ET"
    pdf_bytes = _make_pdf_with_stream([large_stream], compress=True)
    assert len(pdf_bytes) < 1500

    with pytest.raises(PDFValidationError) as exc_info:
        validate_pdf(pdf_bytes, max_size_bytes=1500)

    assert exc_info.value.code == "PDF_DECODED_TOO_LARGE"


def test_decoded_limit_is_cumulative_across_pages() -> None:
    # Each page is below the limit, but total decoded content exceeds it.
    p1 = b"BT /F1 12 Tf 10 10 Td (Page 1 " + b"A" * 750 + b") Tj ET"
    p2 = b"BT /F1 12 Tf 10 10 Td (Page 2 " + b"B" * 750 + b") Tj ET"
    pdf_bytes = _make_pdf_with_stream([p1, p2], compress=True)
    assert len(pdf_bytes) < 1000

    with pytest.raises(PDFValidationError) as exc_info:
        validate_pdf(pdf_bytes, max_size_bytes=1000)

    assert exc_info.value.code == "PDF_DECODED_TOO_LARGE"


def test_decoded_limit_fails_if_any_single_page_exceeds() -> None:
    # Page 1 decoded is ~40 bytes (<= 1000), Page 2 decoded is 2500 bytes (> 1000)
    # Compressed file size is < 1000 bytes.
    p1 = b"BT /F1 12 Tf 10 10 Td (Page 1) Tj ET"
    p2 = b"BT /F1 12 Tf 10 10 Td (" + b"X" * 2500 + b") Tj ET"
    pdf_bytes = _make_pdf_with_stream([p1, p2], compress=True)
    assert len(pdf_bytes) < 1000

    with pytest.raises(PDFValidationError) as exc_info:
        validate_pdf(pdf_bytes, max_size_bytes=1000)

    assert exc_info.value.code == "PDF_DECODED_TOO_LARGE"
