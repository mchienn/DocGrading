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

Repository hiện có prototype React/Vite và nền tảng backend T-005 gồm FastAPI health endpoint, SQLAlchemy/Alembic base, Celery healthcheck, Docker Compose và CI. Domain schema, API nghiệp vụ, persistence nghiệp vụ, authorization và pipeline PDF/AI vẫn chưa được triển khai hoặc kiểm chứng bằng benchmark nội bộ.

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
2. RBAC cho Admin, Giảng viên và Sinh viên; một tài khoản có thể có nhiều vai trò nhưng phải chuyển workspace rõ ràng.
3. Tạo Course, tạo Assignment trong Course, chọn rubric, cấu hình tiêu chí/trọng số, lưu nháp, mở và đóng nhận bài.
4. Rubric mặc định gồm 12 tiêu chí SRS; hỗ trợ template có phiên bản, nhân bản rubric, dry-run trên một PDF mẫu và tạo phiên bản mới.
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
15. Thông báo trong ứng dụng cho các sự kiện nộp bài, xử lý lỗi, công bố và phản hồi yêu cầu xem lại.

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
- Dashboard BI, mô hình dự báo, billing, multi-tenant hoặc marketplace rubric.
- Tự host LLM, fine-tuning, GPU server, Kubernetes và kiến trúc microservice.
- Evaluator tự động đã được đảm bảo chất lượng cho loại báo cáo khác SRS; loại khác chỉ dùng rubric thủ công cho tới khi có corpus và qua quality gate riêng.

### 3.3. Điều kiện để phạm vi một tháng khả thi

- Nhóm tối thiểu: hai kỹ sư làm toàn thời gian, một người tập trung frontend/UX và một người tập trung backend/PDF/AI; có giảng viên hoặc domain reviewer tối thiểu 4 giờ mỗi tuần.
- Dùng dịch vụ LLM qua API; không huấn luyện hoặc vận hành model riêng.
- Có tối thiểu 30 SRS tiếng Việt đã ẩn danh để benchmark, với mức rubric do giảng viên xác nhận cho từng tiêu chí.
- Môi trường triển khai là một máy chủ Linux 8 vCPU, 16 GB RAM, SSD; LLM nằm ngoài máy chủ.
- Nếu chỉ có một developer trong một tháng, release bắt buộc giảm còn upload, ba tiêu chí rule-based, review, duyệt và công bố; không được hạ quality gate để giữ số lượng chức năng.

## 4. Rubric mặc định

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

Ý nghĩa mức:

- `0 — Không đạt`: thiếu hoặc sai bản chất; không có bằng chứng đáp ứng.
- `1 — Yếu`: có dấu hiệu đáp ứng nhưng lỗi nghiêm trọng hoặc thiếu phần lớn.
- `2 — Một phần`: đáp ứng một phần; còn lỗi ảnh hưởng khả năng hiểu hoặc sử dụng.
- `3 — Tốt`: đáp ứng phần lớn; chỉ còn lỗi cục bộ, không nghiêm trọng.
- `4 — Đạt đầy đủ`: đáp ứng yêu cầu của tiêu chí và không có lỗi đáng kể trong phạm vi kiểm tra.

Một rubric có thể thay đổi trọng số hoặc tắt tiêu chí trước khi mở Assignment. Tổng trọng số của các tiêu chí đang bật phải bằng 100%.

## 5. Mô hình nghiệp vụ và trạng thái

### 5.1. Thực thể chính

- `User`, `Role`, `Course`, `CourseMembership`, `Assignment`.
- `RubricVersion`, `CriterionVersion`, `PerformanceLevel`, `TemplateVersion`.
- `Submission`, `DocumentVersion`, `AnalysisJob`.
- `EvaluationResult`, `CriterionResult`, `Finding`, `EvidenceAnchor`.
- `ReviewDecision`, `PublishedResultVersion`, `ReviewRequest`.
- `Notification`, `AuditEvent`.

### 5.2. Vòng đời Course

```text
ACTIVE → ARCHIVED
```

- `ARCHIVED` chỉ đọc, vẫn giữ lịch sử Assignment, Membership và audit.
- Muốn mở Course mới phải tạo Course khác; không unarchive hoặc ghi đè Course đã archive.

### 5.3. Vòng đời Assignment

```text
DRAFT → OPEN → CLOSED → ARCHIVED
```

