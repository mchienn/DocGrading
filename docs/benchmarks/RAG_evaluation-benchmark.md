# Bộ benchmark đánh giá chất lượng chatbot giảng viên (RAG)

Tài liệu này định nghĩa 1 bộ benchmark **cố định, lặp lại được** để đo chất lượng chatbot giảng viên (DocGrading) qua thời gian — dùng cho báo cáo luận văn và để tự theo dõi hồi quy mỗi khi sửa code. Khác với tài liệu pipeline kỹ thuật (kiến trúc RAG) đã có trước đó, tài liệu này chỉ nói về **cách đo**, không nói về cách xây dựng hệ thống.

Grounded trên 3 nhóm intent thật đã triển khai: (1) số liệu tổng hợp rule-based (SUMMARY/UNREVIEWED/REVIEW_REQUESTS...), (2) tìm kiếm nội dung thuần (SEARCH_CONTENT, không LLM), (3) câu trả lời sinh bởi LLM có trích dẫn (ASK_ABOUT_REQUIREMENT, SUMMARIZE_SUBMISSION) — cộng thêm luồng hội thoại làm rõ phạm vi (needs_clarification) vừa thiết kế.

## 1. Mục tiêu & phạm vi đánh giá

**Mục tiêu**: có 1 bộ số liệu khách quan, đo lại được nhiều lần, để (a) chứng minh hệ thống hoạt động đúng thiết kế trong báo cáo luận văn, (b) phát hiện hồi quy (regression) khi sửa code sau này, (c) so sánh được giữa các lựa chọn kỹ thuật (ví dụ đổi embedding provider, đổi LLM).

**Không thuộc phạm vi tài liệu này**: cách build_chunks()/retrieve_chunks() hoạt động, lựa chọn kiến trúc — xem tài liệu pipeline RAG.

**Nguyên tắc xuyên suốt**: mọi test case dùng **dữ liệu thật của hệ thống** (báo cáo PDF sinh viên đã nộp, DocumentIR thật, câu hỏi tiếng Việt tự nhiên) — không dùng benchmark public (CLINC150, RAGAS demo set...) để chấm điểm trực tiếp, vì domain khác nhau. Các benchmark public chỉ dùng để **tham khảo phương pháp luận và công thức metric**, trích dẫn trong phần Tài liệu tham khảo.

## 2. Kiến trúc đánh giá — 3 tầng năng lực

| Tầng | Intent tương ứng | Có gọi LLM? | Rủi ro chính cần đo |
|---|---|---|---|
| 1. Số liệu tổng hợp | SUMMARY, UNREVIEWED, REVIEW_REQUESTS, STUDENT_COUNT... | Không | Sai số liệu so với DB thật, lỗi khi thiếu scope (đã gặp lỗi 500) |
| 2. Tìm kiếm nội dung | SEARCH_CONTENT | Không | Bỏ sót đoạn liên quan (recall thấp), trả đoạn không liên quan (precision thấp) |
| 3. Câu trả lời sinh bởi LLM | ASK_ABOUT_REQUIREMENT, SUMMARIZE_SUBMISSION | Có | Trả lời sai lệch so với đoạn trích (faithfulness), trích dẫn bịa (citation hallucination) |
| 0. Hội thoại làm rõ | needs_clarification (course/assignment/submission) | Không | Hỏi lại khi không cần (phiền), hoặc không hỏi lại khi cần (trả lời sai phạm vi) |

Mỗi tầng có bộ metric riêng ở mục 3–6, vì bản chất rủi ro khác nhau — không dùng 1 metric chung cho cả 4 tầng.

## 3. Tầng 1 — Số liệu tổng hợp (rule-based, không LLM)

