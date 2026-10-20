# Note chốt phạm vi, luật nghiệp vụ và kiến trúc kỹ thuật

Ngày chốt: 21/08/2026

Sản phẩm: Hệ thống đánh giá chất lượng báo cáo; MVP nghiệm thu với rubric SRS

Trạng thái quyết định: Dùng làm baseline cho prototype, phát triển và nghiệm thu MVP

## 1. Kết luận

Xây một ứng dụng web độc lập cho ba vai trò **Admin, Giảng viên và Sinh viên**. Hệ thống nhận **PDF có text layer**, phân tích báo cáo theo rubric, tạo đề xuất điểm/nhận xét kèm bằng chứng, sau đó để giảng viên duyệt trước khi công bố cho sinh viên. Domain model hỗ trợ nhiều loại báo cáo, nhưng phạm vi tự động hóa và nghiệm thu trong một tháng chỉ áp dụng cho rubric SRS mặc định.

MVP không phải hệ thống chấm hoàn toàn tự động. Rule, thuật toán và LLM chỉ tạo **đề xuất**. Mọi điểm chính thức đều do giảng viên xác nhận. Tiêu chí tự động nào chưa đạt benchmark sẽ chuyển sang chế độ thủ công thay vì trả kết quả có vẻ chắc chắn nhưng không đáng tin.

Kiến trúc được chọn là **modular monolith có worker riêng**:

- Frontend: React + TypeScript + Vite.
- Backend/API: Python + FastAPI.
- Xử lý nền: Celery + Redis.
- Dữ liệu: PostgreSQL.
- PDF: PDF.js ở trình duyệt; pypdf và pdfplumber ở worker.
- Triển khai MVP: Docker Compose trên một máy chủ, không dùng Kubernetes hoặc microservice.

Repository hiện có frontend React/Vite nối trực tiếp session auth, Course, roster sinh viên, Assignment, Rubric, upload PDF, trạng thái job, Submission Queue, PDF.js review viewer với evidence hai chiều, review draft/evidence, approve/publish, kết quả đã công bố, yêu cầu xem lại theo criterion, Teacher/Admin xử lý yêu cầu, notification center và Admin dashboard/user/job/audit/force-release; backend đã triển khai domain, authorization và API nghiệp vụ tương ứng đến T-026 cùng API tạo tài khoản Admin. Product UI chưa nối luồng nộp lại/so sánh version; luồng đó tiếp tục ẩn cho đến khi frontend tương ứng hoàn tất.

## 2. Mục tiêu sản phẩm

### 2.1. Vấn đề cần giải quyết

- Giảng viên mất nhiều thời gian kiểm tra cấu trúc, độ đầy đủ, tính nhất quán và khả năng truy vết của SRS.
- Nhận xét dễ thiếu bằng chứng, không đồng đều giữa nhiều bài hoặc khó quay lại đúng vị trí trong tài liệu.
- Sinh viên thường chỉ nhìn điểm tổng và khó hiểu tiêu chí nào cần sửa.
- Kết quả từ AI có thể không ổn định, vì vậy không được thay thế quyết định chuyên môn của giảng viên.

### 2.2. Kết quả mong muốn

- Giảng viên đọc PDF, rubric, phát hiện và bằng chứng trong cùng một workspace.
- Mọi đề xuất tự động có thể được chấp nhận, chỉnh sửa hoặc loại bỏ.
- Sinh viên chỉ thấy phiên bản kết quả đã công bố và có thể mở đúng bằng chứng trong PDF.
- Admin quản lý tài khoản, rubric mặc định, job lỗi và audit log mà không phải vận hành một hệ thống hạ tầng phức tạp.

### 2.3. Chỉ số thành công của MVP

- 100% kết quả công bố đã qua thao tác duyệt của giảng viên.
- 100% finding tự động được hiển thị có criterion, trang và bằng chứng kiểm tra được.
- Không có trường hợp sinh viên xem được kết quả chưa công bố hoặc tài liệu của người khác.
- Ít nhất 90% PDF hợp lệ trong bộ kiểm thử hoàn tất phân tích trong 10 phút trên môi trường tham chiếu.
- Ít nhất 80% phiên review thử nghiệm hoàn thành mà người dùng không phải rời workspace chính để tìm rubric hoặc bằng chứng.

## 3. Phạm vi MVP một tháng

### 3.1. Trong phạm vi

1. Đăng nhập bằng tài khoản được Admin tạo; không có đăng ký công khai.
2. RBAC cho Admin, Giảng viên và Sinh viên; tài khoản nhiều vai trò dùng workspace theo quyền mạnh nhất theo thứ tự `ADMIN`, `TEACHER`, `STUDENT` để khớp authorization backend và tránh rơi xuống nhánh quyền yếu hơn.
3. Tạo Course, tạo Assignment trong Course, chọn rubric, cấu hình tiêu chí/trọng số, lưu nháp, mở và đóng nhận bài.
4. Catalog mặc định gồm 12 tiêu chí SRS baseline và tiêu chí bổ sung `ACC-01`; Rubric Builder cho chọn tiêu chí, xem mô tả/nội dung chấm/công thức điểm, cấu hình trọng số và lưu trực tiếp.
5. Sinh viên upload PDF, xem điều kiện file trước khi nộp, nhận lỗi theo trang và theo dõi trạng thái xử lý.
6. Validation PDF, lưu file riêng tư, tạo checksum, tạo phiên bản bài nộp và job xử lý bất đồng bộ.
7. Trích xuất text, heading, section, bảng, requirement ID, use case và tọa độ bằng chứng thành Document IR.
8. Đánh giá hybrid bằng rule/parser và LLM theo từng tiêu chí; đầu ra có schema cố định và bằng chứng.
9. Workspace review: PDF bên trái, rubric/finding bên phải, liên kết hai chiều giữa finding và bằng chứng.
10. Giảng viên chấp nhận, sửa, loại bỏ, thêm nhận xét, tái sử dụng comment mẫu, nhập mức rubric, lưu tự động, giữ soft lock và chuyển tới bài chưa duyệt tiếp theo.
11. Công bố tách khỏi duyệt; chỉ kết quả đã duyệt mới được công bố, kể cả khi công bố hàng loạt; thu hồi kết quả là hành động đặc quyền có lý do và audit.
12. Sinh viên xem điểm tổng, breakdown, feedback ghim, annotation và so sánh với lần nộp liền trước.
13. Sinh viên gửi một yêu cầu xem lại gắn với tiêu chí của một phiên bản kết quả đã công bố.
14. Admin quản lý người dùng, rubric/template mặc định, danh sách job, thử lại job, usage cơ bản và audit log.
15. Thông báo trong ứng dụng khi AnalysisJob chuyển `ERROR`, tạo `PublishedResultVersion`, tạo ReviewRequest và chuyển ReviewRequest sang `RESOLVED` hoặc `REJECTED`; MVP dùng polling, không có push/email/websocket. Thông báo khi unpublish theo BR-33 được hoãn sang `DOC-30`.
16. Teacher sở hữu Course hoặc Admin xem roster, thêm sinh viên bằng email, tạo invite chờ khi email chưa có tài khoản và soft-remove membership mà không xóa Submission/Result lịch sử.
17. Teacher sở hữu Course hoặc Admin tạo, đổi hạn, revoke và regenerate join code; Student mở link/QR hoặc nhập code rồi xác nhận để tự tham gia Course.
18. Account center cho cả ba vai trò gồm Profile, Notifications, Files và Settings. Profile chỉ cho tự sửa display name; email, role và trạng thái là read-only. Settings cho đổi mật khẩu sau khi xác minh mật khẩu hiện tại và thu hồi các session khác. Files là danh sách DocumentVersion theo quyền: Admin xem toàn hệ thống, Teacher xem Course mình phụ trách, Student chỉ xem bài của mình; upload vẫn chỉ diễn ra trong luồng nộp bài.
19. Admin Analysis và Monitoring dùng aggregate vận hành thật: trạng thái job, queue depth/age, xu hướng throughput và lỗi bảy ngày, phân bổ submission theo Course và trạng thái review request. Biểu đồ luôn có số liệu hoặc bảng thay thế cho screen reader, cùng loading, empty và error state riêng.

Evaluator tự động của MVP chỉ được nghiệm thu cho SRS tiếng Việt. SRS tiếng Anh hoặc tài liệu thuộc ngôn ngữ khác vẫn có thể dùng rubric thủ công nếu PDF hợp lệ; chỉ được bật tự động sau khi có corpus và qua quality gate riêng.

### 3.2. Ngoài phạm vi

- OCR, PDF scan và PDF trộn trang scan.
- DOC/DOCX, Google Docs hoặc định dạng đầu vào khác PDF.
- Kiểm tra đạo văn, phát hiện nội dung do AI viết hoặc viết lại tài liệu cho sinh viên.
- Chấm hoàn toàn tự động hoặc tự công bố kết quả.
- LMS/LTI, email, SMS, push notification và đăng nhập SSO.
- Ứng dụng mobile native; mobile chỉ hỗ trợ xem trạng thái/kết quả cơ bản.
- Đồng chỉnh sửa thời gian thực, anonymous grading, phân công nhiều người chấm nâng cao và moderation workflow.
- Công thức tùy chỉnh, rule builder hoặc chạy code do người dùng cung cấp.
- Dashboard BI tổng quát, mô hình dự báo, billing, multi-tenant hoặc marketplace rubric. Các biểu đồ vận hành giới hạn tại mục 3.1 vẫn trong phạm vi.
- Tự host LLM, fine-tuning, GPU server, Kubernetes và kiến trúc microservice.
- Evaluator tự động đã được đảm bảo chất lượng cho loại báo cáo khác SRS; loại khác chỉ dùng rubric thủ công cho tới khi có corpus và qua quality gate riêng.

### 3.3. Điều kiện để phạm vi một tháng khả thi

- Nhóm tối thiểu: hai kỹ sư làm toàn thời gian, một người tập trung frontend/UX và một người tập trung backend/PDF/AI; có giảng viên hoặc domain reviewer tối thiểu 4 giờ mỗi tuần.
- Dùng dịch vụ LLM qua API; không huấn luyện hoặc vận hành model riêng.
- Có tối thiểu 30 SRS tiếng Việt đã ẩn danh để benchmark, với mức rubric do giảng viên xác nhận cho từng tiêu chí.
- Môi trường triển khai là một máy chủ Linux 8 vCPU, 16 GB RAM, SSD; LLM nằm ngoài máy chủ.
- Nếu chỉ có một developer trong một tháng, release bắt buộc giảm còn upload, ba tiêu chí rule-based, review, duyệt và công bố; không được hạ quality gate để giữ số lượng chức năng.

## 4. Catalog tiêu chí mặc định và rubric SRS baseline

Rubric dùng thang mức **0–4**. Điểm phần trăm của một tiêu chí bằng `mức / 4 × trọng số`. Điểm tổng là tổng điểm phần trăm; giao diện có thể hiển thị thêm thang 10 bằng cách chia cho 10. Hệ thống không tự kết luận đậu/rớt vì đây là chính sách môn học, không phải thuộc tính chất lượng SRS.

