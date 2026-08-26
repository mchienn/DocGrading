# Thiết kế schema và migration domain DocGrading — T-006

Ngày: 2026-08-25

Trạng thái: Đã duyệt trong phiên thiết kế

## 1. Mục tiêu và phạm vi

T-006 bổ sung persistence domain đầu tiên cho backend DocGrading bằng SQLAlchemy 2 typed ORM trên async foundation của T-005 và một Alembic revision PostgreSQL có thể upgrade/downgrade.

Trong phạm vi:

- `User`, `Course`, `Membership`, `Assignment`, `AssignmentRequirement`;
- `RubricVersion`, `CriterionVersion`, `TemplateVersion`;
- `Submission`, `DocumentVersion`, `AnalysisJob`, `AuditEvent`;
- foreign key, ownership, role, lifecycle, uniqueness, check constraint và index cần thiết;
- ràng buộc database bảo vệ rubric đã được dùng;
- Alembic revision nối tiếp `20260825_0001`;
- test metadata và test invariant trên PostgreSQL thật.

Ngoài phạm vi:

- route hoặc endpoint API;
- service/application logic của T-007/T-008;
- evaluator, review result, finding, evidence và publish result của các backlog sau;
- mọi thay đổi trong `frontend/`.

Nguồn yêu cầu áp dụng theo thứ tự: yêu cầu T-006, sheet `Đặc tả tính năng` #1 và #2 trong PM tracker, rồi `docs/design/PROJECT_SCOPE_BUSINESS_RULES_TECH_STACK.md`. Bảng SRS §5.4 còn dùng các tên cũ `Assessment`, `Criterion` và `AuditLog`; các tên đó không được tạo song song vì tài liệu thiết kế canonical và backlog đã thay bằng `Course`/`Assignment`, các entity có version và `AuditEvent`.

## 2. Tổ chức code

Giữ `app.db.base.Base(AsyncAttrs, DeclarativeBase)` làm declarative base. `app/models/` được chia theo ranh giới domain:

```text
app/models/
├── __init__.py
├── enums.py
├── mixins.py
├── identity.py
├── course.py
├── assignment.py
├── rubric.py
├── submission.py
├── analysis.py
└── audit.py
```

Trách nhiệm:

- `enums.py`: enum domain dùng chung, giá trị lưu database là chữ hoa;
- `mixins.py`: UUID primary key, created/updated timestamp và optimistic `revision` cho resource mutable;
- `identity.py`: `User`;
- `course.py`: `Course`, `Membership`;
- `assignment.py`: `Assignment`, `AssignmentRequirement`;
- `rubric.py`: `RubricVersion`, `CriterionVersion`, `TemplateVersion`;
- `submission.py`: `Submission`, `DocumentVersion`;
- `analysis.py`: `AnalysisJob`;
- `audit.py`: `AuditEvent`;
- `__init__.py`: import/export đủ 12 model để Alembic metadata thấy toàn bộ schema.

`alembic/env.py` import `app.models` trước khi đọc `Base.metadata`. Import model không mở kết nối database.

## 3. Quy ước persistence

- Public ID dùng PostgreSQL UUID và Python `uuid.UUID`; default tạo tại application bằng `uuid4`.
- Timestamp dùng `TIMESTAMP WITH TIME ZONE`; `created_at`/`occurred_at` có server default `CURRENT_TIMESTAMP`; timestamp thay đổi được cập nhật bằng ORM và có server expression phù hợp khi cần.
- Enum dùng PostgreSQL native enum có tên ổn định để migration quản lý tường minh.
- Cấu hình evaluator, evidence, levels, snapshot và before/after dùng JSONB; CHECK xác nhận object khi trường có giá trị.
- Chuỗi nghiệp vụ có giới hạn độ dài. Reason và các trường bắt buộc không chấp nhận chuỗi rỗng sau `btrim`.
- Constraint/index đều có tên ổn định. FK lịch sử dùng `RESTRICT`; child chỉ dùng `CASCADE` khi vòng đời hoàn toàn thuộc aggregate và không làm mất provenance.
- `revision` bắt đầu từ 1 và luôn dương cho resource mutable; API sau dùng trường này với ETag/If-Match.

## 4. Mô hình dữ liệu

### 4.1. User

`users` lưu:

- `id`, `email`, `display_name`;
- `password_hash` để auth backlog sau sử dụng, không lưu plaintext;
- `roles` là mảng không rỗng của `ADMIN`, `TEACHER`, `STUDENT`, cho phép một tài khoản có nhiều vai trò;
- `status` là `ACTIVE` hoặc `LOCKED`;
- `revision`, `created_at`, `updated_at`.

Email unique case-insensitive bằng unique index trên `lower(email)`. Role membership cụ thể trong Course vẫn được biểu diễn bằng `Membership`, không suy ra từ global role duy nhất.

