from __future__ import annotations

from evaluation.scoring import (
    ChunkLike,
    agreement,
    cache_case_ok,
    cache_invalidated_ok,
    chunk_is_relevant,
    clarification_outcome,
    cohen_kappa,
    context_precision_at_k,
    context_recall,
    count_relevant_chunks,
    fold,
    fold_compact,
    glue_candidates,
    glue_group,
    glue_stats,
    is_rejection,
    mean,
    parse_errors,
    parse_new_review_requests,
    parse_not_submitted_active_students,
    parse_not_submitted_for_assignment,
    parse_summary_all_courses_rate,
    parse_unreviewed,
    percentile,
    precision_recall,
    rate,
    summary_structure_score,
    theoretical_max_precision,
)


def test_fold_strips_diacritics_and_lowercases() -> None:
    assert fold("Xác Thực Hai Lớp") == "xac thuc hai lop"


def test_parse_unreviewed_zero_case() -> None:
    reply = 'Lớp "CS101" hiện không còn bài nào chờ duyệt.'
    assert parse_unreviewed(reply) == 0


def test_parse_unreviewed_nonzero_case() -> None:
    reply = 'Còn 30 bài chưa duyệt ở lớp "CS101". Mở hàng đợi duyệt bài để xử lý tiếp.'
    assert parse_unreviewed(reply) == 30


def test_parse_unreviewed_no_match_returns_none() -> None:
    assert parse_unreviewed("Mình chưa hiểu câu hỏi này.") is None


def test_parse_errors_zero_and_nonzero() -> None:
    assert parse_errors('Không có bài nào đang lỗi ở lớp "CS101".') == 0
    reply = (
        "Có 2 bài đang ở trạng thái lỗi (PDF không hợp lệ hoặc xử lý "
        'thất bại) ở lớp "CS101". Mở hàng đợi duyệt bài.'
    )
    assert parse_errors(reply) == 2


def test_parse_new_review_requests() -> None:
    assert (
        parse_new_review_requests("Không có yêu cầu xem lại mới nào trong 24 giờ qua.")
        == 0
    )
    assert (
        parse_new_review_requests(
            'Có 5 yêu cầu xem lại mới (còn mở) trong 24 giờ qua ở lớp "CS101".'
        )
        == 5
    )


def test_parse_not_submitted_active_students() -> None:
    reply = (
        'Lớp "CS101" (31 sinh viên đang hoạt động):\n'
        '• Bài tập "SRS": tất cả sinh viên đã nộp.'
    )
    assert parse_not_submitted_active_students(reply) == 31


def test_parse_not_submitted_for_assignment_zero_missing() -> None:
    reply = (
        'Lớp "CS101" (31 sinh viên đang hoạt động):\n'
        '• Bài tập "Báo cáo SRS Hoàn chỉnh": tất cả sinh viên đã nộp.'
    )
    assert parse_not_submitted_for_assignment(reply, "Báo cáo SRS Hoàn chỉnh") == 0


def test_parse_not_submitted_for_assignment_nonzero_missing() -> None:
    reply = (
        'Lớp "CS101" (31 sinh viên đang hoạt động):\n'
        '• Bài tập "Khởi động Tuần 1" (đã đóng): 31/31 sinh viên chưa nộp:\n'
        "   - A (a@x)\n"
    )
    assert parse_not_submitted_for_assignment(reply, "Khởi động Tuần 1") == 31


def test_parse_not_submitted_for_assignment_missing_title_returns_none() -> None:
    reply = (
        'Lớp "CS101" (31 sinh viên đang hoạt động):\n'
        '• Bài tập "Khác": tất cả sinh viên đã nộp.'
    )
    assert parse_not_submitted_for_assignment(reply, "Không tồn tại") is None


def test_parse_summary_all_courses_rate() -> None:
    reply = (
        'Lớp "CS101": 3% (1/31) chấm xong, 31 sinh viên hoạt động.\n'
        'Lớp "CS202" chưa có bài nộp.'
    )
    parsed = parse_summary_all_courses_rate(reply)
    assert parsed == {"rate": 3, "reviewed": 1, "total": 31, "students": 31}