Hệ thống lưu điểm với tối thiểu bốn chữ số thập phân, chỉ làm tròn khi hiển thị: một chữ số cho thang 10 và hai chữ số cho phần trăm. Publish snapshot lưu cả mức từng tiêu chí, trọng số và điểm chưa làm tròn để việc tính lại không bị sai số tích lũy.

| ID | Tiêu chí | Trọng số | Phương pháp đề xuất trong MVP |
|---|---|---:|---|
| SRS-01 | Đúng cấu trúc và template bắt buộc | 7% | Rule + parser |
| SRS-02 | Heading, mục lục và section rỗng | 5% | Rule + parser |
| SRS-03 | Bảng, hình và caption | 3% | Rule + parser |
| SRS-04 | Requirement ID và tính nguyên tử | 7% | Rule + NLP |
| SRS-05 | Rõ ràng, không mơ hồ | 7% | Rule + NLP + LLM |
| SRS-06 | Đầy đủ và kiểm thử được | 9% | Rule + LLM |
| SRS-07 | Nhất quán giữa các phần | 7% | Rule + LLM |
| SRS-08 | Độ đầy đủ của Use Case | 8% | Rule + parser |
| SRS-09 | Logic của luồng Use Case | 12% | Rule + LLM |
| SRS-10 | Truy vết Actor–Use Case–Requirement | 15% | Rule + quan hệ + LLM |
| SRS-11 | Thuật ngữ, chính tả và văn phong | 10% | Rule + NLP |
| SRS-12 | Tính mạch lạc tổng thể | 10% | LLM + duyệt |
| ACC-01 | Accuracy — thuật ngữ, kiến thức và citations | 10% đề xuất | Citation identity/linkage deterministic + duyệt thủ công |

`SRS-01`–`SRS-12` là rubric baseline có tổng trọng số 100%. `ACC-01` là lựa chọn bổ sung trong catalog; khi thêm, giảng viên phải cân lại trọng số để rubric vẫn bằng 100%. Phần có tính điểm của `ACC-01` chỉ gồm kiểm chứng citation thường: metadata/identity, mention-reference linkage và đối chiếu thủ công thuật ngữ/kiến thức với nguồn. Semantic claim–source chỉ được hiển thị như phạm vi dự kiến, không lưu evaluator `CITATION_SEMANTIC`, không tạo điểm và không ảnh hưởng tổng điểm cho tới khi quality gate được phê duyệt.

Ý nghĩa mức:

- `0 — Không đạt`: thiếu hoặc sai bản chất; không có bằng chứng đáp ứng.
- `1 — Yếu`: có dấu hiệu đáp ứng nhưng lỗi nghiêm trọng hoặc thiếu phần lớn.
- `2 — Một phần`: đáp ứng một phần; còn lỗi ảnh hưởng khả năng hiểu hoặc sử dụng.
- `3 — Tốt`: đáp ứng phần lớn; chỉ còn lỗi cục bộ, không nghiêm trọng.
- `4 — Đạt đầy đủ`: đáp ứng yêu cầu của tiêu chí và không có lỗi đáng kể trong phạm vi kiểm tra.

Rubric có thể thay đổi metadata, trọng số, evaluator hoặc tiêu chí cho tới khi Assignment tham chiếu nhận bài đầu tiên. Khi mở Assignment, rubric phải có ít nhất một tiêu chí đang bật, mỗi tiêu chí đủ mức 0–4 và tổng trọng số chính xác 100%.

## 5. Mô hình nghiệp vụ và trạng thái

### 5.1. Thực thể chính

- `User`, `Role`, `Course`, `CourseMembership`, `CourseInvite`, `CourseJoinCode`, `Assignment`.
- `RubricVersion`, `CriterionVersion`, `PerformanceLevel`, `TemplateVersion`.
- `Submission`, `DocumentVersion`, `DocumentStatusEvent`, `AnalysisJob`.
- `EvaluationResult`, `CriterionResult`, `Finding`, `EvidenceAnchor`.
- `ReviewDraft`, `ReviewDecision`, `ReviewLock`, `PublishedResultVersion`, `ReviewRequest`.
- `Notification`, `AuditEvent`.

### 5.2. Vòng đời Course

```text
ACTIVE → ARCHIVED
```

- `ARCHIVED` chỉ đọc, vẫn giữ lịch sử Assignment, Membership, CourseInvite và audit.
- Muốn mở Course mới phải tạo Course khác; không unarchive hoặc ghi đè Course đã archive.

### 5.3. Vòng đời Assignment

```text
DRAFT → OPEN → CLOSED → ARCHIVED
```

- Chỉ `OPEN` nhận bài mới và chấp nhận lần completion đầu tiên; API completion phải khóa cả Assignment và `DocumentVersion`, rồi kiểm tra lại `status` cùng `due_at`. Một document đã completion vẫn trả lại job hiện có theo hợp đồng idempotent dù Assignment đóng hoặc quá hạn sau đó.
- `CLOSED` không nhận phiên bản mới hoặc completion đầu tiên nhưng giảng viên vẫn có thể review và công bố.
- `ARCHIVED` chỉ đọc; muốn sử dụng lại phải nhân bản thành đợt mới.

### 5.4. Vòng đời một phiên bản bài nộp

```text
UPLOADING → VALIDATING ──→ INVALID
                  ↓
               QUEUED → PROCESSING → AWAITING_REVIEW → APPROVED → PUBLISHED
                            └──────→ PROCESSING_FAILED
```

- `INVALID` cần sinh viên nộp file khác.
- `PROCESSING_FAILED` là lỗi hệ thống; Admin/Giảng viên có thể thử lại mà không yêu cầu upload lại. Riêng lỗi `STORAGE_UNAVAILABLE` xảy ra trước khi tạo job cho phép gọi lại completion của cùng document, không phụ thuộc cửa sổ presign cũ nhưng vẫn phải qua khóa và cổng `OPEN`/`due_at` của Assignment.
- `APPROVED` và `PUBLISHED` là hai trạng thái riêng.
- Nộp lại tạo `DocumentVersion` mới; không ghi đè phiên bản cũ.

### 5.5. Vòng đời job phân tích

```text
QUEUED → RUNNING → DONE
              └──→ ERROR ──retry──→ QUEUED
```

- Mỗi tổ hợp `DocumentVersion + RubricVersion` dùng đúng một `AnalysisJob` bền vững; retry và recovery sau worker loss đặt lại chính row đó, không tạo job hoặc kết quả giả.
- Worker claim bằng khóa hàng PostgreSQL, bỏ qua row đã bị worker khác khóa và kiểm tra lại `QUEUED` hoặc `RUNNING` đã hết lease sau khi có khóa. Worker đang chạy cập nhật heartbeat; nếu redelivery tới khi lease còn hiệu lực, Celery task retry có countdown bằng phần lease còn lại thay vì ack và làm mất đường recovery. Job stale được claim lại khi còn attempt, hoặc chuyển `ERROR` khi hết attempt. Mỗi heartbeat và chuyển trạng thái terminal dùng `attempt_count` đã claim làm generation compare-and-set; worker cũ mất lease không thể gia hạn hoặc ghi đè kết quả của attempt mới.
- Mọi transaction có thể commit một job ở trạng thái `QUEUED` tạo duy nhất một `AnalysisJobDispatch` trong chính transaction PostgreSQL đó. API thử publish sau commit; poller lifespan của FastAPI tiếp tục drain row đến hạn theo lô giới hạn, `FOR UPDATE SKIP LOCKED` và backoff. Chỉ xóa dispatch sau khi Redis chấp nhận message; broker lỗi không đổi phản hồi `202` và không làm mất wake-up bền vững.
- Mỗi chuyển trạng thái job `QUEUED`, `RUNNING`, `DONE`, `ERROR` và `ERROR → QUEUED` được ghi `AuditEvent` trong cùng transaction với thay đổi nghiệp vụ. Claim đồng thời chuyển `DocumentVersion` sang `PROCESSING`; hoàn tất ingestion chuyển sang `AWAITING_REVIEW`; cả hai chuyển trạng thái document đều được audit trong cùng transaction.

## 6. Luật nghiệp vụ