- Chỉ `OPEN` nhận bài.
- `CLOSED` không nhận phiên bản mới nhưng giảng viên vẫn có thể review và công bố.
- `ARCHIVED` chỉ đọc; muốn sử dụng lại phải nhân bản thành đợt mới.

### 5.4. Vòng đời một phiên bản bài nộp

```text
UPLOADING → VALIDATING ──→ INVALID
                  ↓
               QUEUED → PROCESSING → AWAITING_REVIEW → APPROVED → PUBLISHED
                            └──────→ PROCESSING_FAILED
```

- `INVALID` cần sinh viên nộp file khác.
- `PROCESSING_FAILED` là lỗi hệ thống; Admin/Giảng viên có thể thử lại mà không yêu cầu upload lại.
- `APPROVED` và `PUBLISHED` là hai trạng thái riêng.
- Nộp lại tạo `DocumentVersion` mới; không ghi đè phiên bản cũ.

## 6. Luật nghiệp vụ

| ID | Luật đã chốt |
|---|---|
| BR-01 | Admin quản lý toàn hệ thống; Giảng viên chỉ quản lý Course, Assignment, rubric và bài thuộc phạm vi được giao; Sinh viên chỉ thao tác với Assignment được giao và bài của chính mình. Mọi API phải kiểm tra quyền theo object, không chỉ ẩn nút trên UI. |
| BR-02 | Không có đăng ký công khai. Admin tạo, khóa hoặc mở khóa tài khoản. Mật khẩu tối thiểu 12 ký tự và được băm bằng Argon2id. |
| BR-03 | Rubric hệ thống không được sửa trực tiếp. Giảng viên phải nhân bản. Khi Assignment nhận bài đầu tiên, rubric và liên kết RubricVersion của Assignment bị đóng băng. Phiên bản rubric mới chỉ dùng cho Assignment khác; không để sinh viên trong cùng một Assignment bị chấm bằng hai rubric khác nhau. |
| BR-04 | Tổng trọng số tiêu chí đang bật phải bằng 100%. Mỗi tiêu chí phải có đủ mức 0–4, mô tả, trọng số và phương pháp đánh giá trước khi mở Assignment. |
| BR-05 | Mỗi job lưu snapshot của Course, Assignment, RubricVersion, CriterionVersion, rule version, model/provider và cấu hình xử lý. Chạy lại cùng snapshot phải có thể truy nguyên kết quả. |
| BR-06 | Chỉ nhận file có magic bytes và MIME là PDF, tối đa 50 MB và 100 trang, không mã hóa/mật khẩu, không attachment hoặc JavaScript nhúng. |
| BR-07 | Một trang bị coi là nghi scan khi ảnh raster phủ từ 80% diện tích trang và có dưới 30 ký tự text hữu ích. File có bất kỳ trang nghi scan nào bị từ chối; trang trắng thật không tính là trang scan. |
| BR-08 | File gốc được lưu ngoài web root. Truy cập file dùng quyền theo object và URL ký có hạn 5 phút. Không lưu PDF blob trong PostgreSQL. |
| BR-09 | SHA-256 nhận diện file. Upload lặp đúng cùng file cho cùng sinh viên, Assignment và lần nộp phải trả lại phiên bản hiện có thay vì tạo job trùng. |
| BR-10 | Tối đa một job hoạt động cho một tổ hợp DocumentVersion + RubricVersion. Queue có thể giao việc lặp nhưng task phải idempotent. Job thử tối đa ba lần với exponential backoff rồi chuyển `PROCESSING_FAILED`. |
| BR-11 | Mọi finding tự động phải có criterion, phương pháp, mô tả, page number, text quote và tọa độ hoặc section anchor. Không xác minh được anchor thì không hiển thị finding như bằng chứng; criterion chuyển `NEEDS_MANUAL_REVIEW`. |
| BR-12 | Nội dung PDF là dữ liệu không tin cậy. Chỉ gửi phần text cần thiết cho từng criterion; nội dung tài liệu không được thay đổi system instruction, gọi tool đặc quyền hoặc quyết định quyền truy cập. |
| BR-13 | LLM phải trả structured output theo JSON Schema và được Pydantic validate. Output lỗi schema được retry một lần; vẫn lỗi thì criterion chuyển thủ công, không suy đoán để điền dữ liệu. |
| BR-14 | Chỉ evaluator vượt quality gate cho đúng criterion và ngôn ngữ mới được bật. MVP chỉ kích hoạt tự động cho tiếng Việt. Criterion/ngôn ngữ không qua gate vẫn xuất hiện trong rubric nhưng không có điểm tự động; giảng viên nhập mức thủ công. |
| BR-15 | Điểm và nhận xét tự động luôn là đề xuất. Giảng viên phải chấp nhận, sửa hoặc loại bỏ các mục cần kiểm tra và xác nhận đủ 12 criterion trước khi duyệt. |
| BR-16 | Khi sửa mức do hệ thống đề xuất, giảng viên phải nhập lý do ngắn. Hành động của hệ thống và người dùng được ghi riêng trong audit log. |
| BR-17 | Autosave sau 800 ms không nhập liệu. API dùng optimistic concurrency bằng revision number; khi xung đột không được ghi đè âm thầm và phải cho người dùng chọn tải bản mới hoặc sao chép thay đổi của mình. |
| BR-18 | Một bài chỉ có một người giữ soft lock review tại một thời điểm. Lock hết hạn sau 10 phút không có heartbeat; người khác vẫn xem được nhưng không được sửa cho tới khi nhận lock. Admin có thể giải phóng lock và hành động phải được audit. |
| BR-19 | Duyệt không đồng nghĩa công bố. Chỉ `APPROVED` mới được publish. Publish là thao tác atomic trên toàn bộ result snapshot; không công bố từng criterion rời rạc. |
| BR-20 | Sau khi công bố, chỉnh sửa tạo `PublishedResultVersion` mới. Sinh viên mặc định thấy phiên bản mới nhất; phiên bản cũ được giữ cho audit và không bị sửa tại chỗ. |
| BR-21 | Sinh viên chỉ thấy finding được giảng viên chấp nhận hoặc tạo, feedback được phép công khai và kết quả đã publish; không thấy prompt, model detail, confidence thô, finding bị loại hoặc log nội bộ. |
| BR-22 | Nộp lại tạo phiên bản mới và phân tích lại bằng snapshot áp dụng tại thời điểm nộp. So sánh MVP chỉ hỗ trợ hai phiên bản liền kề và theo criterion/finding, không diff pixel toàn bộ PDF. |
| BR-23 | Mỗi sinh viên chỉ có một review request đang mở cho một criterion của một PublishedResultVersion. Giảng viên trả lời và đóng yêu cầu; việc mở yêu cầu không tự thay đổi điểm. |
| BR-24 | LLM bên ngoài chỉ được dùng khi cấu hình không dùng dữ liệu để huấn luyện, có chính sách lưu giữ phù hợp và text đã loại metadata/định danh có thể loại. Không đáp ứng điều kiện thì toàn bộ LLM evaluator bị tắt, rule và review thủ công vẫn hoạt động. |
| BR-25 | Tối đa hai job đang hoạt động cho mỗi sinh viên và năm upload/phút/tài khoản. Vượt giới hạn trả lỗi có thời gian thử lại; không tạo job ngầm. |
| BR-26 | Document/result được giữ 365 ngày sau khi Assignment đóng; technical log 30 ngày; audit event 365 ngày. Xóa dữ liệu là job có audit, còn audit giữ định danh đã pseudonymize. |
| BR-27 | Notification là best-effort: lỗi gửi thông báo không rollback thao tác publish, retry job hoặc trả lời review request. Trạng thái nguồn vẫn là nguồn sự thật. |
| BR-28 | Assignment cấu hình số lần nộp từ 1 đến 5, mặc định 3. Chỉ nhận bài khi Assignment ở trạng thái `OPEN`, chưa quá hạn và còn lượt; MVP không có late submission hoặc gia hạn riêng từng sinh viên. Giảng viên có thể đổi hạn chung trước khi đóng Assignment. |
| BR-29 | Rubric và trọng số được hiển thị cho sinh viên từ khi Assignment mở. Cấu hình evaluator, prompt, rule và ghi chú nội bộ không được hiển thị. |
| BR-30 | Review request chỉ được mở trong 7 ngày lịch từ thời điểm publish kết quả và trước khi Assignment bị archive. Hết hạn, sinh viên vẫn xem kết quả nhưng không tạo request mới. |
| BR-31 | Dry-run rubric dùng PDF mẫu riêng, không tạo Submission hoặc PublishedResult, vẫn ghi usage và evaluator snapshot. Mỗi rubric chỉ có một dry-run đang hoạt động; kết quả dry-run tự hết hạn sau 30 ngày. |
| BR-32 | Model/provider là cấu hình vận hành có version, không hard-code vào domain. Chỉ một cấu hình đã qua benchmark và chính sách dữ liệu mới được đặt `ACTIVE`; thay model không làm thay đổi kết quả đã lưu. |
| BR-33 | Chỉ Teacher phụ trách hoặc Admin được unpublish. Thao tác phải có lý do, giữ nguyên PublishedResultVersion và audit, ẩn kết quả khỏi Student ngay lập tức, thông báo cho Student và đóng review request đang mở với trạng thái `RESULT_WITHDRAWN`. |