**Metric**:
- *Intent accuracy*: % câu hỏi test được `classify_intent()` gán đúng intent (theo nhãn người gán tay).
- *Out-of-scope rejection rate*: % câu hỏi ngoài phạm vi (không khớp intent nào, hoặc hỏi mơ hồ) được hệ thống nhận diện đúng là cần hỏi lại thay vì trả lời bừa.
- *Numeric correctness*: % câu trả lời có số liệu khớp 100% với truy vấn SQL trực tiếp trên cùng dữ liệu tại thời điểm hỏi (viết script đối chiếu tự động, không so bằng mắt).
- *Error rate*: % request trả lỗi 5xx trên tổng số câu hỏi test (mục tiêu: 0% sau khi sửa lỗi 500 đã phát hiện).

**Test set**: tối thiểu 10 câu hỏi/intent × số intent hiện có, cộng thêm 15–20 câu "nhiễu" (ngoài phạm vi, viết sai chính tả, không dấu, lẫn 2 ý trong 1 câu) lấy cảm hứng từ cách CLINC150 thiết kế tập out-of-scope.

## 4. Tầng 2 — Tìm kiếm nội dung (SEARCH_CONTENT, retrieval thuần)

**Metric** (theo tinh thần retrieval evaluation trong RAGAS — mục Tài liệu tham khảo):
- *Context Precision@k*: trong k đoạn trích trả về (hiện k=5–8), bao nhiêu % thực sự liên quan tới câu hỏi (gán nhãn tay trên tập gold).
- *Context Recall*: trong các đoạn thực sự chứa câu trả lời (xác định trước bằng tay trên toàn bộ tài liệu), bao nhiêu % được tìm thấy trong top-k.
- *Page/section accuracy*: % kết quả có đúng số trang + mục như gán nhãn tay.
- *Latency*: thời gian phản hồi trung bình (phải nhanh vì không gọi LLM — đặt ngưỡng ví dụ < 1s).

**Test set (gold set)**: chọn 5–10 báo cáo PDF thật đa dạng độ dài, với mỗi báo cáo chọn 5–8 câu hỏi tìm kiếm (từ khoá + diễn đạt khác đi, ví dụ hỏi "xác thực 2 lớp" khi tài liệu viết "two-factor authentication"), tự đọc toàn bộ tài liệu 1 lần để xác định gold answer (đoạn/trang nào thực sự chứa thông tin) trước khi chạy hệ thống — làm đúng thứ tự này để tránh thiên vị (không được xác định gold answer sau khi đã thấy kết quả hệ thống trả về).

**Lưu ý về gold set "multi-relevant" (bổ sung 2026-10-03, sau lần đo đầu tiên)**: gold cho mỗi câu hỏi là một **danh sách** vị trí thực sự liên quan (1, 2, hoặc nhiều đoạn/section) — không phải đúng 1 vị trí duy nhất. Lần đo đầu tiên dùng gold "single-relevant" (đúng 1 vị trí/câu) đã cho Context Precision@k ~21% dù retrieval đúng hoàn toàn, vì với k=6 cố định, khi 1 câu hỏi hẹp chỉ thực sự có 1 đoạn liên quan trong cả tài liệu, precision tối đa lý thuyết của một retriever hoàn hảo cũng chỉ là 1/6 ≈ 17% — ngưỡng ≥70% không có ý nghĩa trong trường hợp đó, bất kể hệ thống tốt hay dở.

Vì vậy, bên cạnh Context Precision@k đo được, cần tính thêm **ngưỡng lý thuyết tối đa** cho từng câu: đếm toàn bộ **chunk** (không phải section) trong kho chunk của tài liệu thật sự khớp với gold (một section gold có thể trải trên nhiều chunk, nên số chunk liên quan thường lớn hơn số vị trí gold đã liệt kê) — ngưỡng = min(1, số_chunk_liên_quan / k). So sánh precision đo được với ngưỡng này (không phải với 70% cố định) mới thực sự cho biết retrieval có vấn đề hay không. Xem `backend/evaluation/scoring.py::theoretical_max_precision` và README phần "Known scoping decisions" để biết chi tiết cách tính.

## 5. Tầng 3 — Câu trả lời sinh bởi LLM (ASK_ABOUT_REQUIREMENT, SUMMARIZE_SUBMISSION)