| ID | Luật đã chốt |
|---|---|
| BR-01 | Admin quản lý toàn hệ thống; Giảng viên chỉ quản lý Course, Assignment, Announcement, rubric và bài thuộc phạm vi được giao; Sinh viên chỉ đọc Course/Assignment/Announcement có membership `ACTIVE` và thao tác với bài của chính mình. Course ngoài phạm vi trả `404` để không lộ sự tồn tại. Mọi API phải kiểm tra quyền theo object, không chỉ ẩn nút trên UI. |
| BR-02 | Không có đăng ký công khai. Admin tạo, khóa hoặc mở khóa tài khoản. Admin không được tự bỏ role `ADMIN` hoặc tự khóa tài khoản; cập nhật đồng thời phải luôn giữ ít nhất một Admin đang `ACTIVE`. Mật khẩu tối thiểu 12 ký tự và được băm bằng Argon2id. |
| BR-03 | Giảng viên tạo, lưu, sửa và xóa rubric trực tiếp; không có bước publish rubric hoặc tạo version trong luồng UI/API. Rubric đã được Assignment tham chiếu không thể xóa. Khi bất kỳ Assignment tham chiếu nhận bài đầu tiên, rubric và toàn bộ tiêu chí bị đóng băng bằng service guard và database trigger để mọi sinh viên trong Assignment dùng cùng cấu hình chấm. Các cột `RubricVersion`/`CriterionVersion`, status và version number hiện hữu chỉ còn là chi tiết tương thích dữ liệu lịch sử. |
| BR-04 | Rubric Builder dùng catalog gồm 12 tiêu chí SRS baseline và `ACC-01` bổ sung. Khi chọn tiêu chí, UI phải hiển thị mô tả, các nội dung được chấm, evaluator, thang mức 0–4 và công thức `mức / 4 × trọng số`. Với `ACC-01`, UI phải tách rõ kiểm chứng citation thường đang tính điểm khỏi semantic chưa tính điểm; payload criterion chỉ dùng `CITATION`, không dùng `CITATION_SEMANTIC`. Trước khi mở Assignment, rubric phải có ít nhất một tiêu chí đang bật, đủ mức 0–4 và tổng trọng số chính xác 100%; API kiểm tra lại, không tin trạng thái UI. |
| BR-05 | Mỗi job lưu snapshot của Course, Assignment, RubricVersion, CriterionVersion, rule version, model/provider và cấu hình xử lý. Khi job được tạo, route LLM `CITATION_SEMANTIC` đang `ACTIVE` được snapshot bằng route/config revision, provider, protocol, model, region, max token, call budget và credential revision; không lưu key, ciphertext hoặc credential fingerprint. Job đã queue không tự chuyển sang route/provider mới; credential bị disable, thiếu hoặc đổi revision làm model fail closed sang review thủ công. Semantic citation lưu thêm internal trace gồm evaluator/parser/Source-IR/retrieval/prompt version, config hash, model ID/region, call budget/count, token usage, latency, source hash/provenance và pair/evidence IDs; không nhân đôi raw prompt hoặc document text và không project trace này ra Teacher/Student API. Chạy lại cùng snapshot phải có thể truy nguyên kết quả. |
| BR-06 | Chỉ nhận file có magic bytes và MIME là PDF, tối đa 100 MB raw và 100 trang, không mã hóa/mật khẩu. Budget decoded stream độc lập là 50 MB; tăng giới hạn raw không làm tăng ngân sách giải nén. JavaScript, Launch, EmbeddedFiles, XFA, form có field thật, `/GoToE` và remote action tự động qua `/OpenAction`, `/AA` hoặc chuỗi `/Next` vẫn bị từ chối. Link annotation do người dùng click với `/URI` được chấp nhận; `/GoToR` chỉ được chấp nhận khi là action `/A` trực tiếp của `/Link` nằm trực tiếp trong mảng `/Annots` của page, có `/F` là PDF string hoặc `/Filespec` thật không chứa active content. Backend không resolve hoặc fetch target. `/StructTreeRoot` dùng traversal riêng có giới hạn và chống chu kỳ để metadata accessibility không chiếm budget active-content chung; `/AF`, `/EF` và active descendant bên trong vẫn bị từ chối. Mỗi lần validation lưu report có mã lỗi an toàn, disposition, page, bbox khi có và repair action; lỗi parser/hạ tầng ngoài taxonomy PDF phải là `PROCESSING_FAILED`, không được gán `PDF_MALFORMED`. Strict parser failure được chạy lại một lần bằng lenient parser nhưng vẫn giữ nguyên mọi budget và security check; chỉ kết quả vượt toàn bộ pipeline mới được nhận với warning `PDF_STRUCTURE_RECOVERED`. |
| BR-07 | Validator preflight page content, toàn bộ Form XObject stream và font resource stream (`/FontFile*`, `/ToUnicode`, stream-backed `/Encoding`) trước khi trích text; mỗi stream duy nhất chỉ bị tính một lần vào decoded budget trên toàn tài liệu. Trang có ít nhất 30 ký tự hữu ích bỏ qua raster geometry nhưng vẫn áp dụng raw, decoded, page, structure và active-content budgets. Chỉ trang ít text chạy scan geometry: ảnh raster phủ từ 80% diện tích trang làm trang nghi scan và bị từ chối; trang trắng thật không tính là scan. Budget 10.000 geometry operations áp dụng độc lập cho từng trang được phân tích, kể cả Form lồng. Clipping Bézier `c`/`v`/`y` với `W` dùng bounding box control point làm conservative upper bound; path lồi đơn giản với `W` hoặc `W*` được đo chính xác. Geometry không thể phân tích an toàn bị từ chối bằng `PDF_SCAN_ANALYSIS_UNSUPPORTED`, không bị báo sai là malformed. |
| BR-08 | File gốc được lưu ngoài web root. Presigned POST chỉ ghi vào staging key. Completion phải kiểm tra metadata, rồi `CopyObject` có `CopySourceIfMatch` theo ETag sang sealed key ngẫu nhiên không xuất hiện trong credential upload; chỉ sealed key được lưu cho worker và download để presign còn hạn không thể ghi đè file đã nhận. Truy cập file dùng quyền theo object và URL ký có hạn 5 phút. Download phải `HEAD` sealed object trước khi ký; object bị mất trả `410` và yêu cầu nộp/khôi phục lại, không trả URL dẫn tới storage `404`. Development giữ thêm bản sealed copy nguyên tử trên volume dùng chung của API/worker và tự khôi phục object/bucket LocalStack bị mất sau restart; production tắt cơ chế local recovery và dùng backup của S3-compatible storage. Không lưu PDF blob trong PostgreSQL. |
| BR-09 | SHA-256 chỉ dùng nội bộ để nhận diện và kiểm tra tính toàn vẹn file, không làm nhãn chính trên giao diện. Upload lặp đúng cùng file cho cùng sinh viên, Assignment và lần nộp phải trả lại phiên bản hiện có thay vì tạo job trùng. |
| BR-10 | Tối đa một `AnalysisJob` bền vững cho một tổ hợp DocumentVersion + RubricVersion. Mọi transaction có thể commit job ở `QUEUED` phải tạo dispatch outbox cùng transaction; queue có thể giao việc lặp nhưng claim dùng khóa hàng và task phải idempotent. Retry dùng lại row hiện có, tối đa ba lần; lỗi hệ thống đồng thời chuyển DocumentVersion sang `PROCESSING_FAILED`. |
| BR-11 | Mọi finding tự động phải có criterion, phương pháp, mô tả, page number, text quote và tọa độ hoặc section anchor. File integrity đối chiếu label URL hiển thị với target `/URI` hoặc `/GoToR` mà không resolve/fetch mạng; mismatch tạo finding và evidence anchor theo bbox của link, target không đủ dữ liệu chuyển review thủ công. Citation evaluator deterministic nhận diện bibliography, numeric/author-year marker, DOI/arXiv ID và liên kết mention-reference, không dùng LLM. Crossref xử lý DOI và bibliographic search với giới hạn của Crossref: 1 request/s, 1 kết nối; 3 request/s, 3 kết nối khi đặt `CITATION_CONTACT_EMAIL` (polite pool); 429/5xx/timeout gọi tối đa ba lần (hai lần retry) theo `Retry-After`, mỗi lần gọi đều giữ một slot của pacer chung, 404 không retry. Identity resolution của một job bị chặn bởi deadline `CITATION_RESOLUTION_DEADLINE_SECONDS` (mặc định 180 giây; không lần gọi hay lần chờ nào vượt deadline) và bởi breaker: sau ba lỗi transport liên tiếp từ một provider, job bỏ qua provider đó; reference chưa được xử lý giữ `UNRESOLVED`, không tính bất lợi cho sinh viên. arXiv Atom API xử lý tối đa 64 arXiv-only reference/job theo batch 32 ID, retry batch một lần, chỉ fallback tối đa tám single-ID request khi arXiv đã trả lời nhưng thiếu ID; miss được cache 5 phút. Reference không có ID mà Crossref không khớp được tìm theo title trên OpenAlex (tối đa 16 search/job; `OPENALEX_API_KEY` tùy chọn nâng ngân sách miễn phí; 429 dừng search của job); DOI Crossref không đăng ký (ví dụ DataCite DOI của arXiv) tra OpenAlex theo DOI; khi arXiv API không trả lời (503), arXiv ID được tra qua DataCite DOI `10.48550/arxiv.<id>` trên OpenAlex. Ứng viên từ search chỉ được nhận khi title khớp, họ của một trong ba tác giả đầu xuất hiện trong reference và năm lệch tối đa một. So khớp identity đối chiếu title của provider với cả chuỗi reference gốc sau khi bỏ khoảng trắng/ký tự (chịu được chữ dính và title bị parse sai trường, trừ khi chuỗi đó nằm trong venue), chấp nhận năm lệch một (preprint so với kỷ yếu), venue so theo từ chính và tiền tố viết tắt; reference có DOI/arXiv ID in sẵn mà thiếu năm vẫn được xác minh bằng title + author. Unversioned arXiv-only metadata được bind sang exact `vN` trước persistent source cache. Resolver lỗi là `UNRESOLVED`, không tự coi citation giả. Finding citation hiển thị loại vấn đề, page và snippet có thể kiểm chứng; không hiển thị internal `mention-*`/`reference-*` hash cho người review. Khi bibliography có marker `[n]`, parser phải ưu tiên marker này, bỏ qua page range và paragraph chỉ chứa số trang thay vì tạo reference giả. Semantic citation chỉ chạy cho mention `LINKED` tới reference `VERIFIED`, giữ nguyên claim anchor và tạo Finding riêng thuộc criterion `CITATION_SEMANTIC`; kết quả exact-text an toàn có thể được xác nhận deterministic, còn kết quả khác tuân model budget và quality gate. |
| BR-12 | Nội dung PDF là dữ liệu không tin cậy. Chỉ gửi atomic claim, citation context và tối đa ba source passage đã truy hồi cho semantic model; nội dung tài liệu không được thay đổi system instruction, gọi tool đặc quyền hoặc quyết định quyền truy cập. Source acquisition đọc private operator cache theo key suy ra từ DOI/exact-version arXiv. Khi bật `SEMANTIC_SOURCE_FETCH_ENABLED`, cache miss của reference đã `VERIFIED` được tải: arXiv-only reference có exact `vN` từ fixed HTTPS arXiv PDF endpoint, không redirect; reference có DOI (in trong bài hoặc được Crossref/OpenAlex khớp khi xác minh; DOI DataCite arXiv `10.48550/arxiv.*` chỉ đi lane arXiv exact-version) từ tối đa hai vị trí `is_oa` mà OpenAlex liệt kê, tối đa 16 lần tra OpenAlex mỗi job, qua fetcher chỉ cho phép HTTPS cổng 443 tới địa chỉ công khai (kiểm tra lại từng redirect, không proxy). Mọi PDF tải về phải qua content-type/size/magic-byte/PDF-security/identity validation (DOI trong PDF, hoặc title + author) rồi mới ghi private cache; ghi lỗi thì từ chối source. URL trong report, search snippet, URL do LLM gợi ý, unversioned arXiv ID và bản không open-access/paywall không bao giờ được fetch. Cache không được expose qua presigned download; vận hành phải đặt lifecycle retention, aggregate outbound pacing giữa worker/replica và kiểm tra license khi dùng ngoài phân tích nội bộ. |
| BR-13 | LLM phải trả structured output theo JSON Schema và được Pydantic validate. Chỉ claim bằng toàn bộ passage sau NFKC/case-fold/whitespace/terminal-period normalization và cắt chính linked mention khi mention đó là trailing bracketed numeric citation marker mới được xác nhận deterministic mà không gọi model. Mathematical/comparison operators và unpaired internal punctuation phải được giữ; negation, Unicode quote, paired delimiter, author-year/superscript marker, unrelated trailing numeric text và mọi trường hợp không exact vẫn đi qua model/manual routing. Output lỗi schema được retry một lần; vẫn lỗi thì criterion chuyển thủ công, không suy đoán để điền dữ liệu. Semantic output chỉ chấp nhận evidence passage ID đã cung cấp và claim part là substring chính xác của claim. Provider exception, source thiếu/mismatch, abstract-only hoặc hết call budget phải deny-default sang `INSUFFICIENT_EVIDENCE`/`NEEDS_MANUAL_REVIEW`; quality gate/coverage không đạt thì không có điểm đề xuất. |
| BR-14 | Chỉ evaluator vượt quality gate cho đúng criterion và ngôn ngữ mới được bật. MVP chỉ kích hoạt tự động cho tiếng Việt. Criterion/ngôn ngữ không qua gate vẫn xuất hiện trong rubric nhưng không có điểm tự động; giảng viên nhập mức thủ công. Semantic Citation giữ score hỗ trợ và coverage tách biệt; quality gate bị khóa cho tới khi có bộ benchmark đã xác minh (ít nhất 100 claim-source pair human-gold với tối thiểu 20% double annotation độc lập, hoặc theo quyết định owner 2026-10-20 ít nhất 800 pair AI-verified theo rule v1.1 mà held-out judge xác nhận ≥95% nhãn), anchor đầy đủ, structured-output ≥99%, macro-F1 ≥0,80, false accusation `CONTRADICTED`/`IRRELEVANT` ≤2%, Hit@3 ≥0,90 cho đúng cấu hình triển khai (retrieval, model, prompt) và owner ký duyệt. |
| BR-15 | Điểm và nhận xét tự động luôn là đề xuất. Giảng viên phải chấp nhận, sửa hoặc loại bỏ các mục cần kiểm tra và xác nhận đủ 12 criterion trước khi duyệt. |
| BR-16 | Khi sửa mức hoặc structured semantic verdict do hệ thống đề xuất, giảng viên phải nhập lý do ngắn. `ReviewDecision.edited_semantic_verdict` chỉ nhận taxonomy semantic và chỉ được dùng với Finding có link trong semantic snapshot. Hành động của hệ thống và người dùng được ghi riêng trong audit log. |
| BR-17 | Autosave sau 800 ms không nhập liệu. API dùng optimistic concurrency bằng revision number; khi xung đột không được ghi đè âm thầm và phải cho người dùng chọn tải bản mới hoặc sao chép thay đổi của mình. |
| BR-18 | Một bài chỉ có một người giữ soft lock review tại một thời điểm. Lock hết hạn sau 10 phút không có heartbeat; người khác vẫn xem được nhưng không được sửa cho tới khi nhận lock. Admin có thể giải phóng lock và hành động phải được audit. |
| BR-19 | Duyệt không đồng nghĩa công bố. Chỉ `APPROVED` mới được publish. Publish là thao tác atomic trên toàn bộ result snapshot; không công bố từng criterion rời rạc. |
| BR-20 | Sau khi công bố, chỉnh sửa tạo `PublishedResultVersion` mới. Sinh viên mặc định thấy phiên bản mới nhất; phiên bản cũ được giữ cho audit và không bị sửa tại chỗ. |
| BR-21 | Sinh viên chỉ thấy finding được giảng viên chấp nhận hoặc tạo, feedback được phép công khai và kết quả đã publish; nội dung chính dùng tên, mã/tiêu đề criterion, tên file, mô tả finding và số trang thay cho UUID, SHA-256, bbox hoặc element ID; không thấy prompt, model detail, confidence thô, finding bị loại hoặc log nội bộ. |
| BR-22 | Nộp lại tạo `DocumentVersion` mới và phân tích lại bằng snapshot áp dụng tại thời điểm nộp. Finding, evidence, review draft/decision và published snapshot gắn với đúng DocumentVersion; draft của cùng reviewer unique theo `(document_version_id, reviewer_user_id)` nên lần nộp mới không được chuyển hoặc xóa dữ liệu review của lần cũ. Mọi thay đổi `DocumentVersion.status` mới được database trigger ghi append-only vào `DocumentStatusEvent`. Phiên bản có trước migration không được bịa lịch sử đã mất; API chỉ dựng timeline từ job/audit/current state đã lưu và đánh dấu `recorded=false`. Có thể mở kết quả read-only hoặc so sánh hai phiên bản bất kỳ được chọn trong cùng Submission theo score, review decision, comment và evidence đã lưu; không chấm lại hoặc diff pixel toàn bộ PDF. |
| BR-23 | Mỗi sinh viên chỉ có một review request đang mở cho một criterion của một PublishedResultVersion. Giảng viên trả lời và đóng yêu cầu; việc mở yêu cầu không tự thay đổi điểm. |
| BR-24 | LLM bên ngoài chỉ được dùng khi provider config đã được Admin xác nhận không dùng dữ liệu để huấn luyện, có chính sách lưu giữ phù hợp và text đã loại metadata/định danh có thể loại. API key chỉ nhận từ allowlist biến môi trường server hoặc input nhạy cảm của Admin; key lưu trong PostgreSQL phải dùng authenticated encryption với keyring riêng trong môi trường API/worker, key ID có version và binding theo credential/provider. Plaintext key không xuất hiện trong response, audit, log, job snapshot, Redis hoặc UI; UI chỉ hiển thị nguồn credential và hint đã che. Không đáp ứng điều kiện, credential bị disable/đổi revision hoặc giải mã lỗi thì toàn bộ LLM evaluator fail closed sang rule/review thủ công, không tự fallback provider. |
| BR-25 | Tối đa hai job đang hoạt động cho mỗi sinh viên và năm upload/phút/tài khoản. Vượt giới hạn trả lỗi có thời gian thử lại; không tạo job ngầm. |
| BR-26 | Document/result được giữ 365 ngày sau khi Assignment đóng; technical log 30 ngày; audit event 365 ngày. Xóa dữ liệu là job có audit, còn audit giữ định danh đã pseudonymize. |
| BR-27 | Việc tạo Notification trong ứng dụng nằm cùng transaction với sự kiện nguồn; lỗi ghi Notification phải rollback cả hai để không mất thông báo hoặc tạo trạng thái nửa vời. Mọi delivery bên ngoài được bổ sung sau này là best-effort sau commit và không rollback trạng thái nguồn. |
| BR-28 | Assignment cấu hình số lần nộp từ 1 đến 5, mặc định 3. Chỉ nhận bài khi Assignment ở trạng thái `OPEN`, chưa quá hạn và còn lượt; MVP không có late submission hoặc gia hạn riêng từng sinh viên. Giảng viên có thể đổi hạn chung trước khi đóng Assignment. |
| BR-29 | Rubric và trọng số được hiển thị cho sinh viên từ khi Assignment mở. Cấu hình evaluator, prompt, rule và ghi chú nội bộ không được hiển thị. |
| BR-30 | Review request chỉ được mở trong 7 ngày lịch từ thời điểm publish kết quả và trước khi Assignment bị archive. Hết hạn, sinh viên vẫn xem kết quả nhưng không tạo request mới. |
| BR-31 | Dry-run rubric dùng PDF mẫu riêng, không tạo Submission hoặc PublishedResult, vẫn ghi usage và evaluator snapshot. Mỗi rubric chỉ có một dry-run đang hoạt động; kết quả dry-run tự hết hạn sau 30 ngày. |
| BR-32 | Model/provider là cấu hình vận hành có version, không hard-code vào domain. Hệ thống hỗ trợ OpenAI, Anthropic Claude, Google Gemini, DeepSeek, OpenCode Zen và Amazon Bedrock qua fixed HTTPS/provider adapter; không nhận custom base URL từ người dùng. Mỗi task chỉ có tối đa một route `ACTIVE`; chỉ route có credential revision đã kiểm tra catalog, chính sách dữ liệu và quality approval mới được activate. Catalog check chỉ xác nhận credential/catalog access, không được gọi là generation health hoặc tự activate route. Thay model/provider không làm thay đổi kết quả hoặc route snapshot đã lưu. |
| BR-33 | Chỉ Teacher phụ trách hoặc Admin được unpublish. Thao tác phải có lý do, giữ nguyên PublishedResultVersion và audit, ẩn kết quả khỏi Student ngay lập tức và thông báo cho Student. Unpublish chặn review request mới nhưng không sửa request đã tồn tại; request đang mở chỉ kết thúc bằng `RESOLVED` hoặc `REJECTED`. |
| BR-J | Chỉ Teacher sở hữu Course hoặc Admin được xem và quản lý roster. Roster chỉ gồm membership `STUDENT`, hỗ trợ lọc `ACTIVE`/`REMOVED`, lưu thời điểm tham gia và nguồn `joined_via` (`MANUAL` hoặc `CODE`). Thêm tay chuẩn hóa email: tài khoản có role `STUDENT` được tạo membership `ACTIVE`; membership `REMOVED` được kích hoạt lại với thời điểm tham gia mới; tài khoản thiếu role `STUDENT` bị từ chối; email chưa có tài khoản tạo `CourseInvite` pending, chưa gửi email hoặc tự tạo membership trong T-026. Gỡ sinh viên là soft-remove sang `REMOVED`: mọi kiểm tra membership chặn truy cập hoặc submission mới, còn Submission, Result, audit và notification cũ giữ nguyên; hệ thống không tạo notification Course mới cho sinh viên đã gỡ. URL storage đã ký trước khi gỡ có thể dùng đến khi hết TTL tối đa 5 phút, nhưng API không cấp URL mới. Mọi lần thêm, kích hoạt lại, tạo invite hoặc gỡ phải ghi `AuditEvent` cùng transaction với actor, before/after và lý do do người thao tác nhập nếu có; Course `ARCHIVED` chỉ cho xem roster. |
| BR-J2 | Mỗi Course có tối đa một `CourseJoinCode` chưa revoke; code 20 ký tự Base32 không mơ hồ có 100 bit entropy và unique toàn hệ thống. Chỉ Teacher sở hữu Course hoặc Admin được tạo, đổi hạn, revoke, regenerate và xem QR/link; archived Course chỉ đọc. Link/QR chỉ chứa code. Student phải xác nhận trước khi join chính tài khoản của mình. Code sai, hết hạn và revoked trả lỗi phân biệt; revoke có hiệu lực ngay. Join lặp membership `ACTIVE` là idempotent; membership `REMOVED` được kích hoạt lại với `joined_via=CODE`. Regenerate không sửa membership cũ. Join bị rate-limit theo account và client IP; lifecycle code và join/reactivate đều có audit không chứa code, URL, email hoặc IP. |