def test_parse_summary_all_courses_rate_no_match() -> None:
    assert parse_summary_all_courses_rate('Lớp "CS202" chưa có bài nộp.') is None


# --- Tier 2 retrieval metrics (multi-relevant gold) --------------------------

ONE_GOLD = [{"page": 5, "keyword": "benchmarks"}]
TWO_GOLD = [{"page": 5, "keyword": "benchmarks"}, {"page": 24, "keyword": "anisotropy"}]


def chunk(
    page: int, section: str | None, text: str, page_end: int | None = None
) -> ChunkLike:
    return ChunkLike(
        page_start=page,
        page_end=page if page_end is None else page_end,
        section_path=section,
        text=text,
    )


def test_fold_compact_removes_all_whitespace() -> None:
    assert fold_compact("Dựa  trên\nmô hình") == "duatrenmohinh"


def test_chunk_relevant_requires_page_in_range_and_keyword() -> None:
    assert chunk_is_relevant(chunk(5, "3.1.2 Benchmarks", "GSM8K"), 5, "benchmarks")
    # Keyword present but the gold page is outside the chunk's range.
    assert not chunk_is_relevant(chunk(6, "Benchmarks", "x"), 5, "benchmarks")
    # Right page but no keyword.
    assert not chunk_is_relevant(chunk(5, "Intro", "nothing"), 5, "benchmarks")


def test_chunk_relevant_uses_page_range_not_just_start() -> None:
    spanning = chunk(4, "Benchmarks", "x", page_end=6)
    assert chunk_is_relevant(spanning, 5, "benchmarks")
    assert chunk_is_relevant(spanning, 6, "benchmarks")
    assert not chunk_is_relevant(spanning, 7, "benchmarks")


def test_chunk_relevant_optional_page_tolerance() -> None:
    assert not chunk_is_relevant(chunk(7, "Benchmarks", "x"), 5, "benchmarks")
    assert chunk_is_relevant(
        chunk(7, "Benchmarks", "x"), 5, "benchmarks", page_tolerance=2
    )


def test_glued_chunk_still_matches_spaced_keyword() -> None:
    glued = chunk(3, None, "Bàibáođềxuấtphươngphápdựatrênđồthịtrithức")
    assert chunk_is_relevant(glued, 3, "dựa trên đồ thị tri thức")
    # And the other way round: spaced chunk text, glued keyword.
    spaced = chunk(3, None, "phương pháp dựa trên đồ thị")
    assert chunk_is_relevant(spaced, 3, "dựatrênđồthị")


def test_keyword_match_is_diacritic_and_case_insensitive() -> None:
    c = chunk(5, "Độ Chính Xác Ngữ Cảnh", "")
    assert chunk_is_relevant(c, 5, "do chinh xac ngu canh")


def test_context_precision_at_k_all_relevant() -> None:
    chunks = [
        chunk(5, "3.1.2 Benchmarks", "GSM8K and AQUA"),
        chunk(5, "3.1.2 Benchmarks", "more benchmark text"),
    ]
    assert context_precision_at_k(chunks, ONE_GOLD) == 1.0


def test_context_precision_at_k_partial_relevant() -> None:
    chunks = [
        chunk(5, "3.1.2 Benchmarks", "GSM8K"),
        chunk(20, "Unrelated section", "nothing to do with it"),
    ]
    assert context_precision_at_k(chunks, ONE_GOLD) == 0.5


def test_context_precision_at_k_empty_is_none() -> None:
    assert context_precision_at_k([], ONE_GOLD) is None


def test_precision_counts_chunks_matching_different_gold_locations() -> None:
    # k=4: two chunks hit gold #1 (p5), one hits gold #2 (p24), one hits none.
    chunks = [
        chunk(5, "Benchmarks", "a"),
        chunk(5, None, "benchmarks used: GSM8K"),
        chunk(24, "4.1.1 Anisotropy", "results"),
        chunk(12, "Method", "unrelated"),
    ]
    assert context_precision_at_k(chunks, TWO_GOLD) == 3 / 4
    assert context_recall(chunks, TWO_GOLD) == 1.0


