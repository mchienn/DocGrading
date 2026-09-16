# Course Join Code/Link/QR Plan — T-027

**Scope:** Backend + frontend. Teacher sở hữu Course hoặc Admin quản lý join code có hạn; Student tự tham gia bằng code, link hoặc QR. Tái sử dụng `Membership` và `joined_via=CODE` từ T-026; không tạo lại bảng membership.

## Contract decisions

- `CourseJoinCode` giữ một credential đang chưa revoke cho mỗi Course; code cũ được giữ để phân biệt `JOIN_CODE_EXPIRED`, `JOIN_CODE_REVOKED` và `JOIN_CODE_INVALID`.
- Code chuẩn hóa thành 20 ký tự từ bảng chữ cái Base32 không mơ hồ, sinh bằng `secrets.choice`: 100 bit entropy, không dùng UUID cắt ngắn. Unique toàn hệ thống vì Student nhập code không kèm Course; điều này mạnh hơn unique trong từng Course.
- Tạo mới yêu cầu Course chưa có code chưa revoke. Đổi hạn cập nhật code hiện tại. Regenerate revoke code cũ và tạo code mới trong cùng transaction. Revoke/regenerate không sửa Membership đã có.
- QR chứa đúng join URL `/student/join?code=...`; link không chứa email, user ID, Course ID hoặc metadata nội bộ. Backend sinh SVG bằng `qrcode==8.2` đã pin.
- Join luôn đọc row code trực tiếp với `FOR UPDATE`; không cache. Cùng khóa Course serialize mutation Membership. Unique constraint `(course_id, user_id, role)` của T-026 là chốt DB cuối cùng. Student đã là member ACTIVE nhận `ALREADY_MEMBER`; không insert, không lỗi. Membership REMOVED được kích hoạt lại bằng `joined_via=CODE`.
- Rate limit DB-backed áp dụng đồng thời theo account và client IP đã được Uvicorn nhận từ proxy thuộc private CIDR cấu hình: 10 request/60 giây mặc định, row counter cập nhật dưới advisory lock, trả `429` cùng `Retry-After`. Compose chỉ tin proxy từ private network; API không được public trực tiếp. Không lưu IP thô; chỉ lưu SHA-256 subject.
- Audit cùng transaction cho create, expiry update, revoke, regenerate và Membership join/reactivate. Audit không lưu code hoặc join URL.
- Teacher/Admin endpoints dùng dependency ownership hiện có. Student join yêu cầu role `STUDENT`. Archived Course không cho tạo/đổi/revoke/regenerate hoặc join.

## Migration security checklist

Hard gate hoàn tất trước khi viết migration:

- [x] **SC-1 — pin `search_path`:** câu lệnh đầu tiên của cả `upgrade()` và `downgrade()` phải là `SET search_path TO public`; mọi PL/pgSQL function mới phải khai báo `SET search_path = pg_catalog, public, pg_temp`.
- [x] **SC-2 — giữ guard TRUNCATE append-only:** migration không alter, disable, replace, truncate hoặc drop `public.audit_events`, `public.published_result_versions` hay row/TRUNCATE guard của chúng. PostgreSQL roundtrip phải chứng minh cả hai bảng vẫn chặn `TRUNCATE` sau upgrade và downgrade/re-upgrade. Bảng join-code/rate-limit không append-only.
- [x] **SC-3 — schema-qualify mọi DDL/FK:** mọi thao tác Alembic table/index/constraint phải truyền `schema="public"`; mọi FK dùng `public.<table>.<column>`; raw SQL phải qualify table/index/type/function thuộc ứng dụng bằng `public.`.
- [x] **Downgrade safety:** lock bảng T-027 theo thứ tự cố định; từ chối downgrade khi `course_join_codes` còn dữ liệu; rate-limit counters là dữ liệu vận hành có hạn và được phép drop. Chỉ xóa object T-027 theo thứ tự phụ thuộc.

## Implementation sequence

1. Thêm ORM, migration, config rate-limit/frontend origin và dependency QR đã pin.
2. Thêm schema/service/router cho lifecycle code, QR SVG, rate-limit và join atomic.
3. Thêm test API/service/PostgreSQL cho error code, revoke, regenerate, idempotency, race, rate-limit, ownership, audit, privacy và migration.
4. Regenerate OpenAPI client; thêm Teacher join-code panel và Student manual/deep-link flow. Deep link chỉ prefill code; Student phải xác nhận Join trước khi POST.
5. Chạy Ruff, Black, full Pytest, frontend typecheck/build, Alembic roundtrip và browser UAT.
6. Rà Functional Correctness, Data Integrity & Integration, Security & Privacy; cập nhật tài liệu bằng kết quả đã kiểm chứng.

## Required proof

### Functional Correctness

- Code sai trả `JOIN_CODE_INVALID`; code hết hạn trả `JOIN_CODE_EXPIRED`; revoked trả `JOIN_CODE_REVOKED`.
- Revoke hiệu lực ở request kế tiếp, không cache/delay. Regenerate không đổi Membership cũ.
- Join lặp của member ACTIVE trả cùng Membership với `ALREADY_MEMBER`.

### Data Integrity & Integration

- Code có ít nhất 100 bit entropy và unique DB-enforced.
- Hai request join đồng thời cùng code/account tạo đúng một Membership.
- Membership dùng model/constraint T-026; không có bảng membership thứ hai hoặc check-then-insert không khóa.

### Security & Privacy

- Account/IP rate-limit trả `429` + `Retry-After`.
- QR/link chỉ encode code. Audit không chứa code, URL, email hoặc IP.
- Chỉ Teacher sở hữu/Admin quản lý code; Student chỉ join chính account của mình.

## Verification results

- Backend trên PostgreSQL sạch `docgrading_t027_full`: `uv run ruff check .`, `uv run black --check .`, `uv run alembic upgrade head`, `RUN_DATABASE_TESTS=1 uv run pytest -q` — **426 passed**.
- T-027 database integration: **4 passed**; gồm lifecycle/error/audit/privacy/rate-limit, hai join đồng thời chỉ một Membership và migration append-only guard.
- Migration DB thật riêng: `upgrade head`, `downgrade 20260916_0014`, `upgrade head` — pass.
- Frontend: `pnpm typecheck` và `pnpm build` — pass; chỉ còn warning chunk size/Zod annotation đã có.
- Browser UAT qua Compose: Teacher tạo code/link/QR; Student mở link, code chỉ prefill trước xác nhận, join thành công; DB có đúng `ACTIVE:CODE:1`. Revoke cũ trả `Join code is revoked`; regenerate rồi ép hết hạn trả `Join code is expired`.
- Reviewer correctness và security recheck: không còn finding; proxy trust/explicit consent và QR cache đã được sửa, tài liệu production đã đồng bộ.