## 7. Quality gate cho evaluator tự động

Gate được áp dụng **theo từng criterion**, không lấy điểm trung bình toàn hệ thống để che một criterion yếu.

### 7.1. Bộ benchmark

- Tối thiểu 30 PDF SRS tiếng Việt đã ẩn danh, phủ tài liệu tốt, trung bình và yếu.
- Mỗi PDF có mức 0–4 cho đủ 12 criterion và evidence do giảng viên xác nhận.
- Ít nhất 20% mẫu được hai người chấm độc lập để phát hiện rubric mơ hồ.
- Giữ riêng 20% PDF làm holdout; không dùng để viết rule, prompt hoặc few-shot example.


Citation v0 có baseline regression riêng tại
[`docs/benchmarks/citation-v0.md`](../benchmarks/citation-v0.md): chạy đủ 35 PDF
của issue #36, chấm extraction/linkage trên 11 PDF byte-set đã gán nhãn với 60
bibliography entries và 69 citation mentions, và chấm identity bằng fixed provider
records. Gold set này được review thủ công có AI hỗ trợ, chưa có reviewer độc lập,
nên không thay thế holdout/domain sign-off của quality gate.

Citation Semantic Support có baseline stage-wise riêng tại
[`docs/benchmarks/citation-semantic-v1.md`](../benchmarks/citation-semantic-v1.md).
Candidate set v0 có 120 pair `AI_DRAFT`/synthetic, chỉ là software-regression evidence.
Bộ v1 `AI_CONSENSUS` (900 pair, 149 paper arXiv giấy phép CC, claim tổng hợp tiếng Việt,
tiếng Anh và trộn) nhận nhãn theo rule v1.1 (audit judge Claude và thêm một họ model khác
cùng xác nhận nhãn dựng sẵn); held-out judge Gemini 3.8 Flash xác nhận 96,7% nhãn. Theo
quyết định owner 2026-10-20, bộ AI-verified này thay human gold cho quality gate. Kết quả
trên tập test ([`docs/benchmarks/citation-semantic-v1-ai-consensus.md`](../benchmarks/citation-semantic-v1-ai-consensus.md)):
evidence Hit@3 BM25 69,6% (tiếng Việt 48,1%), BGE-M3 + reranker 95,0%; prompt v2 với
encoder và `gemini-3.8-flash` đạt macro-F1 0,914–0,926, false accusation 0,3–0,9%, qua mọi
tiêu chí benchmark gate; với BM25 macro-F1 chỉ 0,748 và false accusation 7,5%. Gate artifact
tin cậy (`backend/app/services/semantic_quality_gates.json`, chỉ đổi qua pull request) đã có
entry cho cấu hình này nhưng đang chờ owner phê duyệt, nên điểm tự động vẫn chưa bật.
Retrieval dùng shared text encoder khi được cấu hình (mặc định self-host
`BAAI/bge-m3` + reranker qua Text Embeddings Inference), còn lại dùng BM25; chi tiết tại
[`docs/benchmarks/bge-m3-retrieval-2026-09-24.md`](../benchmarks/bge-m3-retrieval-2026-09-24.md).