def test_no_relevant_chunk_retrieved() -> None:
    chunks = [chunk(1, "Intro", "x"), chunk(30, "References", "y")]
    assert context_precision_at_k(chunks, TWO_GOLD) == 0.0
    assert context_recall(chunks, TWO_GOLD) == 0.0


def test_context_recall_with_multiple_gold_locations_is_fractional() -> None:
    assert context_recall([chunk(5, "Benchmarks", "")], TWO_GOLD) == 0.5
    both = [chunk(5, "Benchmarks", ""), chunk(24, "Anisotropy", "")]
    assert context_recall(both, TWO_GOLD) == 1.0


def test_context_recall_empty_inputs() -> None:
    assert context_recall([], ONE_GOLD) == 0.0
    assert context_recall([chunk(1, "", "")], []) == 0.0


def test_count_relevant_chunks_counts_whole_corpus() -> None:
    corpus = [
        chunk(5, "Benchmarks", "a"),
        chunk(5, "Benchmarks", "b"),
        chunk(24, "Anisotropy", "c"),
        chunk(9, "Other", "d"),
    ]
    assert count_relevant_chunks(corpus, TWO_GOLD) == 3
    assert count_relevant_chunks(corpus, []) == 0


def test_theoretical_max_precision_capped_by_relevant_chunk_count() -> None:
    # A perfect retriever can't beat 1/6 when the submission's WHOLE chunk
    # corpus has only 1 chunk relevant to the question and k=6 - this is
    # what makes a flat >=70% threshold meaningless for narrow questions,
    # independent of retrieval quality.
    assert theoretical_max_precision(1, k=6) == 1 / 6
    assert theoretical_max_precision(2, k=6) == 2 / 6


def test_theoretical_max_precision_never_exceeds_one() -> None:
    assert theoretical_max_precision(10, k=6) == 1.0


def test_theoretical_max_precision_zero_k_is_zero_not_error() -> None:
    assert theoretical_max_precision(3, k=0) == 0.0


# --- Out-of-scope rejection ----------------------------------------------------


def test_is_rejection() -> None:
    assert is_rejection("UNKNOWN", 0)
    assert is_rejection("ASK_ABOUT_REQUIREMENT", 0)
    assert not is_rejection("ASK_ABOUT_REQUIREMENT", 2)
    assert not is_rejection("SUMMARY", 0)


# --- Glue heuristic -------------------------------------------------------------


def test_glue_candidates_flags_long_or_camel_vietnamese_words() -> None:
    text = "Báocáonàycungcấp các TrầnTuấnNghĩa được giới thiệu Gutiérrez retrieval"
    assert glue_candidates(text) == ["Báocáonàycungcấp", "TrầnTuấnNghĩa", "Gutiérrez"]


def test_glue_stats_and_group() -> None:
    stats = glue_stats("các và được Báocáonàycungcấp")
    assert stats == {"vi_words": 4, "glued": 1, "rate": 0.25}
    assert glue_stats("plain english only")["rate"] == 0.0
    assert glue_group(0.0) == "low"
    assert glue_group(0.0199) == "low"
    assert glue_group(0.02) == "mid"
    assert glue_group(0.10) == "high"


# --- Judge calibration ---------------------------------------------------------


def test_cohen_kappa_hand_computed() -> None:
    # 10 items: 4 yes/yes, 1 yes/no, 2 no/yes, 3 no/no.
    pairs = (
        [(True, True)] * 4
        + [(True, False)]
        + [(False, True)] * 2
        + [(False, False)] * 3
    )
    # p_o = 0.7; p_yes(a) = 0.5, p_yes(b) = 0.6 -> p_e = 0.3 + 0.2 = 0.5
    assert abs(cohen_kappa(pairs) - 0.4) < 1e-9
    assert agreement(pairs) == 0.7


def test_cohen_kappa_edge_cases() -> None:
    assert cohen_kappa([]) is None
    # Both raters always "yes": p_e = 1, kappa undefined.
    assert cohen_kappa([(True, True)] * 5) is None
    assert cohen_kappa([(True, True), (False, False)]) == 1.0