**Metric** (theo RAGAS + ALCE — xem Tài liệu tham khảo):
- *Faithfulness*: % câu khẳng định trong câu trả lời có thể suy ra trực tiếp từ các đoạn trích đã gửi cho LLM (không bịa thêm thông tin ngoài context).
- *Citation precision*: trong các trích dẫn [chunk:id] mà câu trả lời đưa ra, bao nhiêu % thực sự hỗ trợ đúng câu đó (không trích dẫn sai chỗ).
- *Citation recall*: các câu khẳng định cần trích dẫn có đều được trích dẫn không (không bỏ sót).
- *Answer relevancy*: câu trả lời có thực sự trả lời đúng câu hỏi hay lạc đề/chung chung.
- *Summarization structure score* (riêng SUMMARIZE_SUBMISSION): chấm theo thang 1–5 xem bản tóm tắt có đủ 3 phần đã yêu cầu (mục tiêu, phạm vi, điểm chính) không, và có bỏ sót phần quan trọng nào của tài liệu gốc không.
- *Cache correctness*: hỏi tóm tắt 2 lần liên tiếp cùng 1 bài → lần 2 phải lấy từ `document_summaries` (không gọi LLM lại) — đo bằng cách log số lần gọi LLM API, không đo bằng mắt.

**Cách chấm**: faithfulness/citation precision-recall chấm bằng tay trên tập nhỏ trước (10–15 câu trả lời) để hiệu chỉnh tiêu chí, sau đó có thể dùng phương pháp LLM-as-judge (xem mục 8) để mở rộng số lượng mẫu mà không cần tự đọc hết — nhưng luôn giữ lại 1 tập chấm tay làm "ground truth" để kiểm tra LLM-judge có đáng tin không trước khi tin kết quả của nó.

**Test set**: 15–20 câu hỏi loại ASK_ABOUT_REQUIREMENT trải trên nhiều báo cáo, 8–10 yêu cầu tóm tắt trên các báo cáo có độ dài khác nhau (ngắn/trung bình/dài, để test cả nhánh map-reduce).

## 6. Tầng 0 — Hội thoại làm rõ phạm vi (needs_clarification)

**Metric**:
- *Clarification precision*: trong các lần hệ thống hỏi lại, bao nhiêu % là thực sự cần thiết (câu hỏi thực sự nhập nhằng/thiếu scope) — tránh hỏi lại vô ích làm phiền giảng viên.
- *Clarification recall*: trong các câu hỏi thực sự thiếu/nhập nhằng scope, bao nhiêu % được hệ thống phát hiện đúng và hỏi lại (thay vì tự đoán bừa 1 lớp/bài nộp).
- *Resolution success rate*: sau khi giảng viên chọn 1 option, % trường hợp hệ thống trả lời đúng câu hỏi gốc ngay (không phải hỏi lại vòng 2).
- *Turns to answer*: số lượt hỏi-đáp trung bình để ra được câu trả lời cuối cùng (càng thấp càng tốt, nhưng phải cân bằng với precision ở trên).

**Test set**: dựng kịch bản cố ý — không chọn lớp, chọn lớp nhưng không chọn bài tập, hỏi tên sinh viên trùng tên trong cùng lớp, và đối chứng: câu hỏi đủ rõ ràng không cần hỏi lại (để đo Clarification precision không bị hỏi lại thừa).

## 7. Quy trình xây dựng test set chuẩn (gold set)