### 7.2. Ngưỡng kích hoạt

Một criterion chỉ được bật tự động khi đồng thời đạt:

- Structured output hợp lệ 100% trên holdout sau retry cho phép; output lỗi luôn fallback thủ công.
- Evidence anchor đúng trang và trỏ tới nội dung thực từ 95% finding trở lên.
- Exact agreement với mức giảng viên từ 75% trở lên trên holdout.
- Agreement lệch không quá một mức từ 95% trở lên trên holdout.
- Không có finding hiển thị mà thiếu evidence có thể kiểm tra.
- Domain reviewer ký duyệt báo cáo benchmark của criterion.

Khi thay model, prompt chính, parser hoặc rule ảnh hưởng criterion, phải chạy lại gate. UI không hiển thị confidence số nếu confidence chưa được hiệu chuẩn trên benchmark.

## 8. Acceptance criteria của MVP

AT-01 đến AT-28 và AT-30 là release blocker. AT-29 là SLO vận hành phải được đánh giá sau tháng sử dụng đầu tiên.

### 8.1. Chức năng

| ID | Điều kiện nghiệm thu |
|---|---|
| AT-01 | Ba role đăng nhập được và 100% test truy cập chéo bị từ chối ở API; một sinh viên không thể suy đoán URL để đọc PDF/kết quả của sinh viên khác. |
| AT-02 | Giảng viên tạo được Course, CRUD Announcement và Assignment từ nháp tới mở nhận bài, xóa được Assignment Draft chưa có bài nộp, xem danh sách bài nộp theo từng Assignment và dry-run rubric trên PDF mẫu; hệ thống chặn mở khi rubric sai tổng trọng số hoặc thiếu level; sau hạn hoặc hết số lượt, upload bị từ chối mà không trừ thêm lượt. |
| AT-03 | Giảng viên tạo, lưu, sửa metadata/tiêu chí và xóa rubric chưa được Assignment tham chiếu mà không publish hoặc tạo version. Rubric còn được sửa khi Assignment chưa nhận bài; sau bài đầu tiên, service và PostgreSQL đều chặn mọi mutation. |
| AT-04 | PDF text-native trong giới hạn được nhận, có SHA-256 và tạo đúng một DocumentVersion cùng một AnalysisJob. |
| AT-05 | File sai định dạng, quá 100 MB raw, vượt 50 MB decoded, quá 100 trang, có mật khẩu, active content, scan geometry không thể xác minh an toàn hoặc trang nghi scan bị từ chối với diagnostic code, disposition, repair action và page/bbox khi xác định được; không enqueue evaluator. |
| AT-06 | Sau upload, sinh viên thấy đúng các trạng thái Validating, Queued, Processing, Awaiting review, Published hoặc lỗi; không có spinner vô hạn và phần trăm giả. Khi validator có diagnostic, sinh viên thấy nguyên nhân an toàn, cách sửa và mở đúng page/region trên PDF viewer dùng chung. |
| AT-07 | Upload lặp hoặc redelivery từ queue không tạo kết quả/finding trùng. Commit `QUEUED`, API restart hoặc broker lỗi không làm mất wake-up nhờ dispatch outbox; dừng worker giữa job rồi khởi động lại không làm mất job; retry dừng sau ba lần. Worker PDF mặc định concurrency 2, prefetch 1 và recycle child định kỳ để giới hạn số file 100 MB đồng thời và thu hồi bộ nhớ parser. |
| AT-08 | Document IR schema 2 lưu text theo trang, section, requirement, use case, table, link annotation và coordinate. Mỗi evidence mở đúng trang; anchor sai bị đánh dấu thủ công thay vì hiển thị như hợp lệ. Trang có text-table discovery vượt work budget phải bỏ qua heuristic tốn kém, giữ text/coordinate và đánh dấu phần tử cần review thay vì loại toàn bộ PDF. |
| AT-09 | Cả 12 criterion xuất hiện trong kết quả. Criterion qua gate có đề xuất; criterion chưa qua gate có trạng thái Needs manual review và cho phép giảng viên nhập mức. |
| AT-10 | Báo cáo benchmark chứng minh từng evaluator đang bật đạt toàn bộ ngưỡng tại mục 7 trên holdout độc lập. |
| AT-11 | Trong review workspace, chọn finding đưa PDF tới đúng evidence; chọn marker chọn lại đúng finding; giảng viên chấp nhận, sửa và loại bỏ được. |
| AT-12 | Autosave hoàn tất trong 2 giây ở p95; refresh sau khi báo Đã lưu không mất dữ liệu. Hai phiên sửa cùng revision gây conflict rõ ràng và không ghi đè âm thầm. |
| AT-13 | Không thể duyệt khi còn criterion chưa xác nhận hoặc review item bắt buộc chưa xử lý. Duyệt thành công tạo immutable review snapshot. |
| AT-14 | Chỉ bài đã duyệt mới publish được. Publish thành công làm toàn bộ kết quả xuất hiện cùng lúc; batch publish tự loại/chặn bài chưa duyệt; publish lỗi không để sinh viên thấy dữ liệu một phần. Unpublish phải ẩn kết quả, giữ version/audit và gửi thông báo đúng BR-33. |
| AT-15 | Sinh viên chỉ thấy kết quả đã công bố, feedback được phép công khai và evidence tương ứng; mọi nhãn dùng dữ liệu nghiệp vụ nhận ra được, không thấy UUID, SHA-256, bbox, element ID hoặc finding bị loại. |
| AT-16 | Nộp lại giữ phiên bản cũ, tạo phiên bản mới và cho phép so sánh hai phiên bản bất kỳ trong cùng Submission từ dữ liệu đã lưu mà không trộn hoặc tính lại kết quả. |
| AT-17 | Sinh viên mở được tối đa một review request cho mỗi criterion/result version; giảng viên trả lời, đóng và mọi thay đổi điểm tạo published version mới. |
| AT-18 | Admin lọc được job lỗi, thử lại an toàn và xem audit của upload, auto-evaluation, override, approve, publish, role change và retry. Job/audit ưu tiên Assignment, tên file, tên/email actor hoặc Student; UUID và correlation ID chỉ xuất hiện trong disclosure `Technical details`. |

### 8.2. Phi chức năng

| ID | Điều kiện nghiệm thu |
|---|---|
| AT-19 | Trên môi trường tham chiếu với 100 phiên web, 20 upload và 10 job đồng thời: p95 API đọc/ghi không gồm upload/analysis không quá 2 giây; upload được enqueue không quá 5 giây sau khi truyền file xong. |
| AT-20 | Ít nhất 90% PDF hợp lệ tối đa 100 trang trong bộ tải hoàn tất từ Queued tới Awaiting review trong 10 phút; báo cáo phải ghi số trang, số job và latency provider. |
| AT-21 | Viewer hiển thị trang đầu trong 3 giây ở mạng 20 Mbps, tải trang theo nhu cầu và không tải lại toàn bộ PDF khi chuyển finding. |
| AT-22 | Kiểm thử file upload xác nhận giới hạn kích thước, magic bytes, MIME, parser validation, active-content rejection, quyền object và URL hết hạn. |
| AT-23 | Bộ test prompt injection xác nhận text trong PDF không thể đổi schema, quyền, provider config, system instruction hoặc khiến worker gọi tool ngoài pipeline đã khai báo. |
| AT-24 | Log không chứa nội dung PDF, password, session cookie, API key, ciphertext hoặc prompt đầy đủ; mọi request/job có correlation ID và lỗi kỹ thuật chỉ hiện cho Admin. Validation error của endpoint credential không lặp lại input. Provider key chỉ đi trong header server-to-server tới fixed HTTPS host, không nằm trong URL/query; mọi kết nối ngoài dùng TLS 1.2 trở lên. File và backup được mã hóa khi lưu; backup có credential ciphertext phải giữ key version tương ứng trong toàn bộ thời gian có thể restore. |
| AT-25 | Các flow đăng nhập, upload, review, publish và xem kết quả đáp ứng WCAG 2.2 AA; dùng được bằng bàn phím, không keyboard trap, reflow ở 320 CSS px, zoom text 200%, trạng thái không chỉ biểu diễn bằng màu và PDF có chế độ text/outline thay thế cho canvas. |
| AT-26 | Hỗ trợ hai bản stable gần nhất của Chrome, Edge và Firefox; Safari hiện hành hỗ trợ flow Student; desktop từ 1280 px có review hai cột, tablet chuyển tab, mobile chỉ bắt buộc flow sinh viên cơ bản. |
| AT-27 | Backup hằng ngày được restore thử trên môi trường tách biệt; RPO không quá 24 giờ và RTO không quá 4 giờ. |
| AT-28 | CI phải pass lint/type check, unit test, integration test và E2E critical path. Domain reviewer hoàn tất một vòng UAT từ tạo đợt đến sinh viên xem kết quả. |
| AT-29 | Sau khi vận hành, Web/API đạt SLO 99,5% theo tháng, không tính maintenance đã thông báo; job bền vững qua restart. Tháng đầu không đạt SLO phải có incident review và kế hoạch sửa trước khi mở rộng người dùng. |
| AT-30 | E2E hoàn tất luồng Teacher tạo/lưu rubric hợp lệ → mở Assignment → Student nộp PDF → worker xử lý → Teacher review/approve/publish kết quả → Student mở evidence và gửi review request. |