### 4.2. Course và Membership

`courses` lưu:

- `id`, `code`, `name`, `term`;
- `owner_teacher_id → users.id`;
- `revision`, `created_at`, `updated_at`.

Code unique. Trigger xác nhận owner có global role `TEACHER`.

`memberships` lưu:

- `id`, `course_id → courses.id`, `user_id → users.id`;
- `role` chỉ nhận `TEACHER` hoặc `STUDENT`;
- `status` là `ACTIVE` hoặc `INACTIVE`;
- `created_at`, `updated_at`.

Unique `(course_id, user_id, role)`. Trigger xác nhận role membership tồn tại trong `User.roles`. Trigger trên `users.roles` chặn gỡ role nếu việc đó làm Course ownership hoặc Membership hiện hữu mất hợp lệ.

### 4.3. Assignment và AssignmentRequirement

`assignments` lưu:

- `id`, `course_id → courses.id`, `created_by_teacher_id → users.id`;
- `rubric_version_id → rubric_versions.id`;
- `title`, `description`, `due_at`, `max_submissions` mặc định 3;
- `status`: `DRAFT`, `OPEN`, `CLOSED`, `ARCHIVED`;
- `published_at`, `closed_at`, `first_submission_at`, `revision`, `created_at`, `updated_at`.

`max_submissions` nằm trong 1..5. `DRAFT` có `published_at IS NULL`; mọi trạng thái còn lại có `published_at IS NOT NULL`. Publish theo ngôn ngữ PM tracker là lần chuyển đầu từ `DRAFT` sang `OPEN`. T-007/T-008 phải giới hạn Student theo `Membership(role=STUDENT, status=ACTIVE)` và `published_at IS NOT NULL`; T-006 chỉ cung cấp cấu trúc dữ liệu, không tạo query hoặc endpoint.

`first_submission_at` ban đầu là `NULL`, chỉ được database đặt đúng một lần trong nested Submission trigger khi Assignment nhận Submission đầu tiên và không thể xóa hoặc thay đổi. Direct INSERT/UPDATE cung cấp marker bị từ chối để không giả mạo provenance. Marker này lưu sự kiện lịch sử nên vẫn tồn tại khi Submission bị xóa hoặc chuyển sang Assignment khác.

`assignment_requirements` lưu:

- `id`, `assignment_id → assignments.id`;
- `kind`, `label`, `description`, `is_required`, `position`;
- giới hạn `max_file_size_bytes`, `max_page_count`, cờ `text_layer_required`;
- `template_version_id → template_versions.id` nullable;
- `created_at`, `updated_at`.

Unique `(assignment_id, position)`; các giới hạn số phải dương khi có.

### 4.4. RubricVersion, CriterionVersion và TemplateVersion

Không tạo entity mutable `Rubric` song song. Một UUID logic gom lịch sử, còn mỗi row là một version.

`rubric_versions` lưu:

- `id`, `rubric_id`, `version_number`;
- `name`, `description`, `status` (`DRAFT`, `PUBLISHED`, `ARCHIVED`);
- `calculation_method`, `total_weight`;
- `owner_user_id → users.id`, `created_by_user_id → users.id`;
- `source_version_id → rubric_versions.id` nullable để truy nguyên clone/version;
- `published_at`, `revision`, `created_at`, `updated_at`.

Unique `(rubric_id, version_number)`; version dương; weight trong 0..100. Việc tổng criterion đang bật bằng 100 trước publish là command validation của T-007/T-008; database vẫn chặn weight từng criterion ngoài miền hợp lệ.

`criterion_versions` lưu:

- `id`, `criterion_id`, `rubric_version_id → rubric_versions.id`;
- `code`, `title`, `description`, `scope`;
- `weight`, `position`, `is_enabled`, `evaluation_method`;
- `levels`, `evaluator_config`, `evidence_requirements` JSONB;
- `revision`, `created_at`, `updated_at`.

Unique `(rubric_version_id, criterion_id)`, `(rubric_version_id, code)` và `(rubric_version_id, position)`. Weight nằm trong 0..100. Mỗi row là snapshot criterion thuộc đúng một RubricVersion; không dùng quan hệ many-to-many mutable.

`template_versions` lưu:

- `id`, `template_id`, `version_number`;
- `name`, `description`, `owner_user_id → users.id`, `created_by_user_id → users.id`;
- `structure` JSONB, `storage_key` nullable, `sha256` nullable;
- `created_at`.

Unique `(template_id, version_number)`. Nếu có checksum thì phải là 64 ký tự hex; file nằm private storage, không lưu blob trong PostgreSQL.

### 4.5. Submission và DocumentVersion

`submissions` là logical submission của một Student trong một Assignment:

- `id`, `assignment_id → assignments.id`, `student_id → users.id`;
- `created_at`, `updated_at`.

Unique `(assignment_id, student_id)`. Trigger xác nhận Student có global role `STUDENT` và active Student membership trong Course chứa Assignment.

`document_versions` là từng lần nộp:

- `id`, `submission_id → submissions.id`;
- `version_number`, `previous_version_id → document_versions.id` nullable;
- `storage_key`, `original_filename`, `content_type`, `size_bytes`, `page_count` nullable, `sha256`;
- `status`: `UPLOADING`, `VALIDATING`, `INVALID`, `QUEUED`, `PROCESSING`, `AWAITING_REVIEW`, `APPROVED`, `PUBLISHED`, `PROCESSING_FAILED`;
- `failure_code`, `failure_detail`, `created_at`, `updated_at`.

Unique `(submission_id, version_number)` và `(submission_id, sha256)`. Size/version dương, page count dương khi có, SHA-256 đúng 64 ký tự hex. `previous_version_id` cho lịch sử so sánh; validation cùng Submission sẽ nằm ở service T-009.

### 4.6. AnalysisJob

`analysis_jobs` lưu:

- `id`, `document_version_id → document_versions.id`, `rubric_version_id → rubric_versions.id`;
- `status`: `QUEUED`, `RUNNING`, `SUCCEEDED`, `FAILED`, `CANCELLED`;
- `attempt_count`, `max_attempts` mặc định 3;
- `snapshot` JSONB bắt buộc, chứa Course/Assignment/Rubric/Criterion và evaluator/parser/model version áp dụng;
- `queued_at`, `started_at`, `finished_at`, `error_code`, `error_detail`, `created_at`, `updated_at`.

CHECK giữ attempt trong 0..max, max dương và snapshot là object. Partial unique index bảo đảm tối đa một job `QUEUED` hoặc `RUNNING` cho `(document_version_id, rubric_version_id)`.

### 4.7. AuditEvent

`audit_events` lưu:

- `id`, `resource_type`, `resource_id`, `action`;
- `actor_type`: `USER` hoặc `SYSTEM`;
- `actor_user_id → users.id` nullable;
- `before` và `after` JSONB nullable;
- `reason` bắt buộc, `occurred_at` có server default.

CHECK yêu cầu:

- actor `USER` có `actor_user_id`; actor `SYSTEM` không có FK actor;
- ít nhất một trong `before`/`after` tồn tại;
- snapshot khi có là JSON object;
- reason không trắng.

`resource_id` không có FK để AuditEvent tồn tại độc lập với vòng đời entity. Trigger chặn UPDATE và DELETE, biến bảng thành append-only ở tầng database.

## 5. Invariant bất biến rubric

PostgreSQL function/trigger là authority vì invariant công bằng không được phép bị bypass bởi bulk ORM update, SQL trực tiếp, worker hoặc migration dữ liệu ứng dụng.

1. Trigger trên `submissions` đặt `assignments.first_submission_at` bằng thời điểm database khi nhận Submission đầu tiên. Reassignment đặt marker cho Assignment mới; marker của Assignment cũ không bị xóa.
2. Trigger trên `assignments` từ chối marker khác `NULL` khi direct INSERT, từ chối direct UPDATE từ `NULL` và chặn thay đổi hoặc xóa `first_submission_at` sau khi marker đã có giá trị. Chỉ nested Submission trigger được phép đặt marker.
3. Trigger trên `rubric_versions` chặn `UPDATE` và `DELETE` khi tồn tại Assignment tham chiếu row có `first_submission_at IS NOT NULL`.
4. Trigger trên `criterion_versions` chặn `INSERT`, `UPDATE` và `DELETE` nếu parent cũ hoặc parent mới là RubricVersion đã đóng băng. Reparent không được dùng để đưa criterion vào hoặc ra khỏi rubric đã dùng.
5. Trigger trên `assignments` chặn thay `rubric_version_id` khi `first_submission_at IS NOT NULL`.
6. RubricVersion dùng chung bị đóng băng toàn cục từ Submission đầu tiên của bất kỳ Assignment nào tham chiếu version đó; xóa hoặc chuyển Submission không làm mất trạng thái đóng băng.
7. Trước Submission đầu tiên, draft/version hiện hành vẫn có thể cập nhật; thay đổi sau điểm đóng băng phải INSERT RubricVersion/CriterionVersion mới và chỉ áp dụng cho Assignment khác chưa từng nhận Submission.

Các trigger dùng transaction advisory lock theo khóa user, rubric và assignment để serialize role check, tạo Assignment, nhận Submission và thay đổi version. Thứ tự canonical trong một thao tác là rubric/user trước assignment; service nhiều statement ở backlog sau phải pre-acquire theo cùng thứ tự và retry transaction bị PostgreSQL chọn làm deadlock victim.

