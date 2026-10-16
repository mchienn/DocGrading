# Ablation benchmark — 20261016T045159Z (after_parser)

- Commit: `d15111a` (app code dirty: True); DB: `docgrading_test`
- LLM hệ thống: `gpt-4o-mini`; judge: `gpt-4o-mini` (CÙNG model với hệ thống); embedding: `text-embedding-3-small`
- Token: LLM 642,410 (ước tính trước khi chạy 1,317,200; trần 2,000,000); embedding 2,592 token / 189 lần gọi
- Hiệu chỉnh judge: CHƯA — 0/54 mẫu đã có nhãn tay

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
| Context Precision@k — mẫu số cố định k=6 (trang chính xác) | ≥70% | 17.1% (N=36) | 19.4% (N=36) | 19.4% (N=36) |
|   trần lý thuyết P@k (k=6) | — | 20.8% | 20.8% | 20.8% |
|   P@k / trần (k=6) | — | 82.2% | 93.3% | 93.3% |
| Context Precision@k — mẫu số = số chunk trả về (cũ, không so sánh được giữa cấu hình) | — | 46.7% (N=36) | 19.4% (N=36) | 19.4% (N=36) |
|   trần lý thuyết P@k (mẫu số = số chunk trả về) | — | 52.1% | 20.8% | 20.8% |
|   P@k / trần (mẫu số = số chunk trả về) | — | 89.6% | 93.3% | 93.3% |
| Context Recall | ≥80% | 88.0% (N=36) | 97.7% (N=36) | 97.7% (N=36) |
| Faithfulness — LLM-judge chưa hiệu chỉnh | ≥90% | N/A: không có LLM sinh câu trả lời (chỉ trả đoạn trích nguyên văn) | 96.2% (N=16) ⚠ chỉ báo | 97.2% (N=16) ⚠ chỉ báo |
| Citation precision — LLM-judge chưa hiệu chỉnh | ≥90% | N/A: không có LLM sinh câu trả lời (chỉ trả đoạn trích nguyên văn) | 97.9% (N=16) ⚠ chỉ báo | 92.7% (N=16) ⚠ chỉ báo |
| Citation recall — LLM-judge chưa hiệu chỉnh | ≥85% | N/A: không có LLM sinh câu trả lời (chỉ trả đoạn trích nguyên văn) | 95.3% (N=16) ⚠ chỉ báo | 92.7% (N=16) ⚠ chỉ báo |
| Summary structure (0–5, phụ) | — | N/A: không có LLM để tóm tắt | 1.00 (N=9) ⚠ chỉ báo | 5.00 (N=9) ⚠ chỉ báo |
| Latency p50 / p95 (mọi ca) | — | 0.02s / 0.06s (N=142) | 2.81s / 5.74s (N=142) | 0.35s / 5.18s (N=142) |
| Error rate (5xx) | 0% | 0.0% (N=142) | 0.0% (N=142) | 0.0% (N=142) |

## Tầng 2 (truy hồi) tách theo tỉ lệ dính chữ của tài liệu

Nhóm: en = tài liệu tiếng Anh (loại khỏi phân nhóm dính chữ); tài liệu tiếng Việt: low < 2%, mid 2–10%, high ≥ 10% (heuristic của chunk audit). Ba cột cuối là kiểm tra độ nhạy với dung sai trang ±2 (quy tắc cũ). P@k (k=6) chia cho 6 ở mọi cấu hình nên so sánh được giữa cấu hình; cột "mẫu số = số chunk trả về" chia cho số chunk thực sự trả về, nên cấu hình trả ít chunk hơn (rule_only) được lợi.

| Config | Nhóm | N | P@k (k=6) | Trần (k=6) | P@k/trần (k=6) | P@k (mẫu số = số chunk trả về) | Trần (mẫu số = số chunk trả về) | P@k/trần (mẫu số = số chunk trả về) | Recall | P@k ±2 (k=6) | P@k ±2 (mẫu số = số chunk trả về) | Recall ±2 |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| rule_only | tổng | 36 | 17.1% | 20.8% | 82.2% | 46.7% | 52.1% | 89.6% | 88.0% | 21.3% | 53.0% | 88.0% |
| rule_only | en | 12 ⚠ | 13.9% | 16.7% | 83.3% | 27.0% | 27.0% | 100.0% | 83.3% | 13.9% | 27.0% | 83.3% |
| rule_only | low | 24 | 18.8% | 22.9% | 81.8% | 54.9% | 62.5% | 87.8% | 90.3% | 25.0% | 63.9% | 90.3% |
| rule_only | mid | 0 ⚠ | — | — | — | — | — | — | — | — | — | — |
| rule_only | high | 0 ⚠ | — | — | — | — | — | — | — | — | — | — |
| rag_only | tổng | 36 | 19.4% | 20.8% | 93.3% | 19.4% | 20.8% | 93.3% | 97.7% | 23.6% | 23.6% | 97.7% |
| rag_only | en | 12 ⚠ | 16.7% | 16.7% | 100.0% | 16.7% | 16.7% | 100.0% | 100.0% | 18.1% | 18.1% | 100.0% |
| rag_only | low | 24 | 20.8% | 22.9% | 90.9% | 20.8% | 22.9% | 90.9% | 96.5% | 26.4% | 26.4% | 96.5% |
| rag_only | mid | 0 ⚠ | — | — | — | — | — | — | — | — | — | — |
| rag_only | high | 0 ⚠ | — | — | — | — | — | — | — | — | — | — |
| hybrid | tổng | 36 | 19.4% | 20.8% | 93.3% | 19.4% | 20.8% | 93.3% | 97.7% | 24.5% | 24.5% | 97.7% |
| hybrid | en | 12 ⚠ | 16.7% | 16.7% | 100.0% | 16.7% | 16.7% | 100.0% | 100.0% | 18.1% | 18.1% | 100.0% |
| hybrid | low | 24 | 20.8% | 22.9% | 90.9% | 20.8% | 22.9% | 90.9% | 96.5% | 27.8% | 27.8% | 96.5% |
| hybrid | mid | 0 ⚠ | — | — | — | — | — | — | — | — | — | — |
| hybrid | high | 0 ⚠ | — | — | — | — | — | — | — | — | — | — |

