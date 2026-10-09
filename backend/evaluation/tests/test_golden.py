from __future__ import annotations

import json
from pathlib import Path

import pytest

from evaluation.anonymize_golden import anonymize
from evaluation.golden import (
    ANONYMIZED_PATH,
    ENV_VAR,
    ORIGINAL_PATH,
    golden_path,
    load_golden_set,
)


def _case(case_id: str, question: str = "Tóm tắt bài này") -> dict:
    return {"id": case_id, "question": question, "gold": {"k": 1}}


def test_anonymize_replaces_name_segments_with_stable_codes() -> None:
    cases = [
        _case("T2-nguyenvanan-01"),
        _case("T3-ASK-nguyenvanan-02"),
        _case("T3-SUM-tranthibinh-03"),
        _case("T2-OPRO-04"),
    ]
    out, mapping = anonymize(cases, ["Nguyễn Văn An", "Trần Thị Bình"], {})
    assert [c["id"] for c in out] == [
        "T2-SV001-01",
        "T3-ASK-SV001-02",
        "T3-SUM-SV002-03",
        "T2-OPRO-04",
    ]
    assert mapping == {"nguyenvanan": "SV001", "tranthibinh": "SV002"}
    # Everything but the id is untouched.
    assert all(a["question"] == b["question"] for a, b in zip(cases, out, strict=True))


def test_anonymize_reuses_an_existing_map() -> None:
    out, mapping = anonymize(
        [_case("T2-tranthibinh-01")], ["Trần Thị Bình"], {"tranthibinh": "SV007"}
    )
    assert out[0]["id"] == "T2-SV007-01"
    assert mapping == {"tranthibinh": "SV007"}


def test_anonymize_refuses_names_outside_the_id() -> None:
    with pytest.raises(SystemExit):
        anonymize(
            [_case("T0-01", "Tóm tắt bài của Nguyễn Văn An")], ["Nguyễn Văn An"], {}
        )


def test_golden_path_selection(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(ENV_VAR, raising=False)
    assert golden_path() == ANONYMIZED_PATH
    assert golden_path("original") == ORIGINAL_PATH
    monkeypatch.setenv(ENV_VAR, "original")
    assert golden_path() == ORIGINAL_PATH
    assert golden_path("anonymized") == ANONYMIZED_PATH  # the flag wins


def test_load_golden_set_from_path(tmp_path: Path) -> None:
    path = tmp_path / "g.jsonl"
    path.write_text(json.dumps(_case("X-01")) + "\n\n", encoding="utf-8")
    assert [c["id"] for c in load_golden_set(str(path))] == ["X-01"]


@pytest.mark.skipif(
    not (ORIGINAL_PATH.exists() and ANONYMIZED_PATH.exists()),
    reason="needs both golden-set files",
)
def test_anonymized_file_differs_from_original_only_in_ids() -> None:
    original = load_golden_set("original")
    anonymized = load_golden_set("anonymized")
    assert len(original) == len(anonymized)
    for a, b in zip(original, anonymized, strict=True):
        assert {**a, "id": None} == {**b, "id": None}