## 7. Quality gate cho evaluator tự động

Gate được áp dụng **theo từng criterion**, không lấy điểm trung bình toàn hệ thống để che một criterion yếu.

### 7.1. Bộ benchmark

- Tối thiểu 30 PDF SRS tiếng Việt đã ẩn danh, phủ tài liệu tốt, trung bình và yếu.
- Mỗi PDF có mức 0–4 cho đủ 12 criterion và evidence do giảng viên xác nhận.
- Ít nhất 20% mẫu được hai người chấm độc lập để phát hiện rubric mơ hồ.
- Giữ riêng 20% PDF làm holdout; không dùng để viết rule, prompt hoặc few-shot example.

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
| AT-02 | Giảng viên tạo được Course và Assignment từ nháp tới mở nhận bài, dry-run rubric trên PDF mẫu; hệ thống chặn mở khi rubric sai tổng trọng số hoặc thiếu level; sau hạn hoặc hết số lượt, upload bị từ chối mà không trừ thêm lượt. |
| AT-03 | Rubric đã dùng không sửa tại chỗ; thao tác sửa tạo version mới và bài cũ vẫn hiển thị đúng snapshot cũ. |
| AT-04 | PDF text-native trong giới hạn được nhận, có SHA-256 và tạo đúng một DocumentVersion cùng một AnalysisJob. |
| AT-05 | File sai định dạng, quá 50 MB, quá 100 trang, có mật khẩu, active content hoặc trang nghi scan bị từ chối với lý do và trang liên quan; không enqueue evaluator. |
| AT-06 | Sau upload, sinh viên thấy đúng các trạng thái Validating, Queued, Processing, Awaiting review, Published hoặc lỗi; không có spinner vô hạn và phần trăm giả. |
| AT-07 | Upload lặp hoặc redelivery từ queue không tạo kết quả/finding trùng. Dừng worker giữa job rồi khởi động lại không làm mất job; retry dừng sau ba lần. |
| AT-08 | Document IR lưu được text theo trang, section, requirement, use case và coordinate. Mỗi evidence mở đúng trang; anchor sai bị đánh dấu thủ công thay vì hiển thị như hợp lệ. |
| AT-09 | Cả 12 criterion xuất hiện trong kết quả. Criterion qua gate có đề xuất; criterion chưa qua gate có trạng thái Needs manual review và cho phép giảng viên nhập mức. |
| AT-10 | Báo cáo benchmark chứng minh từng evaluator đang bật đạt toàn bộ ngưỡng tại mục 7 trên holdout độc lập. |
| AT-11 | Trong review workspace, chọn finding đưa PDF tới đúng evidence; chọn marker chọn lại đúng finding; giảng viên chấp nhận, sửa và loại bỏ được. |
| AT-12 | Autosave hoàn tất trong 2 giây ở p95; refresh sau khi báo Đã lưu không mất dữ liệu. Hai phiên sửa cùng revision gây conflict rõ ràng và không ghi đè âm thầm. |
| AT-13 | Không thể duyệt khi còn criterion chưa xác nhận hoặc review item bắt buộc chưa xử lý. Duyệt thành công tạo immutable review snapshot. |
| AT-14 | Chỉ bài đã duyệt mới publish được. Publish thành công làm toàn bộ kết quả xuất hiện cùng lúc; batch publish tự loại/chặn bài chưa duyệt; publish lỗi không để sinh viên thấy dữ liệu một phần. Unpublish phải ẩn kết quả, giữ version/audit và gửi thông báo đúng BR-33. |
| AT-15 | Sinh viên chỉ thấy kết quả đã công bố, feedback được phép công khai và evidence tương ứng; không thấy dữ liệu kỹ thuật hoặc finding bị loại. |
| AT-16 | Nộp lại giữ phiên bản cũ, tạo phiên bản mới và cho phép so sánh hai lần liền kề theo criterion/finding mà không trộn kết quả. |
| AT-17 | Sinh viên mở được tối đa một review request cho mỗi criterion/result version; giảng viên trả lời, đóng và mọi thay đổi điểm tạo published version mới. |
| AT-18 | Admin lọc được job lỗi, thử lại an toàn và xem audit của upload, auto-evaluation, override, approve, publish, role change và retry. |

