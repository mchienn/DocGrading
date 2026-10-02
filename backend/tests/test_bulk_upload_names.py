from __future__ import annotations

import pytest

from scripts.bulk_upload import repair_mojibake, student_name_from_filename


@pytest.mark.parametrize(
    ("stem", "expected"),
    [
        # Names garbled by a CP437 zip extraction are repaired.
        ("co╠éngtra╠é╠Çnva╠ån_3904_486321_[Nho╠üm13] [LoFTR]", "côngtrầnvăn"),
        ("─æo╠é╠Çngnguye╠é╠ânhu╠¢╠âu_4069_486313_[4][SoccerRAG]", "đồngnguyễnhữu"),
        # Already-correct names are left alone.
        ("anhnguyễnviệt_923_486323_Nhóm-7_One-pixel-attack", "anhnguyễnviệt"),
        ("tuấnnguyễnminh_LATE_4043_487296_1_An Automated Evaluation", "tuấnnguyễnminh"),
        # Files that are not LMS exports keep their whole (repaired) name.
        ("[N10] - MiniRAG", "[N10] - MiniRAG"),
    ],
)
def test_student_name_from_filename(stem: str, expected: str) -> None:
    assert student_name_from_filename(stem) == expected


def test_repair_mojibake_keeps_plain_ascii() -> None:
    assert repair_mojibake("Team 6 - PaperQA") == "Team 6 - PaperQA"
