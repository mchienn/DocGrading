# Ablation benchmark — 20261009T071556Z (baseline)

- Commit: `eb4d9c4` (app code dirty: False); DB: `docgrading_test`
- LLM: `gpt-4o-mini` (judge dùng cùng model); embedding: `text-embedding-3-small`
- Token: LLM 906,270 (ước tính trước khi chạy 1,317,200; trần 2,000,000); embedding 2,594 token / 189 lần gọi
- Hiệu chỉnh judge: CHƯA — chưa có file nhãn tay

## Cấu hình

- **rule_only**: Bộ phân loại intent theo từ khóa + truy vấn SQL; không LLM router, không LLM soạn câu trả lời/tóm tắt; truy hồi chỉ full-text (keyword) - không vector.
- **rag_only**: Không bộ phân loại intent: mọi câu đi thẳng vào nhánh ASK_ABOUT_REQUIREMENT (truy hồi + LLM soạn câu trả lời có trích dẫn); truy hồi chỉ vector (pgvector) - không full-text.
- **hybrid**: Hệ thống hiện tại: từ khóa -> (UNKNOWN) LLM router; SQL cho số liệu; truy hồi lai vector + full-text (RRF); LLM soạn câu trả lời và tóm tắt (có cache).

## Kết quả chính

⚠ chỉ báo = N < 20. N của precision clarification = số lần bot hỏi lại; N của recall = số ca thật sự cần hỏi lại.

| Metric | Ngưỡng | rule_only | rag_only | hybrid |
|---|---|---|---|---|
| Intent accuracy | ≥95% | 100.0% (N=53) | N/A: không có bộ phân loại intent (mọi câu → ASK) | 100.0% (N=53) |
| OOS rejection | ≥90% | 100.0% (N=18) ⚠ chỉ báo | 100.0% (N=18) ⚠ chỉ báo | 100.0% (N=18) ⚠ chỉ báo |
| Numeric correctness (strict) | 100% | 100.0% (N=53) | 0.0% (N=53) | 100.0% (N=53) |
| Numeric (lenient, cận trên) | — | — (chỉ dùng cho rag_only) | 0.0% (N=53) | — (chỉ dùng cho rag_only) |
| Clarification precision | ≥90% | 100.0% (N=6) ⚠ chỉ báo | 100.0% (N=4) ⚠ chỉ báo | 100.0% (N=6) ⚠ chỉ báo |
| Clarification recall | ≥90% | 100.0% (N=6) ⚠ chỉ báo | 66.7% (N=6) ⚠ chỉ báo | 100.0% (N=6) ⚠ chỉ báo |
| Context Precision@k (trang chính xác) | ≥70% | 45.0% (N=36) | 19.0% (N=36) | 19.0% (N=36) |
|   trần lý thuyết P@k | — | 48.9% | 20.8% | 20.8% |
|   P@k / trần | — | 92.0% | 91.1% | 91.1% |
| Context Recall | ≥80% | 82.4% (N=36) | 94.9% (N=36) | 94.9% (N=36) |
| Faithfulness — LLM-judge chưa hiệu chỉnh | ≥90% | N/A: không có LLM sinh câu trả lời (chỉ trả đoạn trích nguyên văn) | 92.2% (N=16) ⚠ chỉ báo | 91.2% (N=16) ⚠ chỉ báo |
| Citation precision — LLM-judge chưa hiệu chỉnh | ≥90% | N/A: không có LLM sinh câu trả lời (chỉ trả đoạn trích nguyên văn) | 100.0% (N=16) ⚠ chỉ báo | 100.0% (N=16) ⚠ chỉ báo |
| Citation recall — LLM-judge chưa hiệu chỉnh | ≥85% | N/A: không có LLM sinh câu trả lời (chỉ trả đoạn trích nguyên văn) | 90.6% (N=16) ⚠ chỉ báo | 85.9% (N=16) ⚠ chỉ báo |
| Summary structure (0–5, phụ) | — | N/A: không có LLM để tóm tắt | 1.00 (N=9) ⚠ chỉ báo | 5.00 (N=9) ⚠ chỉ báo |
| Latency p50 / p95 (mọi ca) | — | 0.01s / 0.03s (N=142) | 2.51s / 4.92s (N=142) | 0.22s / 3.87s (N=142) |
| Error rate (5xx) | 0% | 0.0% (N=142) | 0.0% (N=142) | 0.0% (N=142) |

## Tầng 2 (truy hồi) tách theo tỉ lệ dính chữ của tài liệu

Nhóm: low < 2%, mid 2–10%, high ≥ 10% (heuristic của chunk audit). Hai cột cuối là kiểm tra độ nhạy với dung sai trang ±2 (quy tắc cũ).

| Config | Nhóm | N | P@k | Trần | P@k/trần | Recall | P@k ±2 | Recall ±2 |
|---|---|---|---|---|---|---|---|---|
| rule_only | tổng | 36 | 45.0% | 48.9% | 92.0% | 82.4% | 49.6% | 82.4% |
| rule_only | low | 18 ⚠ | 48.5% | 53.1% | 91.3% | 95.4% | 52.2% | 95.4% |
| rule_only | mid | 6 ⚠ | 59.4% | 59.4% | 100.0% | 100.0% | 74.4% | 100.0% |
| rule_only | high | 12 ⚠ | 30.0% | 35.0% | 85.7% | 54.2% | 30.0% | 54.2% |
| rag_only | tổng | 36 | 19.0% | 20.8% | 91.1% | 94.9% | 24.1% | 94.9% |
| rag_only | low | 18 ⚠ | 20.4% | 23.1% | 88.0% | 95.4% | 23.1% | 95.4% |
| rag_only | mid | 6 ⚠ | 19.4% | 19.4% | 100.0% | 100.0% | 25.0% | 100.0% |
| rag_only | high | 12 ⚠ | 16.7% | 18.1% | 92.3% | 91.7% | 25.0% | 91.7% |
| hybrid | tổng | 36 | 19.0% | 20.8% | 91.1% | 94.9% | 24.1% | 94.9% |
| hybrid | low | 18 ⚠ | 20.4% | 23.1% | 88.0% | 95.4% | 24.1% | 95.4% |
| hybrid | mid | 6 ⚠ | 19.4% | 19.4% | 100.0% | 100.0% | 27.8% | 100.0% |
| hybrid | high | 12 ⚠ | 16.7% | 18.1% | 92.3% | 91.7% | 22.2% | 91.7% |