### 8.2. Phi chức năng

| ID | Điều kiện nghiệm thu |
|---|---|
| AT-19 | Trên môi trường tham chiếu với 100 phiên web, 20 upload và 10 job đồng thời: p95 API đọc/ghi không gồm upload/analysis không quá 2 giây; upload được enqueue không quá 5 giây sau khi truyền file xong. |
| AT-20 | Ít nhất 90% PDF hợp lệ tối đa 100 trang trong bộ tải hoàn tất từ Queued tới Awaiting review trong 10 phút; báo cáo phải ghi số trang, số job và latency provider. |
| AT-21 | Viewer hiển thị trang đầu trong 3 giây ở mạng 20 Mbps, tải trang theo nhu cầu và không tải lại toàn bộ PDF khi chuyển finding. |
| AT-22 | Kiểm thử file upload xác nhận giới hạn kích thước, magic bytes, MIME, parser validation, active-content rejection, quyền object và URL hết hạn. |
| AT-23 | Bộ test prompt injection xác nhận text trong PDF không thể đổi schema, quyền, provider config, system instruction hoặc khiến worker gọi tool ngoài pipeline đã khai báo. |
| AT-24 | Log không chứa nội dung PDF, password, session cookie, API key hoặc prompt đầy đủ; mọi request/job có correlation ID và lỗi kỹ thuật chỉ hiện cho Admin. Mọi kết nối ngoài dùng TLS 1.2 trở lên; file và backup được mã hóa khi lưu. |
| AT-25 | Các flow đăng nhập, upload, review, publish và xem kết quả đáp ứng WCAG 2.2 AA; dùng được bằng bàn phím, không keyboard trap, reflow ở 320 CSS px, zoom text 200%, trạng thái không chỉ biểu diễn bằng màu và PDF có chế độ text/outline thay thế cho canvas. |
| AT-26 | Hỗ trợ hai bản stable gần nhất của Chrome, Edge và Firefox; Safari hiện hành hỗ trợ flow Student; desktop từ 1280 px có review hai cột, tablet chuyển tab, mobile chỉ bắt buộc flow sinh viên cơ bản. |
| AT-27 | Backup hằng ngày được restore thử trên môi trường tách biệt; RPO không quá 24 giờ và RTO không quá 4 giờ. |
| AT-28 | CI phải pass lint/type check, unit test, integration test và E2E critical path. Domain reviewer hoàn tất một vòng UAT từ tạo đợt đến sinh viên xem kết quả. |
| AT-29 | Sau khi vận hành, Web/API đạt SLO 99,5% theo tháng, không tính maintenance đã thông báo; job bền vững qua restart. Tháng đầu không đạt SLO phải có incident review và kế hoạch sửa trước khi mở rộng người dùng. |
| AT-30 | E2E hoàn tất luồng Teacher tạo/publish rubric → Student nộp PDF → worker xử lý → Teacher review/approve/publish → Student mở evidence và gửi review request. |

