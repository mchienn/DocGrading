from io import BytesIO

import pytest
from pypdf import PdfWriter
from pypdf.generic import (
    ArrayObject,
    DecodedStreamObject,
    DictionaryObject,
    EncodedStreamObject,
    NameObject,
    NumberObject,
)

from app.services.pdf_validation import PDFValidationError, validate_pdf


def _image_xobject() -> DecodedStreamObject:
    image = DecodedStreamObject()
    image.set_data(b"\x00")
    image.update(
        {
            NameObject("/Type"): NameObject("/XObject"),
            NameObject("/Subtype"): NameObject("/Image"),
            NameObject("/Width"): NumberObject(1),
            NameObject("/Height"): NumberObject(1),
            NameObject("/ColorSpace"): NameObject("/DeviceGray"),
            NameObject("/BitsPerComponent"): NumberObject(8),
        }
    )
    return image


def _font() -> DictionaryObject:
    return DictionaryObject(
        {
            NameObject("/Type"): NameObject("/Font"),
            NameObject("/Subtype"): NameObject("/Type1"),
            NameObject("/BaseFont"): NameObject("/Helvetica"),
        }
    )


def _add_page(
    writer: PdfWriter,
    *,
    image_rect: tuple[float, float, float, float] | None = None,
    text: str = "",
    image_in_form: bool = False,
    page_size: tuple[float, float] = (100, 100),
    pre_image_operations: str = "",
) -> None:
    page_width, page_height = page_size
    page = writer.add_blank_page(width=page_width, height=page_height)
    xobjects = DictionaryObject()
    resources = DictionaryObject(
        {
            NameObject("/Font"): DictionaryObject({NameObject("/F1"): _font()}),
            NameObject("/XObject"): xobjects,
        }
    )
    operations: list[str] = []

    if image_rect is not None:
        x, y, width, height = image_rect
        image = _image_xobject()
        target_name = "/Im0"
        if image_in_form:
            form = DecodedStreamObject()
            form.set_data(b"q 1 0 0 1 0 0 cm /Im0 Do Q")
            form.update(
                {
                    NameObject("/Type"): NameObject("/XObject"),
                    NameObject("/Subtype"): NameObject("/Form"),
                    NameObject("/BBox"): ArrayObject(
                        [
                            NumberObject(0),
                            NumberObject(0),
                            NumberObject(1),
                            NumberObject(1),
                        ]
                    ),
                    NameObject("/Matrix"): ArrayObject(
                        [
                            NumberObject(1),
                            NumberObject(0),
                            NumberObject(0),
                            NumberObject(1),
                            NumberObject(0),
                            NumberObject(0),
                        ]
                    ),
                    NameObject("/Resources"): DictionaryObject(
                        {
                            NameObject("/XObject"): DictionaryObject(
                                {NameObject("/Im0"): image}
                            )
                        }
                    ),
                }
            )
            xobjects[NameObject("/Fm0")] = form
            target_name = "/Fm0"
        else:
            xobjects[NameObject("/Im0")] = image
        if pre_image_operations:
            operations.append(pre_image_operations)
        operations.append(f"q {width} 0 0 {height} {x} {y} cm {target_name} Do Q")

    if text:
        operations.append(f"BT /F1 10 Tf 1 {max(0, page_height - 5)} Td ({text}) Tj ET")

    content = DecodedStreamObject()
    content.set_data("\n".join(operations).encode("ascii"))
    page[NameObject("/Resources")] = resources
    page[NameObject("/Contents")] = content


def _pdf_bytes(*pages: dict[str, object]) -> bytes:
    writer = PdfWriter()
    for page in pages:
        _add_page(writer, **page)
    output = BytesIO()
    writer.write(output)
    return output.getvalue()


def test_exact_80_percent_image_with_29_useful_characters_is_rejected() -> None:
    data = _pdf_bytes(
        {
            "image_rect": (0, 0, 80, 100),
            "text": "A" * 29,
        }
    )

    with pytest.raises(PDFValidationError) as exc_info:
        validate_pdf(data)

    assert exc_info.value.code == "PDF_SCAN_ONLY"


def test_large_image_with_30_useful_characters_is_accepted() -> None:
    data = _pdf_bytes(
        {
            "image_rect": (5, 5, 90, 90),
            "text": "A" * 30,
        }
    )

    assert validate_pdf(data).has_text is True