1. Chọn cố định 1 bộ dữ liệu neo (ví dụ 8 báo cáo PDF thật, 1–2 lớp, khoảng 30–40 bài nộp) — **không đổi bộ này giữa các lần đánh giá**, để kết quả so sánh được qua thời gian.
2. Với mỗi câu hỏi test, gán nhãn gold TRƯỚC khi chạy hệ thống (đọc tài liệu/DB thật, ghi lại đáp án đúng) — tránh việc nhìn kết quả hệ thống rồi mới quyết định đúng/sai.
3. Lưu toàn bộ test set dưới dạng file version-hoá trong repo (ví dụ `backend/evaluation/golden_set.jsonl`), mỗi dòng gồm: câu hỏi, scope (course/assignment/submission), intent kỳ vọng, đáp án/đoạn trích gold, nguồn gold (ai gán, ngày gán).
4. Mỗi lần có thay đổi lớn (đổi embedding provider, đổi prompt, đổi chunking) → chạy lại toàn bộ test set, không chạy tay từng câu.

## 8. Công cụ & cách tính

- Metric tầng 2–3 (precision/recall/faithfulness): có thể dùng thư viện **RAGAS** (Python, `pip install ragas`) để tính tự động theo công thức chuẩn, thay vì tự viết lại — xem [RAGAS paper] trong Tài liệu tham khảo.
- Citation precision/recall (tầng 3): viết script nhỏ so khớp `[chunk:id]` trong câu trả lời với tập chunk gold đã gán nhãn — logic tương tự nguyên tắc ALCE.
- Nếu dùng LLM-as-judge để mở rộng quy mô chấm điểm (mục 5): áp dụng đúng phương pháp luận trong paper MT-Bench/Chatbot Arena, bao gồm cả việc nhận biết hạn chế (thiên vị độ dài, thiên vị với câu trả lời "tự tin") trước khi trích dẫn kết quả vào luận văn.
- Toàn bộ script đánh giá nên đặt trong `backend/evaluation/`, chạy được bằng 1 lệnh (`uv run python -m evaluation.run_all`), xuất ra 1 file kết quả (CSV/JSON) có timestamp — để lưu lại lịch sử qua từng lần chạy.

## 9. Lịch đánh giá định kỳ & theo dõi hồi quy

- Chạy lại toàn bộ bộ test mỗi khi: đổi provider (embedding/LLM), đổi prompt hệ thống, đổi logic chunking/retrieval, hoặc trước mỗi mốc nộp báo cáo luận văn.
- Lưu kết quả mỗi lần chạy (kèm ngày, commit hash) vào 1 bảng theo dõi theo thời gian — đây chính là nguồn dữ liệu cho biểu đồ "cải thiện qua các phiên bản" trong luận văn.
- Nếu 1 metric giảm so với lần chạy trước mà không giải thích được lý do → coi là hồi quy, cần điều tra trước khi tiếp tục.

## 10. Cách trình bày kết quả cho báo cáo luận văn

- Trình bày theo đúng cấu trúc 4 tầng ở mục 2 — mỗi tầng 1 bảng kết quả riêng (metric, giá trị đo được, ngưỡng kỳ vọng, đạt/không đạt).
- Nêu rõ kích thước test set ("N=45 câu hỏi trên 8 báo cáo thật") — không nêu % mà giấu N, vì N nhỏ cần ghi rõ để người đọc tự đánh giá độ tin cậy.
- Nếu có so sánh giữa các phiên bản (ví dụ trước/sau đổi embedding provider), trình bày dạng bảng hoặc biểu đồ theo thời gian, không chỉ nêu 1 con số cuối.
- Trích dẫn đúng các bài báo đã dùng làm cơ sở phương pháp luận (mục 11) ngay tại phần Phương pháp đánh giá của báo cáo, không chỉ liệt kê ở danh mục tham khảo.
- Nêu rõ giới hạn (mục 11) trong phần Thảo luận — hội đồng đánh giá cao việc tự nhận ra giới hạn hơn là che giấu.

## 11. Giới hạn của phương pháp đánh giá