## 9. Quyết định kiến trúc

```text
Browser
  ├─ React/Vite SPA ── REST/OpenAPI ── FastAPI modular monolith ── PostgreSQL
  │        └─ PDF.js                         │          └────────── File storage
  │                                         │
  └─ trạng thái job / review                └─ dispatch outbox ── Redis ── Celery worker
                                                               ├─ PDF parser
                                                               ├─ Rule evaluators
                                                               └─ LLM provider adapter
```

### 9.1. Lý do chọn modular monolith

- Nghiệp vụ Course, Assignment, Rubric, Submission, Review và Publish liên quan chặt; một transaction boundary và một database giảm lỗi nhất quán.
- API và worker dùng chung domain model/evaluator package nhưng chạy ở process riêng, nên xử lý PDF/LLM không khóa request web.
- Một Docker Compose đủ cho MVP, dễ debug và triển khai hơn nhiều service độc lập.
- Các module có interface rõ để có thể tách worker hoặc storage sau này mà không thiết kế microservice từ đầu.

### 9.2. Ranh giới module

- `identity`: account, role, session, authorization.
- `course`: Course, membership và phân công Giảng viên/Sinh viên.
- `assignment`: Assignment, yêu cầu nộp bài, deadline và lifecycle.
- `rubric`: rubric version, criterion, level, weight và evaluator config.
- `submission`: upload, validation, document version và private storage.
- `analysis`: Document IR, job, evaluator, finding và evidence.
- `review`: decision, autosave, lock, approval và published version.
- `appeal`: review request và response.
- `operations`: notification, audit, usage và job administration.

Module giao tiếp qua service interface/domain event trong cùng codebase. Không tạo HTTP nội bộ giữa module trong MVP.

### 9.3. Quyết định chính thức về frontend

Chọn **React + TypeScript + Vite** cho frontend sản phẩm. Không dùng Next.js trong MVP.

Quyết định này thay thế dòng Web trước đây dùng Next.js tại SRS §5.7 và là baseline áp dụng cho phát triển.

- DocGrading là ứng dụng đăng nhập theo role, giàu tương tác ở review workspace và không có yêu cầu SEO, SSR hoặc nội dung public cần render phía server.
- FastAPI là server duy nhất sở hữu authentication, authorization, domain transaction và OpenAPI. Không tạo thêm Route Handler, Server Action hoặc BFF bằng Next.js.
- Prototype hiện tại đã kiểm chứng cấu trúc màn hình và flow trên React/Vite. Nó là nguồn tham khảo UI với mock data, không phải bằng chứng rằng API, persistence hoặc authorization đã được triển khai.
- Production build là static assets do Vite tạo và Caddy phục vụ. Khi phát triển, Vite proxy `/api` sang FastAPI; production giữ cùng origin qua reverse proxy để đơn giản hóa cookie và CSRF.
- Đăng nhập, đăng xuất và hết hạn session được đồng bộ giữa các tab; mỗi tab phải xóa server-state cache của người dùng cũ trước khi hiển thị session mới.
- React Router quản lý URL theo Course/Assignment/Submission; TanStack Query quản lý server state. Không tiếp tục dùng `View` state trong `App.tsx` làm router sản phẩm.
- Việc nâng prototype từ React 18/Vite 6 lên baseline target phải là thay đổi dependency có kiểm thử riêng; không trộn vào công việc nối API.

### 9.4. API contract v1

#### 9.4.1. Quy ước chung

- REST/JSON dưới prefix `/api/v1`. FastAPI/Pydantic là nguồn sự thật và xuất OpenAPI tại `/api/v1/openapi.json`.
- TypeScript client và type được generate từ OpenAPI; frontend không duy trì model request/response viết tay song song với backend. OpenAPI đã chốt phải được lưu làm artifact CI và contract test phải phát hiện breaking change.
- JSON dùng `snake_case`; ID public là UUID; thời gian là ISO 8601 UTC; enum dùng literal chữ hoa như state machine trong tài liệu này.
- Response một resource trả trực tiếp resource. Danh sách trả `{items, page, page_size, total}`; `page_size` tối đa 100; sort và filter phải được khai báo trong OpenAPI.
- Authentication dùng opaque session cookie. Mọi mutation yêu cầu CSRF token. Backend kiểm tra role và quyền theo từng Course, Assignment, Submission hoặc Result; tài nguyên không tồn tại trả `404`, người dùng đã xác thực nhưng ngoài phạm vi object trả `403` theo dependency authorization dùng chung. Ngoại lệ đã chốt: Teacher truy cập object thuộc Course khác nhận `404` để không lộ sự tồn tại của object.
- Login chuẩn hóa email, serialize mỗi email bằng PostgreSQL advisory lock rồi khóa row `User`. Năm lần sai trong cửa sổ cố định 15 phút khóa login 15 phút; login đúng sau khi hết khóa xóa bộ đếm. Email không tồn tại, tài khoản bị Admin khóa và tài khoản đang bị khóa tạm đều chạy Argon2id dummy rồi trả cùng lỗi `401`, tránh lộ account qua nội dung hoặc timing dễ phân biệt. Trước khi băm, mỗi client IP bị giới hạn `LOGIN_IP_MAX_FAILED_ATTEMPTS` (mặc định 30) lần sai trong cùng cửa sổ, kể cả email không tồn tại; vượt ngưỡng trả `429` và `Retry-After`, login đúng không tính vào ngưỡng. Argon2id chạy ngoài event loop với tối đa 4 phép băm đồng thời mỗi API process; chờ quá 5 giây trả `503`. Bộ đếm IP nằm trong process, cần chuyển sang storage dùng chung trước khi chạy nhiều API replica.
- Mọi response có `X-Request-ID`. Lỗi dùng `application/problem+json` theo RFC 9457 với tối thiểu `type`, `title`, `status`, `detail`, `instance`, `code`, `request_id`; lỗi validation có thêm `errors[]` gồm `field`, `code`, `message`. Không trả stack trace, queue name, prompt hoặc nội dung PDF.
- `POST` tạo resource đồng bộ trả `201 Created` và `Location`. Tác vụ nền trả `202 Accepted` cùng `job_id`, `status_url` và `Retry-After`. Rate limit trả `429` và `Retry-After`.
- Resource có chỉnh sửa đồng thời trả `revision`. Mặc định mutation gửi `If-Match: "rev-{revision}"` và revision cũ trả `412 Precondition Failed`. Riêng autosave `PUT /submissions/{submission_id}/review-draft` gửi `revision` cùng `document_version_id` trong JSON để server nhận diện exact retry của full replacement và chặn write qua lần nộp mới; precondition cũ hoặc khác version trả `409 Conflict`.
- `Idempotency-Key` bắt buộc cho upload, retry, approve, publish và unpublish. Cùng key và cùng payload trả lại kết quả trước đó; cùng key nhưng payload khác trả `409 Conflict`.

#### 9.4.2. Resource hierarchy và endpoint bắt buộc

`Course` là aggregate quản lý người học và quyền truy cập. `Assignment` luôn thuộc đúng một Course và sở hữu yêu cầu nộp bài, deadline, số lượt, RubricVersion và Submission. Không dùng `Assessment` như một entity API song song.

`GET /courses` và `GET /courses/{course_id}` dùng cùng phạm vi đọc: Admin thấy mọi Course, Teacher chỉ thấy Course mình sở hữu, Student chỉ thấy Course có membership `ACTIVE`; Course ngoài phạm vi trả `404` ở endpoint detail. `CourseResponse` trả owner summary (`id`, `display_name`, `email`), `created_at`, `updated_at` và revision phục vụ concurrency. UI project theo vai trò: Admin thấy owner ngay trong danh sách và metadata trong `Course details`; Teacher đặt owner/thời gian trong `Course details`; Student chỉ đặt instructor, học kỳ và trạng thái trong `Course information`, không hiển thị timestamp, revision hoặc UUID. Mutation, roster và join-code vẫn chỉ dành cho Admin hoặc Teacher sở hữu Course.