## Tầng 3 (câu trả lời có trích dẫn) tách theo nhóm dính chữ

Mọi số trong bảng này do LLM-judge chấm và **chưa hiệu chỉnh** bằng nhãn tay.

| Config | Nhóm | Judged/N | Faithfulness | Citation precision | #trích dẫn | Citation recall | Claim coverage |
|---|---|---|---|---|---|---|---|
| rag_only | tổng | 16/16 ⚠ | 92.2% | 100.0% | 19 | 90.6% | 75.0% |
| rag_only | low | 10/10 ⚠ | 87.5% | 100.0% | 11 | 85.0% | 60.0% |
| rag_only | mid | 2/2 ⚠ | 100.0% | 100.0% | 2 | 100.0% | 100.0% |
| rag_only | high | 4/4 ⚠ | 100.0% | 100.0% | 6 | 100.0% | 100.0% |
| hybrid | tổng | 16/16 ⚠ | 91.2% | 100.0% | 23 | 85.9% | 67.2% |
| hybrid | low | 10/10 ⚠ | 86.0% | 100.0% | 15 | 77.5% | 52.5% |
| hybrid | mid | 2/2 ⚠ | 100.0% | 100.0% | 2 | 100.0% | 100.0% |
| hybrid | high | 4/4 ⚠ | 100.0% | 100.0% | 6 | 100.0% | 87.5% |

## Cache tóm tắt (cấu hình hybrid)

Đạt 10/12 ca (83.3%); 0 ca không đủ điều kiện tiền đề (không tính).

| Loại ca | N | Đạt |
|---|---|---|
| miss_then_hit | 6 | 6 |
| precached_hit | 2 | 2 |
| content_change_same_version | 2 | 0 |
| new_version | 2 | 2 |

| Ca | Loại | Số lần gọi LLM mỗi request | Kết quả |
|---|---|---|---|
| CACHE-MISS-HIT-01 | miss_then_hit | [1, 0] | pass |
| CACHE-MISS-HIT-02 | miss_then_hit | [1, 0] | pass |
| CACHE-MISS-HIT-03 | miss_then_hit | [1, 0] | pass |
| CACHE-MISS-HIT-04 | miss_then_hit | [4, 0] | pass |
| CACHE-MISS-HIT-05 | miss_then_hit | [4, 0] | pass |
| CACHE-MISS-HIT-06 | miss_then_hit | [4, 0] | pass |
| CACHE-PRECACHED-07 | precached_hit | [0, 0] | pass |
| CACHE-PRECACHED-08 | precached_hit | [0, 0] | pass |
| CACHE-CONTENT-CHANGE-09 | content_change_same_version | [4, 0, 0] | fail |
| CACHE-CONTENT-CHANGE-10 | content_change_same_version | [6, 0, 0] | fail |
| CACHE-NEW-VERSION-11 | new_version | [1, 0, 1, 0] | pass |
| CACHE-NEW-VERSION-12 | new_version | [0, 0, 4, 0] | pass |
- rule_only: N/A: không có LLM tóm tắt nên không có cache
- rag_only: N/A: không có nhánh SUMMARIZE (mọi câu → ASK)

## Token đã dùng

| Phần | LLM tokens | Theo mục đích | Embedding tokens |
|---|---|---|---|
| rule_only | 0 | — | 0 |
| rag_only | 711,249 | answer: 669,861 (136 lần), judge: 41,388 (35 lần) | 1,805 |
| hybrid | 108,099 | answer: 37,350 (17 lần), judge: 46,216 (39 lần), router: 24,533 (34 lần) | 789 |
| cache suite | 86,922 | summary | 0 |

## Tài liệu trong tầng 2/3

| document_version (8 ký tự) | Tỉ lệ dính chữ | Nhóm | Từ có dấu | Chunk |
|---|---|---|---|---|
| f3ab31f3 | 0.00% | low | 7024 | 144 |
| aeeb376b | 0.00% | low | 0 | 18 |
| 3b19e4cb | 0.00% | low | 2606 | 33 |
| 4a0253c3 | 0.00% | low | 0 | 34 |
| 6d1d7d68 | 0.00% | low | 0 | 28 |
| c557701f | 0.04% | low | 6937 | 88 |
| 6029bae0 | 0.10% | low | 4898 | 55 |
| c4aed038 | 1.79% | low | 5486 | 76 |
| 7874ef79 | 2.75% | mid | 6225 | 73 |
| 97f342b1 | 30.72% | high | 1797 | 62 |
| 893cfc1e | 50.00% | high | 2 | 17 |

Heuristic chỉ phát hiện dính chữ tiếng Việt; tài liệu tiếng Anh (ít từ có dấu) luôn có tỉ lệ ~0% dù có thể dính chữ, và một tài liệu tiếng Anh có thể bị xếp nhóm cao chỉ vì 1–2 tên riêng có dấu (xem cột 'Từ có dấu').