def test_image_below_80_percent_with_short_text_is_accepted() -> None:
    data = _pdf_bytes(
        {
            "image_rect": (0, 0, 79, 100),
            "text": "A",
        }
    )

    assert validate_pdf(data).has_text is True


def test_page_clip_reduces_visible_image_coverage() -> None:
    data = _pdf_bytes(
        {
            "image_rect": (0, 0, 100, 100),
            "pre_image_operations": "0 0 10 100 re W n",
            "text": "A",
        }
    )

    assert validate_pdf(data).has_text is True


def test_self_overlapping_even_odd_clip_does_not_inflate_coverage() -> None:
    doubled_rectangle = (
        "0 0 m 100 0 l 100 100 l 0 100 l 0 0 l " "100 0 l 100 100 l 0 100 l 0 0 l W* n"
    )
    data = _pdf_bytes(
        {
            "image_rect": (0, 0, 100, 100),
            "pre_image_operations": doubled_rectangle,
            "text": "A",
        }
    )

    assert validate_pdf(data).has_text is True


def test_graphics_restore_restores_previous_clip() -> None:
    data = _pdf_bytes(
        {
            "image_rect": (0, 0, 100, 100),
            "pre_image_operations": "q 0 0 10 100 re W n Q",
            "text": "A",
        }
    )

    with pytest.raises(PDFValidationError) as exc_info:
        validate_pdf(data)

    assert exc_info.value.code == "PDF_SCAN_ONLY"


def test_true_blank_page_does_not_reject_text_native_document() -> None:
    data = _pdf_bytes(
        {"text": "Text native content has enough useful characters."},
        {},
    )

    assert validate_pdf(data).page_count == 2


def test_large_image_inside_transformed_form_is_rejected() -> None:
    data = _pdf_bytes(
        {
            "image_rect": (5, 5, 90, 90),
            "text": "A",
            "image_in_form": True,
        }
    )

    with pytest.raises(PDFValidationError) as exc_info:
        validate_pdf(data)

    assert exc_info.value.code == "PDF_SCAN_ONLY"


def test_fractional_exact_80_percent_boundary_is_rejected() -> None:
    data = _pdf_bytes(
        {
            "page_size": (3, 1),
            "image_rect": (0, 0, 2.4, 1),
            "text": "A" * 29,
        }
    )

    with pytest.raises(PDFValidationError) as exc_info:
        validate_pdf(data)

    assert exc_info.value.code == "PDF_SCAN_ONLY"


def test_unmatched_graphics_restore_resets_to_initial_matrix() -> None:
    data = _pdf_bytes(
        {
            "image_rect": (0, 0, 40, 100),
            "pre_image_operations": "2 0 0 2 0 0 cm Q",
            "text": "A",
        }
    )

    assert validate_pdf(data).has_text is True


def test_nested_form_decode_is_bounded_before_geometry_parse() -> None:
    writer = PdfWriter()
    page = writer.add_blank_page(width=100, height=100)
    form = EncodedStreamObject()
    form._data = b"z" * 1000 + b"~>"
    form.update(
        {
            NameObject("/Type"): NameObject("/XObject"),
            NameObject("/Subtype"): NameObject("/Form"),
            NameObject("/Filter"): NameObject("/ASCII85Decode"),
            NameObject("/BBox"): ArrayObject(
                [
                    NumberObject(0),
                    NumberObject(0),
                    NumberObject(1),
                    NumberObject(1),
                ]
            ),
            NameObject("/Resources"): DictionaryObject(),
        }
    )
    page[NameObject("/Resources")] = DictionaryObject(
        {
            NameObject("/Font"): DictionaryObject({NameObject("/F1"): _font()}),
            NameObject("/XObject"): DictionaryObject({NameObject("/Fm0"): form}),
        }
    )
    content = DecodedStreamObject()
    content.set_data(
        b"q 1 0 0 1 0 0 cm /Fm0 Do Q "
        b"BT /F1 10 Tf 1 95 Td (AAAAAAAAAAAAAAAAAAAAAAAAAAAAAA) Tj ET"
    )
    page[NameObject("/Contents")] = content
    output = BytesIO()
    writer.write(output)
    data = output.getvalue()
    max_size_bytes = len(data) + 500

    with pytest.raises(PDFValidationError) as exc_info:
        validate_pdf(data, max_size_bytes=max_size_bytes)

    assert exc_info.value.code == "PDF_DECODED_TOO_LARGE"
