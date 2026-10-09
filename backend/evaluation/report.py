"""Markdown rendering of an ablation snapshot (aggregates only)."""

from __future__ import annotations

from typing import Any

CONFIG_ORDER = ("rule_only", "rag_only", "hybrid")
SMALL_N = 20

NA_REASONS = {
    (
        "rule_only",
        "tier3",
    ): "N/A: không có LLM sinh câu trả lời (chỉ trả đoạn trích nguyên văn)",
    ("rule_only", "summarize"): "N/A: không có LLM để tóm tắt",
    ("rule_only", "cache"): "N/A: không có LLM tóm tắt nên không có cache",
    ("rag_only", "intent"): "N/A: không có bộ phân loại intent (mọi câu → ASK)",
    ("rag_only", "cache"): "N/A: không có nhánh SUMMARIZE (mọi câu → ASK)",
    ("rule_only", "lenient"): "— (chỉ dùng cho rag_only)",
    ("hybrid", "lenient"): "— (chỉ dùng cho rag_only)",
}


def _pct(value: float | None) -> str:
    return "—" if value is None else f"{value * 100:.1f}%"


def _sec(value: float | None) -> str:
    return "—" if value is None else f"{value:.2f}s"


def _cell(value: str, n: int | None) -> str:
    if n is None:
        return value
    flag = " ⚠ chỉ báo" if n < SMALL_N else ""
    return f"{value} (N={n}){flag}"


def _metric_rows(configs: dict[str, Any], calibrated: bool) -> list[list[str]]:
    judge_note = "" if calibrated else " — LLM-judge chưa hiệu chỉnh"

    def get(config: str, fn: Any, na_key: str | None = None) -> str:
        data = configs.get(config)
        if data is None:
            return "chưa chạy"
        if na_key and (config, na_key) in NA_REASONS:
            return NA_REASONS[(config, na_key)]
        return fn(data)

    rows = [
        [
            "Intent accuracy",
            "≥95%",
            *[
                get(
                    c,
                    lambda d: _cell(
                        _pct(d["tier1"]["intent_accuracy"]), d["tier1"]["intent_n"]
                    ),
                    "intent",
                )
                for c in CONFIG_ORDER
            ],
        ],
        [
            "OOS rejection",
            "≥90%",
            *[
                get(
                    c,
                    lambda d: _cell(
                        _pct(d["tier1"]["oos_rejection_rate"]), d["tier1"]["oos_n"]
                    ),
                )
                for c in CONFIG_ORDER
            ],
        ],
        [
            "Numeric correctness (strict)",
            "100%",
            *[
                get(
                    c,
                    lambda d: _cell(
                        _pct(d["tier1"]["numeric_correctness"]), d["tier1"]["numeric_n"]
                    ),
                )
                for c in CONFIG_ORDER
            ],
        ],
        [
            "Numeric (lenient, cận trên)",
            "—",
            *[
                get(
                    c,
                    lambda d: _cell(
                        _pct(d["tier1"]["numeric_lenient_upper_bound"]),
                        d["tier1"]["numeric_n"],
                    ),
                    "lenient",
                )
                for c in CONFIG_ORDER
            ],
        ],
        [
            "Clarification precision",
            "≥90%",
            *[
                get(
                    c,
                    lambda d: _cell(
                        _pct(d["tier0"]["precision"]), d["tier0"]["n_asked"]
                    ),
                )
                for c in CONFIG_ORDER
            ],
        ],
        [
            "Clarification recall",
            "≥90%",
            *[
                get(
                    c,
                    lambda d: _cell(
                        _pct(d["tier0"]["recall"]), d["tier0"]["n_should_ask"]
                    ),
                )
                for c in CONFIG_ORDER
            ],
        ],
        [
            "Context Precision@k (trang chính xác)",
            "≥70%",
            *[
                get(
                    c,
                    lambda d: _cell(
                        _pct(d["tier2"]["all"]["precision_at_k"]),
                        d["tier2"]["all"]["n"],
                    ),
                )
                for c in CONFIG_ORDER
            ],
        ],
        [
            "  trần lý thuyết P@k",
            "—",
            *[
                get(c, lambda d: _pct(d["tier2"]["all"]["precision_ceiling"]))
                for c in CONFIG_ORDER
            ],
        ],
        [
            "  P@k / trần",
            "—",
            *[
                get(c, lambda d: _pct(d["tier2"]["all"]["precision_vs_ceiling"]))
                for c in CONFIG_ORDER
            ],
        ],
        [
            "Context Recall",
            "≥80%",
            *[
                get(
                    c,
                    lambda d: _cell(
                        _pct(d["tier2"]["all"]["recall"]), d["tier2"]["all"]["n"]
                    ),
                )
                for c in CONFIG_ORDER
            ],
        ],
        [
            f"Faithfulness{judge_note}",
            "≥90%",
            *[
                get(
                    c,
                    lambda d: _cell(
                        _pct(d["tier3_ask"]["all"]["faithfulness"]),
                        d["tier3_ask"]["all"]["n_judged"],
                    ),
                    "tier3",
                )
                for c in CONFIG_ORDER
            ],
        ],
        [
            f"Citation precision{judge_note}",
            "≥90%",
            *[
                get(
                    c,
                    lambda d: _cell(
                        _pct(d["tier3_ask"]["all"]["citation_precision"]),
                        d["tier3_ask"]["all"]["n_with_citations"],
                    ),
                    "tier3",
                )
                for c in CONFIG_ORDER
            ],
        ],
        [
            f"Citation recall{judge_note}",
            "≥85%",
            *[
                get(
                    c,
                    lambda d: _cell(
                        _pct(d["tier3_ask"]["all"]["citation_recall"]),
                        d["tier3_ask"]["all"]["n_judged"],
                    ),
                    "tier3",
                )
                for c in CONFIG_ORDER
            ],
        ],
        [
            "Summary structure (0–5, phụ)",
            "—",
            *[
                get(
                    c,
                    lambda d: _cell(
                        (
                            "—"
                            if d["tier3_summarize"]["structure_score_avg_of_5"] is None
                            else f"{d['tier3_summarize']['structure_score_avg_of_5']:.2f}"  # noqa: E501
                        ),
                        d["tier3_summarize"]["n"],
                    ),
                    "summarize",
                )
                for c in CONFIG_ORDER
            ],
        ],
        [
            "Latency p50 / p95 (mọi ca)",
            "—",
            *[
                get(
                    c,
                    lambda d: _cell(
                        f"{_sec(d['latency_p50_s'])} / {_sec(d['latency_p95_s'])}",
                        d["latency_n"],
                    ),
                )
                for c in CONFIG_ORDER
            ],
        ],
        [
            "Error rate (5xx)",
            "0%",
            *[
                get(c, lambda d: _cell(_pct(d["error_rate_5xx"]), d["n_cases"]))
                for c in CONFIG_ORDER
            ],
        ],
    ]
    return rows


