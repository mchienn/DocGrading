"""LLM-as-judge prompts and parsers for tier 3 (ASK_ABOUT_REQUIREMENT).

Two judges:

- ``judge_answer`` grades a whole answer (faithfulness, citation recall,
  answer relevancy, claim coverage) against the FULL text of every chunk the
  generator was given.
- ``judge_citation`` grades ONE citation: does the cited chunk support the
  answer sentence(s) carrying that ``[n]`` marker? Citation precision is the
  mean of these verdicts, and this is the judge that
  ``evaluation/calibration/`` calibrates against hand labels.

Neither judge has been calibrated until ``calibrate_judge.py`` reports
otherwise; quote their numbers as uncalibrated.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any

from app.services.rag import LLMClient, strip_section_prefix

JUDGE_SYSTEM_PROMPT = (
    "Bạn là giám khảo (LLM-as-judge) chấm chất lượng câu trả lời của một "
    "chatbot RAG cho giảng viên. Chỉ trả về một object JSON hợp lệ, không "
    "kèm giải thích hay markdown."
)

ANSWER_KEYS = (
    "faithfulness",
    "citation_recall",
    "answer_relevancy",
    "claim_coverage",
)

_JSON_RE = re.compile(r"\{.*\}", re.DOTALL)
_MARKER_RE = re.compile(r"\[(\d+)\]")
_SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?…])\s+|\n+")


@dataclass(frozen=True)
class JudgeChunk:
    """A chunk shown to the judge: ``number`` is its [n] in the answer, or
    None when the generator received it but did not cite it."""

    number: int | None
    page_start: int
    page_end: int
    section_path: str | None
    text: str


def _pages(chunk: JudgeChunk) -> str:
    if chunk.page_start == chunk.page_end:
        return f"trang {chunk.page_start}"
    return f"trang {chunk.page_start}-{chunk.page_end}"


def build_answer_prompt(
    question: str, answer: str, chunks: list[JudgeChunk], expected_claims: list[str]
) -> str:
    cited = [c for c in chunks if c.number is not None]
    uncited = [c for c in chunks if c.number is None]
    cited_block = "\n\n".join(
        f"[{c.number}] ({_pages(c)}, {c.section_path or 'không rõ mục'}):\n"
        f"{strip_section_prefix(c.text)}"
        for c in sorted(cited, key=lambda c: c.number or 0)
    )
    uncited_block = "\n\n".join(
        f"(không được trích; {_pages(c)}, {c.section_path or 'không rõ mục'}):\n"
        f"{strip_section_prefix(c.text)}"
        for c in uncited
    )
    claims_block = "\n".join(f"- {claim}" for claim in expected_claims)
    return (
        f"Câu hỏi của giảng viên:\n{question}\n\n"
        "Các đoạn trích ĐƯỢC TRÍCH DẪN trong câu trả lời (đánh số [n]):\n"
        f"{cited_block or '(không có)'}\n\n"
        "Các đoạn trích khác cũng đã cấp cho hệ thống nhưng không được trích:\n"
        f"{uncited_block or '(không có)'}\n\n"
        "Câu trả lời của hệ thống (các số [n] là trích dẫn tới đoạn ở trên):\n"
        f"{answer}\n\n"
        "Các ý chính lẽ ra phải có trong câu trả lời đúng (gold, do con người đọc "
        "tài liệu gốc xác định trước khi xem câu trả lời của hệ thống):\n"
        f"{claims_block}\n\n"
        "Chấm các tiêu chí sau, mỗi tiêu chí là một số thực từ 0.0 đến 1.0:\n"
        "- faithfulness: tỉ lệ các khẳng định trong câu trả lời có thể suy ra trực "
        "tiếp từ các đoạn trích ở trên (được trích hoặc không), không bịa thêm.\n"
        "- citation_recall: tỉ lệ các khẳng định lấy từ đoạn trích thực sự có kèm "
        "trích dẫn [n] (không bỏ sót).\n"
        "- answer_relevancy: câu trả lời có trả lời đúng trọng tâm câu hỏi không "
        "(1.0 = đúng trọng tâm).\n"
        "- claim_coverage: tỉ lệ các ý chính (gold) được đề cập đúng trong câu "
        "trả lời.\n"
        "Chỉ trả về đúng JSON theo format sau, không thêm gì khác:\n"
        '{"faithfulness": 0.0, "citation_recall": 0.0, "answer_relevancy": 0.0, '
        '"claim_coverage": 0.0}'
    )


def parse_answer_verdict(raw: str) -> dict[str, float] | None:
    match = _JSON_RE.search(raw)
    if not match:
        return None
    try:
        data = json.loads(match.group(0))
        return {key: max(0.0, min(1.0, float(data[key]))) for key in ANSWER_KEYS}
    except (json.JSONDecodeError, KeyError, TypeError, ValueError):
        return None


def sentences_citing(answer: str, number: int) -> str:
    """The answer sentence(s) carrying the ``[number]`` marker."""
    picked = [
        sentence.strip()
        for sentence in _SENTENCE_SPLIT_RE.split(answer)
        if str(number) in _MARKER_RE.findall(sentence)
    ]
    return " ".join(picked)


def build_citation_prompt(question: str, claim: str, chunk_text: str) -> str:
    return (
        f"Câu hỏi của giảng viên:\n{question}\n\n"
        "Câu (trong câu trả lời của chatbot) có gắn trích dẫn tới đoạn bên dưới:\n"
        f"{claim}\n\n"
        "Đoạn được trích (lấy từ báo cáo PDF của sinh viên):\n"
        f"{strip_section_prefix(chunk_text)}\n\n"
        "Đoạn được trích có hỗ trợ nội dung của câu trên không? Trả lời true nếu "
        "nội dung câu (phần dựa vào trích dẫn này) có thể suy ra từ đoạn trích, "
        "false nếu đoạn trích không chứa hoặc mâu thuẫn với nội dung đó.\n"
        'Chỉ trả về đúng JSON: {"supported": true} hoặc {"supported": false}'
    )


def parse_citation_verdict(raw: str) -> bool | None:
    match = _JSON_RE.search(raw)
    if not match:
        return None
    try:
        value = json.loads(match.group(0)).get("supported")
    except (json.JSONDecodeError, AttributeError):
        return None
    return value if isinstance(value, bool) else None


async def judge_answer(
    client: LLMClient,
    question: str,
    answer: str,
    chunks: list[JudgeChunk],
    expected_claims: list[str],
) -> dict[str, float] | None:
    raw = await client.complete(
        system=JUDGE_SYSTEM_PROMPT,
        prompt=build_answer_prompt(question, answer, chunks, expected_claims),
        max_tokens=200,
    )
    return parse_answer_verdict(raw)


async def judge_citation(
    client: LLMClient, question: str, claim: str, chunk_text: str
) -> bool | None:
    raw = await client.complete(
        system=JUDGE_SYSTEM_PROMPT,
        prompt=build_citation_prompt(question, claim, chunk_text),
        max_tokens=20,
    )
    return parse_citation_verdict(raw)


def citation_records(answer: str, cited_numbers: list[int]) -> list[dict[str, Any]]:
    """One record per [n] in the answer with the sentence(s) it backs."""
    return [{"number": n, "claim": sentences_citing(answer, n)} for n in cited_numbers]
