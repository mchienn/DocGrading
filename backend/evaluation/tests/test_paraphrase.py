from __future__ import annotations

import json
from pathlib import Path

from evaluation.paraphrase_eval import (
    PARAPHRASE_PATH,
    confusion_matrix,
    load_paraphrases,
    score_mode,
)


def test_template_file_has_no_question_yet() -> None:
    rows, problems = load_paraphrases(PARAPHRASE_PATH)
    assert problems == []
    # The committed file is a template; once questions are added this test
    # only checks that the file stays valid.
    assert all(r["question"].strip() for r in rows)


def test_load_paraphrases_skips_blank_and_flags_bad_rows(tmp_path: Path) -> None:
    path = tmp_path / "p.jsonl"
    rows = [
        {"id": "P1", "intent_expected": "SUMMARY", "question": "lớp sao rồi"},
        {"id": "P2", "intent_expected": "SUMMARY", "question": "  "},
        {"id": "P3", "intent_expected": "NOPE", "question": "x"},
        {"id": "P1", "intent_expected": "UNKNOWN", "question": "thời tiết"},
    ]
    path.write_text("\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8")
    loaded, problems = load_paraphrases(path)
    assert [r["id"] for r in loaded] == ["P1", "P1"]
    assert any("NOPE" in p for p in problems)
    assert any("duplicate id P1" in p for p in problems)


def test_confusion_matrix_and_score() -> None:
    pairs = [("SUMMARY", "SUMMARY"), ("SUMMARY", "UNKNOWN"), ("ERRORS", "ERRORS")]
    assert confusion_matrix(pairs) == {
        "ERRORS": {"ERRORS": 1, "SUMMARY": 0, "UNKNOWN": 0},
        "SUMMARY": {"ERRORS": 0, "SUMMARY": 1, "UNKNOWN": 1},
        "UNKNOWN": {"ERRORS": 0, "SUMMARY": 0, "UNKNOWN": 0},
    }
    rows = [
        {"id": "a", "question": "q1", "intent_expected": "SUMMARY"},
        {"id": "b", "question": "q2", "intent_expected": "SUMMARY"},
    ]
    scored = score_mode(rows, ["SUMMARY", "UNKNOWN"])
    assert scored["accuracy"] == 0.5
    assert [w["id"] for w in scored["wrong"]] == ["b"]
