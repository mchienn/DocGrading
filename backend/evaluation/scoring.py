"""Pure scoring helpers for the chatbot evaluation benchmark.

Kept free of DB/HTTP/LLM calls on purpose so ``evaluation/tests/test_scoring.py``
can exercise the formulas with small hand-computed inputs, independently of
whether the real benchmark run (``run_all.py``) is wired correctly.

Each function mirrors the exact reply wording produced by
``app.services.chat`` (see that module's ``_handle_unreviewed``,
``_handle_errors``, ``format_not_submitted``, ``_handle_new_review_requests``,
``_handle_summary_all_courses``) — if that wording changes, these parsers
must change with it.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from typing import Any


def fold(text: str) -> str:
    """Lowercase, diacritics-stripped form used for fuzzy keyword matching."""
    # Đ/đ is its own base letter in Unicode (U+0110/U+0111), not a combining
    # mark over "d", so NFD decomposition alone would leave it untouched.
    text = text.replace("Đ", "D").replace("đ", "d")
    decomposed = unicodedata.normalize("NFD", text)
    without_marks = "".join(c for c in decomposed if unicodedata.category(c) != "Mn")
    return unicodedata.normalize("NFC", without_marks).lower()


# --- Tier 1: numeric correctness parsers ------------------------------------


def parse_unreviewed(reply: str) -> int | None:
    if "hiện không còn bài nào chờ duyệt" in reply:
        return 0
    match = re.search(r"Còn (\d+) bài chưa duyệt", reply)
    return int(match.group(1)) if match else None


def parse_errors(reply: str) -> int | None:
    if "Không có bài nào đang lỗi" in reply:
        return 0
    match = re.search(r"Có (\d+) bài đang ở trạng thái lỗi", reply)
    return int(match.group(1)) if match else None


def parse_new_review_requests(reply: str) -> int | None:
    if "Không có yêu cầu xem lại mới nào" in reply:
        return 0
    match = re.search(r"Có (\d+) yêu cầu xem lại mới", reply)
    return int(match.group(1)) if match else None


def parse_not_submitted_active_students(reply: str) -> int | None:
    match = re.search(r"\((\d+) sinh viên đang hoạt động\)", reply)
    return int(match.group(1)) if match else None


def parse_not_submitted_for_assignment(reply: str, assignment_title: str) -> int | None:
    """Missing-student count for one assignment's bullet line in a NOT_SUBMITTED reply.

    ``format_not_submitted`` writes one bullet per assignment, title quoted
    verbatim; a line either ends "... đã nộp." (0 missing) or
    "N/M sinh viên chưa nộp:" followed by the name list.
    """
    marker = f'"{assignment_title}"'
    pos = reply.find(marker)
    if pos == -1:
        return None
    segment = reply[pos : pos + 200]
    if "tất cả sinh viên đã nộp" in segment:
        return 0
    match = re.search(r"(\d+)/(\d+) sinh viên chưa nộp", segment)
    return int(match.group(1)) if match else None


def parse_summary_all_courses_rate(reply: str) -> dict[str, int] | None:
    """The first ``rate% (reviewed/total) chấm xong, N sinh viên`` line, if any."""
    match = re.search(
        r"(\d+)%\s*\((\d+)/(\d+)\)\s*chấm xong,\s*(\d+)\s*sinh viên", reply
    )
    if not match:
        return None
    rate, reviewed, total, students = (int(g) for g in match.groups())
    return {"rate": rate, "reviewed": reviewed, "total": total, "students": students}


# --- Tier 2: retrieval metrics ----------------------------------------------


def fold_compact(text: str) -> str:
    """``fold`` plus every whitespace character removed.

    PDF extraction glues Vietnamese words together ("dựatrên" for "dựa
    trên"); applying the same transform to both the keyword and the chunk
    makes a glued chunk still match its keyword.
    """
    return "".join(fold(text).split())


# Context Precision@k uses this fixed denominator for every configuration:
# the chatbot's retrieval size (``app.services.rag.FINAL_TOP_K``) and the k
# of ``retrieval_eval``.
FIXED_K = 6


@dataclass(frozen=True)
class ChunkLike:
    """One retrieved chunk as the scorer sees it (full text, page range)."""

    page_start: int
    page_end: int
    section_path: str | None
    text: str


def chunk_is_relevant(
    chunk: ChunkLike,
    gold_page: int,
    gold_keyword: str,
    *,
    page_tolerance: int = 0,
) -> bool:
    """Relevant when the gold page lies in the chunk's page range and the
    chunk's section path or text contains the gold keyword (compared with
    ``fold_compact`` on both sides).

    ``page_tolerance`` widens the range on both ends; the benchmark's
    primary numbers use 0, and the old +-2 rule is reported only as a
    sensitivity check.
    """
    if not (
        chunk.page_start - page_tolerance
        <= gold_page
        <= chunk.page_end + page_tolerance
    ):
        return False
    haystack = fold_compact(f"{chunk.section_path or ''} {chunk.text}")
    return fold_compact(gold_keyword) in haystack


@dataclass(frozen=True)
class GoldLocation:
    page: int
    keyword: str


def _as_gold_locations(gold_relevant: list[dict[str, Any]]) -> list[GoldLocation]:
    return [GoldLocation(page=g["page"], keyword=g["keyword"]) for g in gold_relevant]


def _matches_any(
    chunk: ChunkLike, locations: list[GoldLocation], page_tolerance: int
) -> bool:
    return any(
        chunk_is_relevant(chunk, g.page, g.keyword, page_tolerance=page_tolerance)
        for g in locations
    )


def context_precision_at_k(
    chunks: list[ChunkLike],
    gold_relevant: list[dict[str, Any]],
    *,
    page_tolerance: int = 0,
) -> float | None:
    """Fraction of the k retrieved chunks that match ANY gold location.

    ``gold_relevant`` is a list of ``{"page": int, "keyword": str}``: one
    question can have several correct passages, and a chunk matching any of
    them counts. k is the number of chunks actually retrieved. Returns
    ``None`` when nothing was retrieved (precision undefined, not zero).
    """
    if not chunks:
        return None
    locations = _as_gold_locations(gold_relevant)
    relevant = sum(1 for c in chunks if _matches_any(c, locations, page_tolerance))
    return relevant / len(chunks)


def context_precision_fixed_k(
    chunks: list[ChunkLike],
    gold_relevant: list[dict[str, Any]],
    *,
    k: int = FIXED_K,
    page_tolerance: int = 0,
) -> float:
    """Relevant chunks among the top *k* retrieved, divided by *k* itself.

    Unlike ``context_precision_at_k`` the denominator does not shrink when a
    configuration returns fewer than k chunks, so configurations are
    comparable; nothing retrieved scores 0.0.
    """
    locations = _as_gold_locations(gold_relevant)
    relevant = sum(1 for c in chunks[:k] if _matches_any(c, locations, page_tolerance))
    return relevant / k


def context_recall(
    chunks: list[ChunkLike],
    gold_relevant: list[dict[str, Any]],
    *,
    page_tolerance: int = 0,
) -> float:
    """Fraction of gold locations hit by at least one retrieved chunk."""
    locations = _as_gold_locations(gold_relevant)
    if not locations:
        return 0.0
    found = sum(
        1
        for g in locations
        if any(
            chunk_is_relevant(c, g.page, g.keyword, page_tolerance=page_tolerance)
            for c in chunks
        )
    )
    return found / len(locations)


def count_relevant_chunks(
    corpus: list[ChunkLike],
    gold_relevant: list[dict[str, Any]],
    *,
    page_tolerance: int = 0,
) -> int:
    """How many chunks of a submission's WHOLE corpus match a gold location
    (the numerator of ``theoretical_max_precision``)."""
    locations = _as_gold_locations(gold_relevant)
    return sum(1 for c in corpus if _matches_any(c, locations, page_tolerance))


def theoretical_max_precision(n_relevant_in_corpus: int, k: int) -> float:
    """Best precision@k a perfect retriever could reach for this corpus.

    ``n_relevant_in_corpus`` must be the count of chunks in the submission's
    *entire* chunk corpus that satisfy ``citation_is_relevant`` against the
    gold locations - NOT the number of gold locations itself. A single gold
    *section* can span several chunks that are each independently relevant,
    so "2 gold locations" does not mean "at most 2 relevant chunks"; undercounting
    this way can make measured precision look like it exceeds its own ceiling.

    When a question genuinely has fewer relevant chunks than k, even a
    perfect retriever must fill the rest of the k slots with something else,
    capping precision at ``n_relevant_in_corpus / k``. Comparing measured
    precision against this ceiling (rather than a flat threshold like 70%)
    is what actually tells you whether retrieval is underperforming.
    """
    if k <= 0:
        return 0.0
    return min(1.0, n_relevant_in_corpus / k)


# --- Tier 0: clarification precision/recall ---------------------------------


def clarification_outcome(
    needs_clarification: str | None, expected: str | None
) -> tuple[bool, bool]:
    """Return (asked, should_have_asked) for one case."""
    return (needs_clarification is not None, expected is not None)


def precision_recall(
    outcomes: list[tuple[bool, bool]],
) -> tuple[float | None, float | None]:
    """Precision = correct asks / all asks.

    Recall = correct asks / all cases that actually needed one.
    """
    asked = [o for o in outcomes if o[0]]
    needed = [o for o in outcomes if o[1]]
    precision = (
        sum(1 for asked_, expected_ in asked if expected_) / len(asked)
        if asked
        else None
    )
    recall = (
        sum(1 for asked_, expected_ in needed if asked_) / len(needed)
        if needed
        else None
    )
    return precision, recall


# --- Tier 3: deterministic summary structure rubric -------------------------


def summary_structure_score(summary_text: str) -> int:
    """0-5 rubric for the mandated 3-part structure (SUMMARY_SYSTEM_PROMPT).

    Deterministic by design (regex on the mandated markdown headers) rather
    than LLM-judged, so it stays free and exactly reproducible.
    """
    score = 0
    if re.search(r"\*\*Mục tiêu:?\*\*", summary_text):
        score += 1
    if re.search(r"\*\*Phạm vi:?\*\*", summary_text):
        score += 1
    if re.search(r"\*\*Điểm chính", summary_text):
        score += 1
    if re.search(r"^\s*-\s+\S", summary_text, re.MULTILINE):
        score += 1
    if len(summary_text.strip()) >= 80:
        score += 1
    return score


# --- Tier 3: cache correctness (two-step: miss then hit) --------------------


def cache_case_ok(
    calls_on_first_request: int,
    new_calls_on_second_request: int,
    reply_first: str,
    reply_second: str,
) -> bool:
    """One cache-correctness case passes only if it exercised BOTH paths.

    ``calls_on_first_request`` must be > 0 - otherwise the submission already
    had a cached summary before this run and the case never actually proved
    the write path works, only that re-reads don't call the LLM again.
    ``new_calls_on_second_request`` must be exactly 0 - the second, identical
    request must be served entirely from the cache. Both replies must match.
    """
    return (
        calls_on_first_request > 0
        and new_calls_on_second_request == 0
        and reply_first == reply_second
    )


def cache_invalidated_ok(
    calls_after_change: int, reply_before: str, reply_after: str
) -> bool:
    """After the summarized content changed, the next request must rebuild
    the summary (at least one LLM call) instead of serving the stale one."""
    del reply_before, reply_after  # the new text may legitimately be equal
    return calls_after_change > 0


# --- Out-of-scope rejection ---------------------------------------------------

_RAG_INTENTS = frozenset({"ASK_ABOUT_REQUIREMENT", "SEARCH_CONTENT"})


def is_rejection(intent: str, n_citations: int) -> bool:
    """An out-of-scope question counts as rejected when the bot either said
    it didn't understand (UNKNOWN/HELP) or answered through RAG without
    grounding the reply in any passage (no citation returned).

    The second clause lets the same definition apply to a RAG-only
    configuration, which has no UNKNOWN intent at all.
    """
    if intent in ("UNKNOWN", "HELP", "GREETING"):
        return True
    return intent in _RAG_INTENTS and n_citations == 0


# --- PDF word-gluing heuristic (same rule as the chunk audit) ----------------

_VI_CHARS = frozenset(
    "ăâđêôơưàảãáạằẳẵắặầẩẫấậèẻẽéẹềểễếệìỉĩíịòỏõóọồổỗốộờởỡớợùủũúụừửữứựỳỷỹýỵ"
)
_WORD_RE = re.compile(r"[^\W\d_]+", re.UNICODE)

GLUE_LOW_MAX = 0.02  # rate < 2% -> "low"
GLUE_HIGH_MIN = 0.10  # rate >= 10% -> "high"; anything in between -> "mid"


def _has_vi(word: str) -> bool:
    return any(ch in _VI_CHARS for ch in word.lower())


def glue_candidates(text: str) -> list[str]:
    """Vietnamese syllables are at most 7 letters, so a word with Vietnamese
    diacritics that is 9+ letters long, or that switches lower->upper case
    mid-word, is most likely several words glued together by the PDF reader.
    Only detects Vietnamese gluing; English text is never flagged."""
    out = []
    for word in _WORD_RE.findall(text):
        if not _has_vi(word):
            continue
        if len(word) >= 9 or any(
            a.islower() and b.isupper() for a, b in zip(word, word[1:], strict=False)
        ):
            out.append(word)
    return out


def glue_stats(text: str) -> dict[str, float | int]:
    vi_words = sum(1 for w in _WORD_RE.findall(text) if _has_vi(w))
    glued = len(glue_candidates(text))
    return {
        "vi_words": vi_words,
        "glued": glued,
        "rate": glued / vi_words if vi_words else 0.0,
    }


def glue_group(glue_rate: float) -> str:
    if glue_rate >= GLUE_HIGH_MIN:
        return "high"
    if glue_rate < GLUE_LOW_MAX:
        return "low"
    return "mid"


# Very frequent function words; which list a document hits more decides its
# language. On the anchor dataset the two populations don't overlap at all
# (Vietnamese reports: >= 4.7% Vietnamese / <= 2.1% English function words;
# English reports: <= 0.1% / >= 14%).
_VI_FUNCTION_WORDS = frozenset(
    {
        "và", "của", "các", "là", "được", "trong", "cho", "với", "những",
        "này", "có", "không", "một", "để", "từ", "khi", "theo",
    }
)  # fmt: skip
_EN_FUNCTION_WORDS = frozenset(
    {
        "the", "and", "of", "to", "in", "is", "for", "with", "that", "this",
        "are", "on", "by", "we", "as",
    }
)  # fmt: skip

GROUPS = ("en", "low", "mid", "high")


def detect_language(text: str) -> str:
    """ "vi" or "en" for a whole document."""
    words = [w.lower() for w in _WORD_RE.findall(text)]
    vi = sum(1 for w in words if w in _VI_FUNCTION_WORDS)
    en = sum(1 for w in words if w in _EN_FUNCTION_WORDS)
    return "vi" if vi > en else "en"


def document_group(text: str) -> str:
    """ "en" for English documents (the glue heuristic only sees Vietnamese,
    so they are kept out of the glue groups); otherwise the glue group."""
    if detect_language(text) == "en":
        return "en"
    return glue_group(glue_stats(text)["rate"])


# --- Judge calibration ----------------------------------------------------------


def cohen_kappa(pairs: list[tuple[bool, bool]]) -> float | None:
    """Cohen's kappa for two raters giving binary labels to the same items.

    kappa = (p_o - p_e) / (1 - p_e). Returns None for no items, and when
    p_e == 1 (both raters gave one constant label, kappa undefined).
    """
    n = len(pairs)
    if n == 0:
        return None
    p_o = sum(1 for a, b in pairs if a == b) / n
    a_yes = sum(1 for a, _ in pairs if a) / n
    b_yes = sum(1 for _, b in pairs if b) / n
    p_e = a_yes * b_yes + (1 - a_yes) * (1 - b_yes)
    if p_e == 1:
        return None
    return (p_o - p_e) / (1 - p_e)


def agreement(pairs: list[tuple[bool, bool]]) -> float | None:
    return sum(1 for a, b in pairs if a == b) / len(pairs) if pairs else None


# --- Shared aggregate helpers -------------------------------------------------


def mean(values: list[float]) -> float | None:
    values = [v for v in values if v is not None]
    return sum(values) / len(values) if values else None


def rate(hits: int, total: int) -> float | None:
    return hits / total if total else None


def percentile(values: list[float], pct: float) -> float | None:
    """Linear-interpolated percentile (same as numpy's default), pct in [0, 100]."""
    if not values:
        return None
    ordered = sorted(values)
    position = (len(ordered) - 1) * pct / 100
    low = int(position)
    high = min(low + 1, len(ordered) - 1)
    return ordered[low] + (ordered[high] - ordered[low]) * (position - low)