## Tầng 3 (câu trả lời có trích dẫn) tách theo nhóm dính chữ

Mọi số trong bảng này do LLM-judge chấm và **chưa hiệu chỉnh** bằng nhãn tay.

| Config | Nhóm | Judged/N | Faithfulness | Citation precision | #trích dẫn | Citation recall | Claim coverage |
|---|---|---|---|---|---|---|---|
| rag_only | tổng | 16/16 ⚠ | 96.2% | 97.9% | 20 | 95.3% | 68.8% |
| rag_only | en | 6/6 ⚠ | 91.7% | 100.0% | 7 | 91.7% | 66.7% |
| rag_only | low | 10/10 ⚠ | 99.0% | 96.7% | 13 | 97.5% | 70.0% |
| rag_only | mid | 0/0 ⚠ | — | — | 0 | — | — |
| rag_only | high | 0/0 ⚠ | — | — | 0 | — | — |
| hybrid | tổng | 16/16 ⚠ | 97.2% | 92.7% | 22 | 92.7% | 70.3% |
| hybrid | en | 6/6 ⚠ | 95.8% | 100.0% | 7 | 88.8% | 70.8% |
| hybrid | low | 10/10 ⚠ | 98.0% | 88.3% | 15 | 95.0% | 70.0% |
| hybrid | mid | 0/0 ⚠ | — | — | 0 | — | — |
| hybrid | high | 0/0 ⚠ | — | — | 0 | — | — |

## Cache tóm tắt (cấu hình hybrid)

Đạt 2/2 ca (100.0%); 10 ca không đủ điều kiện tiền đề (không tính).

| Loại ca | N | Đạt |
|---|---|---|
| new_version | 2 | 2 |

| Ca | Loại | Số lần gọi LLM mỗi request | Kết quả |
|---|---|---|---|
| CACHE-MISS-HIT-01 | miss_then_hit | — | precondition_failed |
| CACHE-MISS-HIT-02 | miss_then_hit | — | precondition_failed |
| CACHE-MISS-HIT-03 | miss_then_hit | — | precondition_failed |
| CACHE-MISS-HIT-04 | miss_then_hit | — | precondition_failed |
| CACHE-MISS-HIT-05 | miss_then_hit | — | precondition_failed |
| CACHE-MISS-HIT-06 | miss_then_hit | — | precondition_failed |
| CACHE-LEGACY-07 | legacy_row_regenerates | — | precondition_failed |
| CACHE-LEGACY-08 | legacy_row_regenerates | — | precondition_failed |
| CACHE-CONTENT-CHANGE-09 | content_change_same_version | — | precondition_failed |
| CACHE-CONTENT-CHANGE-10 | content_change_same_version | — | precondition_failed |
| CACHE-NEW-VERSION-11 | new_version | [0, 0, 1, 0] | pass |
| CACHE-NEW-VERSION-12 | new_version | [0, 0, 4, 0] | pass |
- rule_only: N/A: không có LLM tóm tắt nên không có cache
- rag_only: N/A: không có nhánh SUMMARIZE (mọi câu → ASK)

## Token đã dùng

| Phần | LLM tokens | Theo mục đích | Embedding tokens |
|---|---|---|---|
| rule_only | 0 | — | 0 |
| rag_only | 527,731 | answer: 488,499 (136 lần), judge: 39,232 (36 lần) | 1,805 |
| hybrid | 101,462 | answer: 34,453 (17 lần), judge: 42,482 (38 lần), router: 24,527 (34 lần) | 787 |
| cache suite | 13,217 | summary | 0 |

## Tài liệu trong tầng 2/3

| document_version (8 ký tự) | Tỉ lệ dính chữ | Nhóm | Từ có dấu | Chunk |
|---|---|---|---|---|
| f3ab31f3 | 0.00% | low | 7011 | 146 |
| aeeb376b | 0.00% | en | 0 | 18 |
| 3b19e4cb | 0.00% | low | 2603 | 32 |
| 4a0253c3 | 0.00% | en | 0 | 36 |
| 6d1d7d68 | 0.00% | en | 0 | 29 |
| 97f342b1 | 0.00% | low | 5440 | 65 |
| c557701f | 0.01% | low | 6942 | 88 |
| 6029bae0 | 0.02% | low | 4906 | 55 |
| 7874ef79 | 0.09% | low | 7468 | 74 |
| c4aed038 | 0.52% | low | 5954 | 77 |
| 893cfc1e | 50.00% | en | 2 | 18 |

Ngôn ngữ phát hiện bằng từ chức năng (scoring.detect_language). Heuristic dính chữ chỉ áp dụng cho tài liệu tiếng Việt; tài liệu tiếng Anh (nhóm en) có thể dính chữ mà không bị phát hiện.