- Test set tự xây dựng có quy mô nhỏ (vài chục câu hỏi) — không đại diện thống kê đầy đủ như benchmark public hàng nghìn mẫu; kết quả chỉ có giá trị *so sánh nội bộ qua thời gian*, không nên diễn giải là "độ chính xác tổng quát của hệ thống".
- Nhãn gold do 1 người tự gán (không có nhiều người gán độc lập để tính độ đồng thuận liên-đánh-giá-viên) — nên nêu rõ trong luận văn đây là giới hạn, không phải thiếu sót che giấu.
- LLM-as-judge (nếu dùng) có thiên vị đã biết (thiên vị độ dài câu trả lời, thiên vị thứ tự) — chỉ dùng để mở rộng quy mô, luôn đối chiếu với tập chấm tay nhỏ.
- Metric tầng 3 phụ thuộc vào chất lượng LLM provider tại thời điểm đo — nếu đổi model/provider, kết quả cũ không còn so sánh trực tiếp được.

## 12. Tài liệu tham khảo (cơ sở phương pháp luận)

- Es, S. et al. "RAGAS: Automated Evaluation of Retrieval Augmented Generation." EACL 2024. https://aclanthology.org/2024.eacl-demo.16/
- Gao, T. et al. "Enabling Large Language Models to Generate Text with Citations" (ALCE). EMNLP 2023. https://arxiv.org/abs/2305.14627
- Yu, H. et al. "Evaluation of Retrieval-Augmented Generation: A Survey." 2024. https://arxiv.org/abs/2405.07437
- "Benchmarking LLM Faithfulness in RAG with Evolving Leaderboards." 2025. https://arxiv.org/abs/2505.04847
- Zheng, L. et al. "Judging LLM-as-a-Judge with MT-Bench and Chatbot Arena." 2023. https://arxiv.org/abs/2306.05685
- Larson, S. et al. "An Evaluation Dataset for Intent Classification and Out-of-Scope Prediction" (CLINC150). EMNLP 2019. https://arxiv.org/abs/1909.02027
- UIT NLP Group — bộ dữ liệu QA/NLP tiếng Việt (UIT-ViQuAD, ViNewsQA...). https://nlp.uit.edu.vn/datasets/

## 13. Phụ lục — Bảng tổng hợp nhanh toàn bộ metric

| # | Tầng | Metric | Công thức/cách đo | Ngưỡng đề xuất |
|---|---|---|---|---|
| 1 | 1 | Intent accuracy | đúng/tổng câu test | ≥ 95% |
| 2 | 1 | Out-of-scope rejection rate | đúng nhận diện/tổng câu ngoài phạm vi | ≥ 90% |
| 3 | 1 | Numeric correctness | khớp SQL đối chiếu/tổng | 100% |
| 4 | 1 | Error rate (5xx) | lỗi/tổng request test | 0% |
| 5 | 2 | Context Precision@k | đoạn liên quan/k đoạn trả về (so với ngưỡng lý thuyết tối đa — xem mục 4) | ≥ 70% *(hoặc ≥ ~90% của ngưỡng lý thuyết tối đa nếu ngưỡng đó < 70%/k)* |
| 6 | 2 | Context Recall | đoạn gold tìm thấy/tổng đoạn gold | ≥ 80% |
| 7 | 2 | Latency | thời gian phản hồi trung bình | < 1s |
| 8 | 3 | Faithfulness | câu khẳng định đúng theo context/tổng | ≥ 90% |
| 9 | 3 | Citation precision | trích dẫn đúng chỗ/tổng trích dẫn | ≥ 90% |
| 10 | 3 | Citation recall | câu cần trích dẫn có trích/tổng cần | ≥ 85% |
| 11 | 3 | Cache correctness | lần hỏi 2 không gọi LLM/tổng | 100% |
| 12 | 0 | Clarification precision | hỏi lại đúng cần thiết/tổng lần hỏi lại | ≥ 90% |
| 13 | 0 | Clarification recall | nhận diện đúng nhập nhằng/tổng case nhập nhằng | ≥ 90% |

*Ngưỡng đề xuất ở trên là điểm khởi đầu để tự đặt mục tiêu — điều chỉnh lại sau lần đo đầu tiên cho phù hợp thực tế dữ liệu của bạn, đừng coi là chuẩn cố định phải đạt ngay từ đầu.*
