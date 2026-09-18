from __future__ import annotations

import pytest

from app.services.chat import Intent, classify_intent


@pytest.mark.parametrize(
    ("message", "expected"),
    [
        ("Tình hình báo cáo lớp thế nào?", Intent.SUMMARY),
        ("Tỷ lệ hoàn thành của đợt SRS tháng 9?", Intent.SUMMARY),
        ("tinh hinh lop the nao", Intent.SUMMARY),  # no diacritics
        ("Còn bao nhiêu bài chưa duyệt?", Intent.UNREVIEWED),
        ("Những bài nào đang lỗi?", Intent.ERRORS),
        ("Bao nhiêu sinh viên chưa nộp?", Intent.NOT_SUBMITTED),
        ("Sinh viên nào chưa nộp bài?", Intent.NOT_SUBMITTED),
        ("Hôm nay có yêu cầu xem lại nào mới không?", Intent.NEW_REVIEW_REQUESTS),
        ("Xin chào", Intent.GREETING),
        ("Bạn giúp được gì?", Intent.HELP),
        ("thời tiết hôm nay thế nào", Intent.UNKNOWN),
    ],
)
def test_classify_intent(message: str, expected: Intent) -> None:
    assert classify_intent(message) is expected


def test_not_submitted_not_confused_with_unreviewed() -> None:
    # "chưa nộp" must win over the broader "chưa duyệt" keyword family even
    # though both start with "chưa".
    message = "Bao nhiêu sinh viên chưa nộp bài tập?"
    assert classify_intent(message) is Intent.NOT_SUBMITTED


def test_classify_is_case_and_whitespace_insensitive() -> None:
    assert classify_intent("   CÒN BAO NHIÊU BÀI CHƯA DUYỆT?   ") is Intent.UNREVIEWED


def test_greeting_keyword_does_not_match_inside_other_words() -> None:
    # "nghỉ" strips diacritics to "nghi", which contains "hi" as a substring —
    # that must not be misread as the GREETING keyword "hi".
    message = "Sinh viên nghỉ học có tính là chưa nộp không?"
    assert classify_intent(message) is Intent.NOT_SUBMITTED