FK `RESTRICT` tiếp tục bảo vệ việc xóa row đang được tham chiếu. Trigger trả SQLSTATE có thông báo domain ổn định để test xác nhận đúng invariant.

## 6. Alembic revision

Tạo revision `20260825_0002_domain_schema` với:

```python
revision = "20260825_0002"
down_revision = "20260825_0001"
```

Upgrade:

1. tạo native enum types;
2. tạo bảng theo thứ tự dependency;
3. tạo named indexes, gồm partial unique index job active;
4. tạo PostgreSQL functions và triggers cho role/ownership, durable first-submission marker, rubric immutability, advisory serialization và AuditEvent append-only.

Downgrade:

1. drop triggers và functions;
2. drop indexes/bảng theo thứ tự dependency ngược;
3. drop native enum types.

Migration viết tay và tự chứa schema; không phụ thuộc ORM runtime để downgrade. Upgrade/downgrade dùng transactional DDL của PostgreSQL.

## 7. TDD và kiểm chứng

### 7.1. Test không cần database

Test metadata/mappers phải kiểm tra:

- đủ đúng 12 model và table;
- model import/configure mapper thành công;
- UUID, timezone timestamp, enum/ARRAY/JSONB đúng loại;
- FK graph, relationship, unique/check constraint và index quan trọng;
- Alembic metadata import thấy toàn bộ table.

Test được viết trước model và phải fail vì symbol/table chưa tồn tại.

### 7.2. Test PostgreSQL tích hợp

Test integration chỉ bật bằng biến môi trường riêng để CI hiện tại không cần thêm database service. Trong stack Docker nghiệm thu, test phải:

- tạo users Teacher/Student, Course, Membership, RubricVersion/CriterionVersion, Assignment và Submission hợp lệ;
- chứng minh marker freeze ban đầu `NULL`, được đặt khi nhận/reassign Submission và không mất sau delete/reassign;
- chứng minh UPDATE/DELETE rubric và criterion sau Submission bị từ chối kể cả khi Submission đầu tiên đã bị xóa;
- chứng minh INSERT criterion và reparent vào/ra rubric đã đóng băng bị từ chối;
- chứng minh đổi rubric của Assignment hoặc sửa marker freeze sau Submission bị từ chối;
- chứng minh owner/membership sai role, gỡ role đang dùng, role array chứa `NULL` và text nghiệp vụ chỉ có whitespace bị từ chối;
- chứng minh các race role/rubric/Assignment/Submission được serialize bằng advisory lock;
- chứng minh actor AuditEvent sai constraint và AuditEvent update/delete bị từ chối.

Test cleanup bằng transaction/fixture hoặc reset schema phù hợp, không phụ thuộc thứ tự test.

### 7.3. Cổng hoàn tất

Chạy từ `backend/`:

1. `uv run ruff check .`;
2. `uv run black --check .`;
3. `uv run pytest`;
4. trên Docker PostgreSQL thật: `alembic upgrade head`;
5. chạy test invariant tích hợp;
6. `alembic downgrade 20260825_0001` và xác nhận domain schema đã gỡ;
7. `alembic upgrade head` lại;
8. reviewer độc lập kiểm tra invariant, migration symmetry, schema và phạm vi.

Diff cuối không được chứa file dưới `frontend/` hoặc `backend/app/api/routers/`. Commit implementation dùng conventional commit `feat(backend): add domain schema and migration`. Báo cáo cuối đúng ba phần: `Đã triển khai`, `Kiểm chứng`, `HEAD commit`.

## 8. Rủi ro và quyết định

- **PostgreSQL-specific trigger:** chấp nhận vì stack canonical đã chốt PostgreSQL 17; đổi database không thuộc MVP.
- **Schema không thay API authorization:** `published_at`, Membership và ownership tạo dữ liệu cần thiết; object authorization/404 masking thuộc T-007/T-008.
- **Không tạo entity ngoài backlog:** evaluator config và snapshot tạm dùng JSONB để không kéo các model Result/Finding/Evidence vào T-006.
- **SRS tên cũ:** không tạo compatibility alias hoặc bảng song song. Clean cutover theo PM tracker và tài liệu thiết kế canonical tránh hai domain contract.
- **Rubric validation nhiều row:** total weight bằng 100 và đủ level/evaluator được kiểm tra tại command publish ở backlog sau; T-006 chỉ đặt miền giá trị và invariant không thể bypass sau Submission.
- **Advisory lock:** trigger bảo vệ invariant và PostgreSQL deadlock detection ngăn silent corruption. Application service nhiều statement phải tuân theo thứ tự lock canonical và retry transaction bị abort; T-006 không tạo service/API.