| Nhóm | Endpoint v1 | Hợp đồng chính |
|---|---|---|
| Session/Profile | `POST /auth/login`, `POST /auth/logout`, `GET/PATCH /auth/me`, `POST /auth/change-password` | Đăng nhập/đăng xuất và trả user, role, quyền hiệu lực; session nằm trong cookie, không trả JWT để lưu ở browser. User tự sửa display name bằng optimistic concurrency. Đổi mật khẩu phải xác minh mật khẩu hiện tại, dùng Argon2id, không ghi password vào log/audit và thu hồi mọi session khác. |
| Course | `GET/POST /courses`, `GET/PUT/DELETE /courses/{course_id}`, `POST /courses/{course_id}/archive`, `GET/POST /courses/{course_id}/members`, `DELETE /courses/{course_id}/members/{user_id}` | Chỉ Admin hoặc Teacher sở hữu Course xem roster và mutation. Teacher tạo Course do chính mình sở hữu; Admin tạo phải chọn một tài khoản `ACTIVE` có role `TEACHER` làm owner. `PUT`, `DELETE` và `archive` khóa row Course, yêu cầu `If-Match`; Course chỉ được hard-delete khi chưa có Assignment, Announcement, Membership, CourseInvite hoặc CourseJoinCode, nếu không phải archive. `GET members` phân trang, lọc `ACTIVE`/`REMOVED`, trả email, display name, `joined_at`, `joined_via`. `POST members` nhận email và reason tùy chọn, trả `ADDED`, `REACTIVATED` hoặc `INVITED`; `DELETE member` nhận JSON body có reason tùy chọn và soft-remove, không xóa lịch sử submission/result. |
| Assignment | `GET/POST /courses/{course_id}/assignments`, `GET/PUT/DELETE /courses/{course_id}/assignments/{assignment_id}`, `POST /courses/{course_id}/assignments/{assignment_id}/publish`, `POST /courses/{course_id}/assignments/{assignment_id}/close` | Route `publish` hiện hữu mở Assignment từ `DRAFT` sang `OPEN`; đây không phải publish rubric hoặc publish kết quả. Lưu details, submission requirements, rubric link và lifecycle. Chỉ mở khi rubric/requirements hợp lệ. Chỉ xóa `DRAFT` chưa có Submission. Response cho Student thêm `student_submission_id` và `student_attempts_used` để UI đồng bộ số lượt với upload guard. |
| Announcement | `GET/POST /courses/{course_id}/announcements`, `PUT/DELETE /courses/{course_id}/announcements/{announcement_id}` | Student membership đang hoạt động được đọc; Teacher sở hữu Course hoặc Admin được tạo, sửa, xóa. Mọi mutation khóa và kiểm tra lại Course ACTIVE trong cùng transaction; archived Course chỉ đọc. |
| Rubric | `GET/POST /rubrics`, `GET/PUT/DELETE /rubrics/{rubric_id}`, `GET/POST /rubrics/{rubric_id}/criteria`, `PUT/DELETE /rubrics/{rubric_id}/criteria/{criterion_id}` | Lưu và chỉnh sửa trực tiếp; không có rubric publish/new-version endpoint. Xóa chỉ khi không có Assignment, AnalysisJob hoặc lineage tham chiếu. Metadata/tiêu chí đóng băng sau bài nộp đầu tiên. |
| Submission | `GET /assignments/{assignment_id}/submissions`, `POST /assignments/{assignment_id}/uploads/presign`, `POST /document-versions/{version_id}/complete`, `GET /submissions/{submission_id}`, `GET /submissions/{submission_id}/versions`, `GET /submissions/{submission_id}/versions/compare` | Upload hai bước: presign yêu cầu `Idempotency-Key`, SHA-256 và client hints, trả presigned POST tối đa 5 phút khóa đúng staging key/MIME/size; completion kiểm tra metadata, conditional-copy đúng ETag sang sealed key không được presign rồi tạo hoặc trả lại đúng một AnalysisJob. Upload trùng theo BR-09 trả resource hiện có mà không cấp credential ghi đè. Teacher/Admin xem danh sách theo Assignment gồm Student, email, latest filename/size/time/status và tổng số attempt. Mỗi Student có thể mở toàn bộ lịch sử `DocumentVersion`; API versions trả số lần nộp, filename, size, thời gian, trạng thái xử lý/publication và không thay thế lần cũ bằng lần mới. Compare chỉ đọc snapshot, draft và decision đã lưu, đồng thời không chấm lại. |
| File/evidence | `GET /document-versions`, `GET /document-versions/{version_id}/download`, `GET /document-versions/{version_id}/validation-report`, `GET /submissions/{submission_id}/evidence` | Collection DocumentVersion phân trang, search/filter và luôn áp quyền object: Admin toàn hệ thống, Teacher chỉ Course mình phụ trách, Student chỉ Submission của mình trong Course còn membership `ACTIVE`. Download kiểm tra cùng quyền trước khi trả redirect/URL ký tối đa 5 phút. Validation report dùng cùng quyền đọc DocumentVersion và chỉ trả diagnostic đã giới hạn. Evidence chỉ dành cho Admin hoặc Teacher phụ trách, không trả raw parser content, raw IR, prompt hoặc storage key. |
| Job | `GET /analysis-jobs/{job_id}`, `POST /analysis-jobs/{job_id}/retry`, `GET /operations/analysis-jobs`, `GET /operations/analysis-jobs/{job_id}`, `POST /operations/analysis-jobs/{job_id}/retry` | Trạng thái job là `QUEUED`, `RUNNING`, `DONE`, `ERROR`; retry dùng lại row và tuân BR-10. Các endpoint `/operations/*` chỉ dành cho Admin, hỗ trợ xem/retry mọi job và lọc danh sách theo status/Course; Teacher chỉ xem/retry job thuộc Course mình phụ trách qua endpoint cũ; Student chỉ xem job của mình và không retry. Frontend poll, không giả lập phần trăm. |
| Review | `GET /courses/{course_id}/submission-queue`, `GET /document-versions/{version_id}/grading-result`, `POST /submissions/{submission_id}/review-lock`, `PUT /submissions/{submission_id}/review-lock/heartbeat`, `DELETE /submissions/{submission_id}/review-lock`, `GET/PUT /submissions/{submission_id}/review-draft` | Queue lọc `UNREVIEWED`/`REVIEWED`/`ERROR`, sort theo submission time và dùng `{items, page, page_size, total}`. Teacher phụ trách Course hoặc Admin mở grading result read-only của từng DocumentVersion: metadata file, analysis job, finding/evidence, citation report, review decision/comment, published snapshots, status timeline và audit action đã allowlist; không trả raw IR, prompt, storage key hoặc error detail. Draft endpoint vẫn sửa DocumentVersion mới nhất nhưng mỗi version giữ row riêng; full-replacement gửi `revision` và `document_version_id`, hỗ trợ `ACCEPT`/`EDIT`/`REJECT` và comment. Lock/heartbeat theo BR-18; Admin force-release được audit. Score override yêu cầu reason và audit before/after. |
| Approve/publish | `POST /document-versions/{version_id}/approve`, `POST /document-versions/{version_id}/publish`, `POST /published-results/{published_result_id}/unpublish` | Approve và publish là hai command riêng. Publish/unpublish atomic, idempotent, có reason/audit và không lộ kết quả một phần. |
| Student result | `GET /submissions/{submission_id}/published-result`, `POST /published-results/{published_result_id}/review-requests` | Chỉ trả published snapshot và field được phép công khai; tạo review request theo BR-23/BR-30. |
| Review request | `GET /courses/{course_id}/review-requests`, `GET/PATCH /review-requests/{review_request_id}` | Teacher phụ trách Course hoặc Admin lọc, xem và phản hồi request; `status` hỗ trợ `OPEN`, `RESOLVED`, `REJECTED`; danh sách trả `{items, page, page_size, total}`. Student chỉ xem request của chính mình. Mỗi request giữ exact PublishedResultVersion; thay đổi điểm phải tạo PublishedResultVersion mới. |
| Operations | `GET/POST /users`, `GET/PATCH /users/{user_id}`, `GET /operations/audit-events`, `GET /operations/dashboard`, `GET /notifications`, `PATCH /notifications/{notification_id}/read`, `PATCH /notifications/read`, `GET /metrics` | Admin có quyền cao nhất tại mọi object nhưng vẫn phải qua lifecycle, optimistic concurrency, CSRF, idempotency và audit như role khác. “Delete” dùng hard delete chỉ với resource chưa có lịch sử phụ thuộc; dữ liệu học thuật, User, Submission, PublishedResultVersion và AuditEvent dùng lock/archive/unpublish hoặc bất biến, không có bypass xóa tràn lan. Dashboard trả aggregate vận hành và xu hướng bảy ngày của job terminal (`DONE`/`ERROR`) theo `finished_at`, không trả telemetry nhạy cảm. Mỗi actor chỉ list/mark-read Notification của chính mình. |

#### 9.4.3. Hợp đồng trạng thái bất đồng bộ

1. Presign upload thành công trả `201` với `submission_id`, `document_version_id`, object key, URL/form fields ký, `expires_in`, `status` và cờ `reused`. Response `reused` của bản đã hoàn tất không trả credential ghi đè.
2. Browser upload trực tiếp lên staging key rồi gọi completion. Completion chỉ trả `202` sau khi conditional-copy đúng ETag sang sealed key dành cho worker/download; response gồm `submission_id`, `document_version_id`, `analysis_job_id` và trạng thái job.
3. Frontend poll `GET /analysis-jobs/{job_id}` theo backoff từ 2 đến tối đa 10 giây và dừng ở `DONE` hoặc `ERROR`; trạng thái tài liệu vẫn theo state machine tại mục 5.4.
4. API chỉ trả progress khi worker có số bước đo được; nếu không thì không giả lập phần trăm. `ERROR` dùng mã lỗi ổn định; chi tiết provider, URL ký và nội dung PDF không được trả cho người dùng.
5. Browser refresh phải khôi phục trạng thái từ API bằng `status_url`; timer và state trong prototype không phải nguồn sự thật.
6. Notification dùng polling `GET /notifications`; không có push, email hoặc websocket cho tới khi có hạ tầng delivery riêng.

#### 9.4.4. Điều kiện hoàn tất contract

- OpenAPI mô tả đủ request, success response, Problem Details, auth/CSRF, enum và ví dụ cho toàn bộ endpoint trong bảng trên.
- Frontend build dùng generated client và không gọi `fetch` trực tiếp ngoài một transport wrapper dùng chung.
- Contract test xác nhận codegen TypeScript thành công, không có operation ID trùng và mọi mutation khai báo các response `401`, `403` hoặc `404`, `409`, `412`, `422` và `429` khi áp dụng.
- Integration test khóa các invariant quan trọng: object authorization, Course → Assignment ownership, upload idempotency, optimistic concurrency, Approve ≠ Publish và Student chỉ thấy PublishedResultVersion.
- E2E AT-30 chạy qua API thật; mock timer của prototype không được dùng làm bằng chứng nghiệm thu.

## 10. Tech stack đã chọn

| Lớp | Công nghệ | Quyết định sử dụng |
|---|---|---|
| Runtime frontend | Node.js 24 LTS | Chỉ dùng bản LTS và khóa version bằng `.nvmrc`/Volta. |
| Frontend | React 19, TypeScript 6, Vite 8 | Quyết định chính thức cho SPA; không dùng Next.js, SSR, React Server Components, Server Actions hoặc Route Handlers. |
| Routing/data | React Router, TanStack Query | URL giữ filter/selection quan trọng; server state không đưa vào global store tùy ý. Không dùng Redux trong MVP. |
| Form/schema | React Hook Form, Zod | Form rubric/upload rõ validation; type API được generate từ OpenAPI. |
| UI | Tailwind CSS + Radix Primitives | Radix xử lý semantics/focus/keyboard; Tailwind triển khai skeleton trung tính. Không dùng dashboard template hoặc theme nhiều màu. |
| PDF viewer | PDF.js 6.x | Render phía client, lazy-load page, search, zoom và overlay evidence riêng. Không fork viewer lõi. |
| Runtime backend | Python 3.13 | Hệ sinh thái PDF/AI phù hợp và còn được hỗ trợ tới 2029; pin minor qua container. |
| API/domain | FastAPI, Pydantic 2 | OpenAPI tự sinh, validation mạnh, async I/O cho upload/provider. Heavy work không chạy bằng BackgroundTasks của web process. |
| ORM/migration | SQLAlchemy 2, Alembic | Transaction rõ, schema migration có version; không tạo SQL bằng LLM. |
| Queue | Celery 5.6 + Redis 7 | Chỉ dùng task, retry, late acknowledgement và routing cơ bản; PostgreSQL dispatch outbox được drain sau commit và bởi poller lifespan FastAPI, không dùng chain/canvas/beat trong MVP. Task phải idempotent. |
| Database | PostgreSQL 17, latest minor | Lưu nguồn sự thật, JSONB cho evaluator payload có schema và relational columns cho dữ liệu cần query. Không dùng MongoDB. |
| PDF backend | pypdf + pdfplumber | pypdf validate-first cho PDF untrusted (strict, page/decoded-size/active-content bounds); pdfplumber cho character/line/table coordinate, gồm bảng ruled và text-aligned. Chạy trong worker process. |
| Citation identity | Crossref REST API + arXiv Atom API + OpenAlex (title search, DOI lookup) qua stdlib adapter | Chỉ gọi fixed Crossref endpoint cho DOI/bounded bibliographic search, fixed arXiv endpoint cho canonical arXiv ID và fixed OpenAlex `/works` endpoint; rate-limit theo chính sách từng provider, retry có giới hạn, cache bounded, không fetch arbitrary URL và không dùng LLM. |
| File storage | Storage adapter: LocalStack S3 + sealed-object recovery volume ở dev, S3-compatible ở staging/prod | Dev tự khôi phục object/bucket LocalStack bị mất sau restart từ named volume dùng chung và cấu hình upload CORS cho cả hai loopback origin `localhost`/`127.0.0.1`; production không phụ thuộc local disk của container. Ngoài development, `Settings` từ chối `STORAGE_RECOVERY_DIR` để object đã xóa khỏi bucket không được khôi phục lại từ bản sao local. arXiv source cache chỉ private, không có user download route. |
| Auth | Opaque server session cookie + Argon2id | Cookie `HttpOnly`, `Secure`, `SameSite=Lax`, CSRF token cho mutation. Không lưu JWT trong localStorage. |
| AI integration | Versioned Admin-managed provider routing + bounded adapters + Pydantic JSON Schema | `CITATION_SEMANTIC` dùng một route `ACTIVE` được snapshot khi tạo job. Adapter cố định cho OpenAI, Anthropic Claude, Google Gemini, DeepSeek, OpenCode Zen và Amazon Bedrock; OpenCode Zen yêu cầu protocol phù hợp model (`OpenAI Chat`, `OpenAI Responses`, `Anthropic Messages` hoặc `Gemini generateContent`). Exact textual support vẫn bỏ qua model; trường hợp còn lại dùng criterion-scoped system instruction, atomic claim + top-3 source passages, temperature 0, explicit token/call budget, no tools, output validation/retry và provider-error fallback sang review thủ công. API key lấy từ allowlist env hoặc encrypted PostgreSQL credential; fixed host/path, không custom base URL hay automatic provider failover. Catalog test dùng endpoint list models và được gắn với credential revision; model generation không được coi là đã test chỉ từ catalog. Bedrock tiếp tục dùng IAM credential chain/Converse, server-owned region/model; global/ARN inference profile bị từ chối và geographic prefix phải được phê duyệt chính xác. Token usage/latency được trace nội bộ; `estimated_cost_usd` và Student billing vẫn `null` cho tới khi có pricing contract được duyệt. |
| Semantic retrieval | BM25 stdlib + shared text encoder client | Encoder là cấu hình vận hành dùng chung, không gắn với một model: client nói OpenAI-compatible `/embeddings` và Text Embeddings Inference `/rerank`. Mặc định self-host qua Compose profile `encoder` (TEI CPU, pinned `BAAI/bge-m3` + `BAAI/bge-reranker-v2-m3`, MIT/Apache-2.0); API embedding hosted dùng cùng client nếu được duyệt, API key chỉ gửi tới embeddings URL. Vector source passage lưu packed float32 trong private cache theo encoder + nội dung passage; không dùng vector database. Không cấu hình hoặc encoder/reranker/cache lỗi thì fallback BM25. |
| Deploy | Docker Compose + Caddy | Một host, TLS/reverse proxy đơn giản. Database và file storage có backup riêng. |
| Test | pytest, Vitest, Playwright, axe-core | Unit cho scoring/rule; integration cho DB/queue/storage; E2E cho critical flows và accessibility. |
| Quality | Ruff, mypy, ESLint, TypeScript strict | Chặn lỗi sớm trong CI; không thêm nhiều formatter/linter trùng chức năng. |