def _table(header: list[str], rows: list[list[str]]) -> str:
    lines = ["| " + " | ".join(header) + " |", "|" + "---|" * len(header)]
    lines += ["| " + " | ".join(r) + " |" for r in rows]
    return "\n".join(lines)


def render_markdown(snapshot: dict[str, Any]) -> str:
    configs = snapshot["configs"]
    calibration = snapshot["judge_calibration"]
    calibrated = calibration.get("calibrated") is True
    tokens = snapshot["token_usage_total"]
    parts = [
        f"# Ablation benchmark — {snapshot['timestamp']} ({snapshot['label']})",
        "",
        f"- Commit: `{snapshot['git_commit']}` (app code dirty: "
        f"{snapshot['app_code_dirty']}); DB: `{snapshot['postgres_db']}`",
        f"- LLM: `{snapshot['llm_model']}` (judge dùng cùng model); embedding: "
        f"`{snapshot['embedding_model']}`",
        f"- Token: LLM {tokens['llm_total_tokens']:,} (ước tính trước khi chạy "
        f"{snapshot['token_estimate_before_run']:,}; trần {tokens['llm_budget']:,}); "
        f"embedding {tokens['embedding']['tokens']:,} token / "
        f"{tokens['embedding']['calls']} lần gọi",
        f"- Hiệu chỉnh judge: {'đã' if calibrated else 'CHƯA'} — "
        f"{calibration['reason']}",
    ]
    if snapshot.get("aborted"):
        parts.append(f"- **Run bị dừng giữa chừng:** {snapshot['aborted']}")
    parts += ["", "## Cấu hình", ""]
    for c in CONFIG_ORDER:
        if c in configs:
            parts.append(f"- **{c}**: {configs[c]['description']}")
    parts += [
        "",
        "## Kết quả chính",
        "",
        f"⚠ chỉ báo = N < {SMALL_N}. N của precision clarification = số lần bot "
        "hỏi lại; "
        "N của recall = số ca thật sự cần hỏi lại.",
        "",
        _table(["Metric", "Ngưỡng", *CONFIG_ORDER], _metric_rows(configs, calibrated)),
    ]

    group_rows = []
    for c in CONFIG_ORDER:
        if c not in configs:
            continue
        t2 = configs[c]["tier2"]
        for g, agg in [("tổng", t2["all"]), *t2["by_group"].items()]:
            group_rows.append(
                [
                    c,
                    g,
                    str(agg["n"]) + (" ⚠" if agg["n"] < SMALL_N else ""),
                    _pct(agg["precision_at_k"]),
                    _pct(agg["precision_ceiling"]),
                    _pct(agg["precision_vs_ceiling"]),
                    _pct(agg["recall"]),
                    _pct(agg["precision_at_k_tol2"]),
                    _pct(agg["recall_tol2"]),
                ]
            )
    parts += [
        "",
        "## Tầng 2 (truy hồi) tách theo tỉ lệ dính chữ của tài liệu",
        "",
        "Nhóm: low < 2%, mid 2–10%, high ≥ 10% (heuristic của chunk audit). "
        "Hai cột cuối là kiểm tra độ nhạy với dung sai trang ±2 (quy tắc cũ).",
        "",
        _table(
            [
                "Config",
                "Nhóm",
                "N",
                "P@k",
                "Trần",
                "P@k/trần",
                "Recall",
                "P@k ±2",
                "Recall ±2",
            ],
            group_rows,
        ),
    ]

    t3_rows = []
    for c in CONFIG_ORDER:
        if c not in configs or configs[c].get("tier3_ask") is None:
            continue
        t3 = configs[c]["tier3_ask"]
        for g, agg in [("tổng", t3["all"]), *t3["by_group"].items()]:
            t3_rows.append(
                [
                    c,
                    g,
                    f"{agg['n_judged']}/{agg['n']}"
                    + (" ⚠" if agg["n"] < SMALL_N else ""),
                    _pct(agg["faithfulness"]),
                    _pct(agg["citation_precision"]),
                    str(agg["n_citations_judged"]),
                    _pct(agg["citation_recall"]),
                    _pct(agg["claim_coverage"]),
                ]
            )
    parts += [
        "",
        "## Tầng 3 (câu trả lời có trích dẫn) tách theo nhóm dính chữ",
        "",
        "Mọi số trong bảng này do LLM-judge chấm"
        + ("." if calibrated else " và **chưa hiệu chỉnh** bằng nhãn tay."),
        "",
        _table(
            [
                "Config",
                "Nhóm",
                "Judged/N",
                "Faithfulness",
                "Citation precision",
                "#trích dẫn",
                "Citation recall",
                "Claim coverage",
            ],
            t3_rows,
        ),
    ]

    cache = configs.get("cache")
    parts += ["", "## Cache tóm tắt (cấu hình hybrid)", ""]
    if cache is None:
        parts.append("Chưa chạy.")
    else:
        parts.append(
            f"Đạt {cache['pass']}/{cache['n_counted']} ca "
            f"({_pct(cache['rate'])}); {cache['n_precondition_failed']} ca không đủ "
            "điều kiện tiền đề (không tính)."
        )
        parts += [
            "",
            _table(
                ["Loại ca", "N", "Đạt"],
                [[k, str(v["n"]), str(v["pass"])] for k, v in cache["by_kind"].items()],
            ),
            "",
            _table(
                ["Ca", "Loại", "Số lần gọi LLM mỗi request", "Kết quả"],
                [
                    [
                        d["case_id"],
                        d["kind"],
                        str(d.get("calls", "—")),
                        d.get("status", "?")
                        + (f" ({d['error']})" if d.get("error") else ""),
                    ]
                    for d in cache["details"]
                ],
            ),
        ]
        for c in ("rule_only", "rag_only"):
            parts.append(f"- {c}: {NA_REASONS[(c, 'cache')]}")

    token_rows = []
    for c in CONFIG_ORDER:
        if c in configs:
            t = configs[c]["tokens"]
            purposes = ", ".join(
                f"{p}: {v['prompt'] + v['completion']:,} ({v['calls']} lần)"
                for p, v in sorted(t["llm_by_purpose"].items())
                if v["calls"]
            )
            token_rows.append(
                [
                    c,
                    f"{t['llm_total_tokens']:,}",
                    purposes or "—",
                    f"{t['embedding_tokens']:,}",
                ]
            )
    if cache is not None:
        t = cache["tokens"]
        token_rows.append(
            [
                "cache suite",
                f"{t['llm_total_tokens']:,}",
                "summary",
                f"{t['embedding_tokens']:,}",
            ]
        )
    parts += [
        "",
        "## Token đã dùng",
        "",
        _table(["Phần", "LLM tokens", "Theo mục đích", "Embedding tokens"], token_rows),
    ]

    doc_rows = [
        [
            k,
            f"{v['glue_rate'] * 100:.2f}%",
            v["glue_group"],
            str(v["vi_words"]),
            str(v["n_chunks"]),
        ]
        for k, v in sorted(
            snapshot["documents"].items(), key=lambda kv: kv[1]["glue_rate"]
        )
    ]
    parts += [
        "",
        "## Tài liệu trong tầng 2/3",
        "",
        _table(
            [
                "document_version (8 ký tự)",
                "Tỉ lệ dính chữ",
                "Nhóm",
                "Từ có dấu",
                "Chunk",
            ],
            doc_rows,
        ),
        "",
        "Heuristic chỉ phát hiện dính chữ tiếng Việt; tài liệu tiếng Anh "
        "(ít từ có dấu) "
        "luôn có tỉ lệ ~0% dù có thể dính chữ, và một tài liệu tiếng Anh có thể bị "
        "xếp nhóm cao chỉ vì 1–2 tên riêng có dấu (xem cột 'Từ có dấu').",
    ]
    return "\n".join(parts) + "\n"