## 9. Quyết định kiến trúc

```text
Browser
  ├─ React/Vite SPA ── REST/OpenAPI ── FastAPI modular monolith ── PostgreSQL
  │        └─ PDF.js                         │          └────────── File storage
  │                                         │
  └─ trạng thái job / review                └─ enqueue ── Redis ── Celery worker
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
- React Router quản lý URL theo Course/Assignment/Submission; TanStack Query quản lý server state. Không tiếp tục dùng `View` state trong `App.tsx` làm router sản phẩm.
- Việc nâng prototype từ React 18/Vite 6 lên baseline target phải là thay đổi dependency có kiểm thử riêng; không trộn vào công việc nối API.

### 9.4. API contract v1

#### 9.4.1. Quy ước chung

- REST/JSON dưới prefix `/api/v1`. FastAPI/Pydantic là nguồn sự thật và xuất OpenAPI tại `/api/v1/openapi.json`.
- TypeScript client và type được generate từ OpenAPI; frontend không duy trì model request/response viết tay song song với backend. OpenAPI đã chốt phải được lưu làm artifact CI và contract test phải phát hiện breaking change.
- JSON dùng `snake_case`; ID public là UUID; thời gian là ISO 8601 UTC; enum dùng literal chữ hoa như state machine trong tài liệu này.
- Response một resource trả trực tiếp resource. Danh sách trả `{items, page, page_size, total}`; `page_size` tối đa 100; sort và filter phải được khai báo trong OpenAPI.
- Authentication dùng opaque session cookie. Mọi mutation yêu cầu CSRF token. Backend kiểm tra role và quyền theo từng Course, Assignment, Submission hoặc Result; tài nguyên ngoài phạm vi của người dùng trả `404` để không làm lộ sự tồn tại.
- Mọi response có `X-Request-ID`. Lỗi dùng `application/problem+json` theo RFC 9457 với tối thiểu `type`, `title`, `status`, `detail`, `instance`, `code`, `request_id`; lỗi validation có thêm `errors[]` gồm `field`, `code`, `message`. Không trả stack trace, queue name, prompt hoặc nội dung PDF.
- `POST` tạo resource đồng bộ trả `201 Created` và `Location`. Tác vụ nền trả `202 Accepted` cùng `job_id`, `status_url` và `Retry-After`. Rate limit trả `429` và `Retry-After`.
- Resource có chỉnh sửa đồng thời trả `ETag: "rev-{revision}"`. Mutation phải gửi `If-Match`; revision cũ trả `412 Precondition Failed`, không ghi đè dữ liệu.
- `Idempotency-Key` bắt buộc cho upload, retry, approve, publish và unpublish. Cùng key và cùng payload trả lại kết quả trước đó; cùng key nhưng payload khác trả `409 Conflict`.

#### 9.4.2. Resource hierarchy và endpoint bắt buộc

`Course` là aggregate quản lý người học và quyền truy cập. `Assignment` luôn thuộc đúng một Course và sở hữu yêu cầu nộp bài, deadline, số lượt, RubricVersion và Submission. Không dùng `Assessment` như một entity API song song.

| Nhóm | Endpoint v1 | Hợp đồng chính |
|---|---|---|
| Session | `POST /auth/session`, `DELETE /auth/session`, `GET /users/me` | Đăng nhập/đăng xuất và trả user, role, quyền hiệu lực; session nằm trong cookie, không trả JWT để lưu ở browser. |
| Course | `GET/POST /courses`, `GET/PATCH /courses/{course_id}`, `GET/POST /courses/{course_id}/members`, `DELETE /courses/{course_id}/members/{user_id}` | CRUD Course và membership; chỉ Admin hoặc Teacher được phân công mới mutation. |
| Assignment | `GET/POST /courses/{course_id}/assignments`, `GET/PATCH /assignments/{assignment_id}`, `POST /assignments/{assignment_id}/open`, `POST /assignments/{assignment_id}/close` | Lưu details, submission requirements, rubric link và lifecycle. `open` chỉ thành công khi rubric/requirements hợp lệ. Từ **publish** chỉ dành cho kết quả; Assignment dùng **open/close**. |
| Rubric | `GET/POST /rubrics`, `GET /rubrics/{rubric_id}/versions`, `POST /rubrics/{rubric_id}/versions`, `PUT /assignments/{assignment_id}/rubric-version` | Nhân bản/version rubric; không sửa version đã được Assignment sử dụng. |
| Submission | `GET /assignments/{assignment_id}/submissions`, `POST /assignments/{assignment_id}/submissions`, `GET /submissions/{submission_id}`, `GET /submissions/{submission_id}/versions` | Upload dùng `multipart/form-data`; sau kiểm tra đồng bộ cơ bản, tạo DocumentVersion + AnalysisJob và trả `202`. Upload trùng theo BR-09 trả resource hiện có. |
| File/evidence | `GET /document-versions/{version_id}/download`, `GET /document-versions/{version_id}/evidence/{anchor_id}` | Kiểm tra quyền trước khi trả redirect/URL ký tối đa 5 phút hoặc evidence anchor; hỗ trợ mở đúng page/coordinate. |
| Job | `GET /analysis-jobs/{job_id}`, `POST /analysis-jobs/{job_id}/retry`, `GET /operations/analysis-jobs` | Frontend poll `status_url`; không giả lập phần trăm khi worker không có progress thật. MVP không dùng WebSocket/SSE. Retry tuân BR-10 và quyền vận hành. |
| Review | `GET /document-versions/{version_id}/review`, `POST/DELETE /document-versions/{version_id}/review-lock`, `PATCH /criterion-results/{criterion_result_id}` | Review workspace trả rubric snapshot, criterion result, finding và evidence; lock/heartbeat theo BR-18; edit dùng `If-Match`. |
| Approve/publish | `POST /document-versions/{version_id}/approve`, `POST /document-versions/{version_id}/publish`, `POST /published-results/{published_result_id}/unpublish` | Approve và publish là hai command riêng. Publish/unpublish atomic, idempotent, có reason/audit và không lộ kết quả một phần. |
| Student result | `GET /submissions/{submission_id}/published-result`, `POST /published-results/{published_result_id}/review-requests` | Chỉ trả published snapshot và field được phép công khai; tạo review request theo BR-23/BR-30. |
| Review request | `GET /assignments/{assignment_id}/review-requests`, `GET/PATCH /review-requests/{review_request_id}` | Teacher xem, phản hồi và đóng request; thay đổi điểm phải tạo PublishedResultVersion mới. |
| Operations | `GET/PATCH /users/{user_id}`, `GET /operations/audit-events` | Admin quản lý account và xem audit có filter/pagination; không trả secret hoặc nội dung tài liệu. |

#### 9.4.3. Hợp đồng trạng thái bất đồng bộ

1. Upload thành công ở tầng HTTP trả `202` với `submission_id`, `document_version_id`, `job_id`, `status`, `status_url` và `retry_after_seconds`.
2. Frontend poll `status_url` sau thời gian server chỉ định, dùng backoff từ 2 đến tối đa 10 giây và dừng ở `INVALID`, `PROCESSING_FAILED`, `AWAITING_REVIEW` hoặc `PUBLISHED`.
3. API chỉ trả `progress_percent` khi worker có số bước đo được; nếu không thì trả `null` cùng `status` và `status_message` trung thực.
4. `PROCESSING_FAILED` trả `retryable` và `user_action`; chi tiết kỹ thuật chỉ xuất hiện ở endpoint Operations cho Admin.
5. Browser refresh phải khôi phục trạng thái từ API bằng `status_url`; timer và state trong prototype không phải nguồn sự thật.

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
| Queue | Celery 5.6 + Redis 7 | Chỉ dùng task, retry, late acknowledgement và routing cơ bản; không dùng chain/canvas/beat trong MVP. Task phải idempotent. |
| Database | PostgreSQL 17, latest minor | Lưu nguồn sự thật, JSONB cho evaluator payload có schema và relational columns cho dữ liệu cần query. Không dùng MongoDB. |
| PDF backend | pypdf + pdfplumber | pypdf cho kiểm tra/cấu trúc/text cơ bản; pdfplumber cho character/line/table coordinate. Chạy trong worker process. |
| File storage | Storage adapter: local volume ở dev, S3-compatible ở staging/prod | Không buộc developer chạy MinIO hằng ngày; production không phụ thuộc local disk của container. |
| Auth | Opaque server session cookie + Argon2id | Cookie `HttpOnly`, `Secure`, `SameSite=Lax`, CSRF token cho mutation. Không lưu JWT trong localStorage. |
| AI integration | Provider adapter + JSON Schema | Criterion-scoped prompt, timeout, retry giới hạn, redaction và feature flag theo quality gate. |
| Deploy | Docker Compose + Caddy | Một host, TLS/reverse proxy đơn giản. Database và file storage có backup riêng. |
| Test | pytest, Vitest, Playwright, axe-core | Unit cho scoring/rule; integration cho DB/queue/storage; E2E cho critical flows và accessibility. |
| Quality | Ruff, mypy, ESLint, TypeScript strict | Chặn lỗi sớm trong CI; không thêm nhiều formatter/linter trùng chức năng. |

### 10.1. Vì sao Python không phải nút thắt chính

- Request web, upload, database và gọi LLM chủ yếu chờ I/O; FastAPI xử lý phần này bằng async I/O.
- Parse PDF và rule nặng chạy ở Celery worker process, tách khỏi API và có thể tăng số worker theo CPU.
- Pipeline giới hạn file 100 trang, cache Document IR và không parse lại PDF cho từng criterion.
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
| Chi phí/độ trễ LLM | Trung bình | Chunk theo criterion, cache IR, timeout, token budget, usage log và manual fallback. |
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