### 10.1. Vì sao Python không phải nút thắt chính

- Request web, upload, database và gọi LLM chủ yếu chờ I/O; FastAPI xử lý phần này bằng async I/O.
- Parse PDF và rule nặng chạy ở Celery worker process, tách khỏi API và có thể tăng số worker theo CPU.
- Pipeline giới hạn file 100 trang, parse một lần thành một Document IR JSONB có version cho mỗi `DocumentVersion`, tọa độ dùng hệ top-left theo từng trang; worker tái sử dụng IR cho mọi evaluator và không parse lại PDF cho từng criterion.
- Tốc độ thực tế phải được đo bằng bộ PDF của dự án. Không chọn thư viện chỉ dựa trên benchmark của nhà cung cấp.

### 10.2. Thư viện không chọn mặc định

- **Next.js**: SSR, Server Components và server layer của Next không tạo giá trị rõ cho ứng dụng nội bộ; làm tăng khái niệm phải vận hành khi backend vẫn cần Python.
- **NestJS + Python evaluator service**: type-safe ở backend nhưng buộc duy trì thêm service, contract và deployment chỉ để giữ Python cho PDF/AI.
- **Django template/HTMX**: tốt cho CRUD nhưng review workspace PDF hai chiều là ứng dụng client phức tạp; cuối cùng vẫn cần nhiều JavaScript riêng.
- **PyMuPDF**: nhanh nhưng dùng AGPL hoặc commercial license. Không đưa vào baseline cho tới khi dự án chấp nhận nghĩa vụ AGPL hoặc mua license.
- **Kubernetes, Kafka, Elasticsearch, vector database**: chưa có yêu cầu scale/search chứng minh chi phí vận hành này.

## 11. So sánh phương án

| Phương án | Tốc độ phát triển | Độ phức tạp vận hành | Phù hợp PDF/AI | Kết luận |
|---|---:|---:|---:|---|
| React/Vite + FastAPI + Celery | Cao | Thấp–trung bình | Cao | **Chọn** |
| Next.js + FastAPI + Celery | Trung bình | Trung bình | Cao | Không cần SSR; trùng server concern |
| React + NestJS + Python evaluator service | Thấp trong tháng đầu | Cao | Cao | Quá nhiều service và contract |
| Django/HTMX + worker | Cao cho CRUD, thấp cho review viewer | Thấp–trung bình | Cao | Review workspace cần client app giàu tương tác |

## 12. Rủi ro và biện pháp khóa scope

| Rủi ro | Mức | Quyết định xử lý |
|---|---|---|
| PDF có layout không ổn định, anchor sai | Cao | Chỉ text-native, giới hạn 100 trang, benchmark corpus, lưu quote + page + coordinate, fallback thủ công. |
| LLM hallucination hoặc prompt injection | Cao | Structured output, criterion-scoped input, không cấp tool/quyền, evidence bắt buộc, teacher approval. |
| Thiếu dữ liệu benchmark | Cao | Không bật evaluator chưa qua gate; không dùng demo đẹp làm bằng chứng chất lượng. |
| Review workspace quá nhiều thông tin | Trung bình | PDF 60–70%, rubric là tab mặc định, progressive disclosure, skeleton trung tính theo DESIGN.md. |
| Celery tạo độ phức tạp | Trung bình | Chỉ task/retry cơ bản, một Redis, idempotency ở database, không workflow canvas/beat. |
| Hai giảng viên sửa cùng bài | Trung bình | Soft lock + heartbeat + optimistic concurrency + audit. |
| Chi phí/độ trễ LLM | Trung bình | Claim-level retrieval, top-3 passages, cache Source IR, tối đa một call bình thường và một schema retry, per-job call budget, explicit token budget và manual fallback. Offline baseline không gọi model nên cost/latency model còn `NOT_MEASURED`. |
| Rò rỉ tài liệu học thuật | Cao | Private storage, object authorization, URL ngắn hạn, redaction, no-training provider policy, content-free logs. |

## 13. Trình tự triển khai để giữ mốc một tháng

- **Tuần 1:** domain model, database, auth/RBAC, app shell, OpenAPI contract, Course, Assignment và RubricVersion.
- **Tuần 2:** upload/validation, private storage, queue, Document IR, PDF.js viewer và ba evaluator rule-based đầu tiên.
- **Tuần 3:** review workspace, finding/evidence, autosave/lock, approve/publish, student result và remaining evaluators sau feature flag.
- **Tuần 4:** benchmark/gating, resubmission/review request, admin jobs/audit, security/accessibility/load test, backup restore và UAT.

Cuối tuần 2 phải có vertical slice: sinh viên upload một PDF hợp lệ → worker tạo finding có evidence → giảng viên mở đúng evidence. Nếu vertical slice này chưa chạy, dừng mở rộng dashboard/rubric builder và ưu tiên sửa pipeline lõi.

## 14. Quy tắc cho prototype giao diện

- Prototype phải thể hiện đúng scope và state machine trong note này; không thêm OCR, plagiarism, AI detection hoặc auto-publish.
- Thiết kế theo skeleton structure đã gửi: nền trung tính, ít màu, không gradient/glassmorphism/shadow lớn và không dùng dashboard template trang trí.
- Review workspace là viewport quan trọng nhất: PDF 60–70%, panel 360–480 px, action bar cố định.
- Bắt buộc có loading, empty, invalid PDF, processing failed, conflict, needs manual review, approved và published state.
- Đề xuất tự động, giảng viên đã sửa và giảng viên đã xác nhận phải phân biệt bằng label/icon, không chỉ bằng màu.
- Prototype dùng dữ liệu giả nhưng phải giữ đúng tên entity, role, status, business rule và acceptance trong note để không tạo flow không thể triển khai.

## 15. Nguồn nghiên cứu chính

- [ISO/IEC/IEEE 29148:2018 — Requirements engineering](https://www.iso.org/standard/72089.html)
- [ISO/IEC 25010:2023 — Product quality model](https://www.iso.org/standard/78176.html)
- [W3C Web Content Accessibility Guidelines 2.2](https://www.w3.org/TR/WCAG22/)
- [NIST AI Risk Management Framework 1.0](https://nvlpubs.nist.gov/nistpubs/ai/NIST.AI.100-1.pdf)
- [OWASP LLM01: Prompt Injection](https://genai.owasp.org/llmrisk/llm01-prompt-injection/)
- [OWASP File Upload Cheat Sheet](https://cheatsheetseries.owasp.org/cheatsheets/File_Upload_Cheat_Sheet.html)
- [Gradescope — Grading submissions with rubrics](https://guides.gradescope.com/hc/en-us/articles/22249389005709-Grading-submissions-with-rubrics)
- [Vite — Building for Production](https://vite.dev/guide/build)
- [Next.js — Single-Page Applications and static export](https://nextjs.org/docs/app/guides/single-page-applications)
- [Next.js — Static exports and unsupported server features](https://nextjs.org/docs/app/guides/static-exports)
- [FastAPI — Generate Clients](https://fastapi.tiangolo.com/advanced/generate-clients/)
- [FastAPI — Background Tasks](https://fastapi.tiangolo.com/tutorial/background-tasks/)
- [OpenAPI Specification](https://spec.openapis.org/oas/latest.html)
- [RFC 9110 — HTTP Semantics](https://www.rfc-editor.org/rfc/rfc9110.html)
- [RFC 9457 — Problem Details for HTTP APIs](https://www.rfc-editor.org/rfc/rfc9457.html)
- [Celery 5.6 — Tasks](https://docs.celeryq.dev/en/stable/userguide/tasks.html)
- [Node.js release status](https://nodejs.org/en/about/previous-releases)
- [Python version status](https://devguide.python.org/versions/)
- [PostgreSQL versioning policy](https://www.postgresql.org/support/versioning/)
- [PDF.js — Getting Started](https://mozilla.github.io/pdf.js/getting_started/?lang=en)
- [Radix Primitives — Accessibility](https://www.radix-ui.com/primitives/docs/overview/accessibility)
- [PyMuPDF — License and Copyright](https://pymupdf.readthedocs.io/en/latest/about.html#license-and-copyright)