def test_percentile() -> None:
    assert percentile([], 50) is None
    assert percentile([3.0, 1.0, 2.0], 50) == 2.0
    assert abs(percentile([1.0, 2.0, 3.0, 4.0], 95) - 3.85) < 1e-9


# --- Tier 0 clarification precision/recall -----------------------------------


def test_clarification_outcome() -> None:
    assert clarification_outcome("course", "course") == (True, True)
    assert clarification_outcome(None, None) == (False, False)
    assert clarification_outcome("submission", None) == (True, False)
    assert clarification_outcome(None, "submission") == (False, True)


def test_precision_recall_hand_computed() -> None:
    # 4 cases: 2 correctly asked, 1 wrongly asked (unnecessary), 1 correctly
    # not asked, and 1 missed case (should have asked but didn't).
    outcomes = [
        (True, True),  # correct ask
        (True, True),  # correct ask
        (True, False),  # unnecessary ask (hurts precision)
        (False, False),  # correctly silent
        (False, True),  # missed clarification (hurts recall)
    ]
    precision, recall = precision_recall(outcomes)
    # 3 asks total, 2 of them justified -> precision = 2/3
    assert precision == 2 / 3
    # 3 cases truly needed clarification, 2 were caught -> recall = 2/3
    assert recall == 2 / 3


def test_precision_recall_empty_inputs_are_none() -> None:
    assert precision_recall([]) == (None, None)
    # Nothing was ever asked -> precision undefined.
    assert precision_recall([(False, False), (False, True)])[0] is None
    # Nothing ever needed clarification -> recall undefined.
    assert precision_recall([(False, False), (True, False)])[1] is None


# --- Tier 3 deterministic summary structure rubric ---------------------------


def test_summary_structure_score_full_marks() -> None:
    text = (
        "**Mục tiêu:** Nghiên cứu X.\n\n"
        "**Phạm vi:** Giới hạn Y.\n\n"
        "**Điểm chính từng phần:**\n"
        "- Chương 1: tóm tắt.\n"
        "- Chương 2: tóm tắt.\n"
    )
    assert summary_structure_score(text) == 5


def test_summary_structure_score_missing_parts() -> None:
    assert summary_structure_score("Một đoạn văn ngắn không có cấu trúc gì cả.") <= 1


def test_summary_structure_score_too_short_loses_point() -> None:
    text = "**Mục tiêu:** A\n**Phạm vi:** B\n**Điểm chính**\n- x"
    # Has all 3 headers + a bullet (4 points) but is under 80 chars (no 5th point).
    assert summary_structure_score(text) == 4


# --- Shared aggregate helpers --------------------------------------------------


def test_mean_ignores_none() -> None:
    assert mean([1.0, None, 0.5]) == 0.75  # type: ignore[list-item]
    assert mean([]) is None
    assert mean([None, None]) is None  # type: ignore[list-item]


def test_rate_divides_safely() -> None:
    assert rate(3, 4) == 0.75
    assert rate(0, 0) is None


# --- Tier 3: cache correctness (two-step miss-then-hit) -----------------------


def test_cache_case_ok_when_miss_then_hit() -> None:
    assert cache_case_ok(2, 0, "same text", "same text") is True


def test_cache_case_ok_false_if_never_called_llm_first_time() -> None:
    # Already cached before this run started - never proved the write path.
    assert cache_case_ok(0, 0, "same text", "same text") is False


def test_cache_case_ok_false_if_second_request_calls_llm_again() -> None:
    assert cache_case_ok(2, 1, "same text", "same text") is False


def test_cache_case_ok_false_if_replies_differ() -> None:
    assert cache_case_ok(2, 0, "text a", "text b") is False


def test_cache_invalidated_ok_needs_a_rebuild() -> None:
    assert cache_invalidated_ok(1, "old", "new") is True
    # Served the stale summary without calling the LLM -> not invalidated.
    assert cache_invalidated_ok(0, "old", "old") is False
