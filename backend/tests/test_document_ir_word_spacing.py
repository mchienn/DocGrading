"""Word spacing in Document IR (issue #47: glued words).

The PDFs are built here (no student data). Words are positioned one by one
with no space character between them, as justified Word/LaTeX output does.
The 2.6 pt gap at 11 pt mirrors the anchor dataset: in the most glued
reports, the gaps pdfplumber's default ``x_tolerance=3`` merged were
2.3-3.0 pt (median 2.7 pt) at 10-11 pt.
"""

from __future__ import annotations

from io import BytesIO

import pytest
from pypdf import PdfWriter
from pypdf.generic import (
    ArrayObject,
    DecodedStreamObject,
    DictionaryObject,
    NameObject,
    NumberObject,
)

from app.core.config import Settings
from app.services.document_ir import PARSER_VERSION, parse_document_ir
from tests.test_t010_document_ir_parser import _make_ruled_table_page

GLYPH_WIDTH = 500  # every code: 0.5 em, so positions are easy to compute
TIGHT_GAP = 2.6


class _Font:
    """A non-embedded simple font with explicit ``/Widths`` (not one of the
    standard 14, whose built-in metrics would override them) whose codes
    >= 128 name Unicode glyphs (``/uniXXXX``), so the text layer carries
    Vietnamese letters and every glyph is exactly 0.5 em wide."""

    def __init__(self, *texts: str) -> None:
        extra = sorted({ch for text in texts for ch in text if ord(ch) > 126})
        self.codes = {ch: 128 + i for i, ch in enumerate(extra)}
        assert len(self.codes) <= 128

    def hex(self, text: str) -> str:
        return "".join(f"{self.codes.get(ch, ord(ch)):02X}" for ch in text)

    def dictionary(self) -> DictionaryObject:
        differences = ArrayObject([NumberObject(128)])
        differences.extend(
            NameObject(f"/uni{ord(ch):04X}")
            for ch, _code in sorted(self.codes.items(), key=lambda kv: kv[1])
        )
        return DictionaryObject(
            {
                NameObject("/Type"): NameObject("/Font"),
                NameObject("/Subtype"): NameObject("/Type1"),
                NameObject("/BaseFont"): NameObject("/DocGradingTestSans"),
                NameObject("/FirstChar"): NumberObject(32),
                NameObject("/LastChar"): NumberObject(255),
                NameObject("/Widths"): ArrayObject(
                    [NumberObject(GLYPH_WIDTH)] * (255 - 32 + 1)
                ),
                NameObject("/Encoding"): DictionaryObject(
                    {
                        NameObject("/Type"): NameObject("/Encoding"),
                        NameObject("/BaseEncoding"): NameObject("/WinAnsiEncoding"),
                        NameObject("/Differences"): differences,
                    }
                ),
            }
        )


def _pdf(font: _Font, operations: list[str]) -> bytes:
    writer = PdfWriter()
    page = writer.add_blank_page(width=612, height=792)
    page[NameObject("/Resources")] = DictionaryObject(
        {NameObject("/Font"): DictionaryObject({NameObject("/F1"): font.dictionary()})}
    )
    content = DecodedStreamObject()
    content.set_data("\n".join(operations).encode("ascii"))
    page[NameObject("/Contents")] = writer._add_object(content)
    out = BytesIO()
    writer.write(out)
    return out.getvalue()


def _positioned_words(
    font: _Font, sentence: str, *, y: float, size: float = 11, gap: float
) -> list[str]:
    """One text object per word, *gap* points apart, no space characters."""
    ops, x = [], 72.0
    for word in sentence.split():
        ops.append(f"BT /F1 {size} Tf {x:.2f} {y} Td <{font.hex(word)}> Tj ET")
        x += len(word) * GLYPH_WIDTH / 1000 * size + gap
    return ops


VI = "Hệ thống trích xuất các quy trình làm việc từ đoạn hội thoại của người dùng."
EN = "The proposed method helps the chatbot identify user intent more accurately."


def _paragraph_texts(data: bytes, **kwargs) -> list[str]:
    return [p["text"] for p in parse_document_ir(data, **kwargs).content["paragraphs"]]


def test_word_x_tolerance_default() -> None:
    settings = Settings(postgres_db="db", postgres_user="u", postgres_password="p")
    assert settings.pdf_word_x_tolerance == 1.5
    with pytest.raises(ValueError):
        Settings(
            postgres_db="db",
            postgres_user="u",
            postgres_password="p",
            pdf_word_x_tolerance=0,
        )


def test_parser_version_is_bumped_for_the_new_word_spacing() -> None:
    # Summary cache keys include DocumentIR.parser_version
    # (rag.summary_source_hash), so old summaries stop matching.
    assert PARSER_VERSION == "pypdf-pdfplumber-v6"


@pytest.mark.parametrize("sentence", [VI, EN], ids=["vietnamese", "english"])
def test_tightly_spaced_words_keep_their_spaces(sentence: str) -> None:
    font = _Font(sentence)
    data = _pdf(font, _positioned_words(font, sentence, y=700, gap=TIGHT_GAP))
    assert _paragraph_texts(data) == [sentence]


def test_old_tolerance_reproduces_the_glued_words() -> None:
    font = _Font(VI)
    data = _pdf(font, _positioned_words(font, VI, y=700, gap=TIGHT_GAP))
    [glued] = _paragraph_texts(data, word_x_tolerance=3.0)
    assert " " not in glued and glued == VI.replace(" ", "")


def test_text_with_real_space_characters_is_unchanged() -> None:
    font = _Font(VI)
    data = _pdf(font, [f"BT /F1 11 Tf 72 700 Td <{font.hex(VI)}> Tj ET"])
    assert _paragraph_texts(data) == [VI]
    assert _paragraph_texts(data, word_x_tolerance=3.0) == [VI]


def test_letter_spaced_heading_is_not_split_into_letters() -> None:
    heading = "TÓM TẮT ĐỒ ÁN"
    body = "Báo cáo trình bày hệ thống hỏi đáp tài liệu cho giảng viên."
    font = _Font(heading, body)
    # 1 pt tracking between letters (Tc), real spaces between words.
    data = _pdf(
        font,
        [
            f"BT /F1 18 Tf 1 Tc 72 740 Td <{font.hex(heading)}> Tj ET",
            f"BT /F1 11 Tf 0 Tc 72 700 Td <{font.hex(body)}> Tj ET",
        ],
    )
    content = parse_document_ir(data).content
    texts = [s["text"] for s in content["sections"]] + [
        p["text"] for p in content["paragraphs"]
    ]
    assert heading in texts, texts
    assert not any("T Ó M" in t for t in texts)


def test_tables_are_detected_the_same_with_either_tolerance() -> None:
    font = _Font()
    operations = _make_ruled_table_page(
        [["ID", "Name"], ["UC01", "Login"]],
        y_lines=[500, 540, 580],
    )
    data = _pdf(font, operations)
    new = parse_document_ir(data).content["tables"]
    old = parse_document_ir(data, word_x_tolerance=3.0).content["tables"]
    assert len(new) == len(old) == 1
    assert new == old
