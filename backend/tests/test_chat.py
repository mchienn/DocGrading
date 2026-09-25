from __future__ import annotations

import pytest

from app.services.chat import Intent, classify_intent, extract_search_topic


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
        ("Tìm đoạn nói về kiểm thử đơn vị", Intent.SEARCH_CONTENT),
        ("tim doan noi ve kien truc he thong", Intent.SEARCH_CONTENT),
        ("Đoạn nào nói về use case đăng nhập?", Intent.SEARCH_CONTENT),
        ("Tìm trong bài phần yêu cầu phi chức năng", Intent.SEARCH_CONTENT),
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

def test_search_content_wins_over_keywords_inside_topic() -> None:
    # The topic contains ERRORS ("xử lý lỗi") and SUMMARY ("tổng quan") phrases,
    # but the explicit "tìm đoạn" trigger must decide the intent.
    assert classify_intent("Tìm đoạn nói về xử lý lỗi") is Intent.SEARCH_CONTENT
    message = "tìm đoạn nói về tổng quan hệ thống"
    assert classify_intent(message) is Intent.SEARCH_CONTENT


@pytest.mark.parametrize(
    ("message", "topic"),
    [
        ("Tìm đoạn nói về kiểm thử đơn vị", "kiểm thử đơn vị"),
        ("Tìm đoạn nói về kiểm thử đơn vị trong bài này", "kiểm thử đơn vị"),
        ("tìm các đoạn liên quan đến LightRAG", "LightRAG"),
        ("Đoạn nào nói về use case đăng nhập?", "use case đăng nhập"),
        ("Tìm trong bài phần yêu cầu phi chức năng", "phần yêu cầu phi chức năng"),
        ("tìm đoạn", ""),
    ],
)
def test_extract_search_topic(message: str, topic: str) -> None:
    assert extract_search_topic(message) == topic
