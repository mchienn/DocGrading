# DocGrading backend

FastAPI API và Celery worker của DocGrading. Backend dùng PostgreSQL cho dữ liệu, Redis cho queue/result và LocalStack S3 cho PDF development.

## Yêu cầu

- Python 3.13
- uv 0.11.19 hoặc tương thích
- Docker Engine và Docker Compose v2

## Cấu hình

Từ repository root:

```bash
cp .env.example .env
```

PowerShell:

```powershell
Copy-Item .env.example .env
```

Đổi `POSTGRES_PASSWORD` và đặt `LOAD_SMOKE_PASSWORD` không rỗng trong `.env`. Không commit `.env`.

## Chatbot: lỗi OpenAI và thời gian chờ tối đa

Mọi lỗi của SDK OpenAI (timeout, mất kết nối, 429, 5xx, 401/403 và các lỗi API khác) được bọc thành `LLMUnavailableError`/`EmbeddingUnavailableError` (chỉ mang tên lớp lỗi; lỗi gốc chỉ nằm trong log server) và chat luôn trả HTTP 200:

| Đường | Khi provider lỗi |
|---|---|
| Embedding câu hỏi (truy hồi vector) | Bỏ phần vector, vẫn truy hồi full-text; log warning |
| LLM router (câu `UNKNOWN`) | Trả lời như `UNKNOWN` (câu hướng dẫn mặc định); log warning |
| Trả lời có trích dẫn | Trả các đoạn truy hồi được, dòng đầu "Hệ thống chưa tạo được câu trả lời tự động lúc này, đây là các đoạn liên quan."; `llm_unavailable=true` |
| Tóm tắt bài nộp | Thông báo "Hệ thống chưa tạo được bản tóm tắt lúc này…", không ghi cache; `llm_unavailable=true` (cũng `true` khi model trả rỗng) |

Thiếu API key được xử lý giống provider lỗi; response không nhắc tên biến môi trường.

Khi indexing gặp lỗi provider embedding, worker vẫn lưu chunk (`embedding = NULL`, truy hồi full-text vẫn dùng được) và ghi cảnh báo kèm id phiên bản. Không có job tự quét lại; khi provider hoạt động trở lại, chạy `uv run python -m scripts.backfill_chunks --fill-embeddings` (trên đúng database cần bổ sung) để nhúng các chunk còn thiếu vector.

Cấu hình (mặc định): `LLM_TIMEOUT_SECONDS=30`, `LLM_MAX_RETRIES=1` (trả lời), `LLM_SUMMARY_MAX_RETRIES=2`, `EMBEDDING_TIMEOUT_SECONDS=20`, `EMBEDDING_MAX_RETRIES=2`. Embedding của câu hỏi chat không dùng vòng chờ 429 riêng (20/40/…/120 s) của backfill; chỉ còn retry của SDK.

### Hạn chót mỗi lượt chat

Các lời gọi provider (embedding, router, trả lời, tóm tắt) chạy dưới hạn chót tính từ lúc bắt đầu lượt chat; hết hạn thì lời gọi đang chờ bị huỷ ngay trong task đó (SDK đóng HTTP client trong `finally`, không còn task nền):

| Biến | Mặc định | Áp dụng |
|---|---:|---|
| `CHAT_TURN_DEADLINE_SECONDS` | 25 | Router + embedding câu hỏi + trả lời có trích dẫn, cộng dồn trong một lượt. Hết hạn: trả câu dự phòng và các đoạn truy hồi (full-text nếu embedding bị cắt), `llm_unavailable=true` |
| `QUERY_EMBEDDING_TIMEOUT_SECONDS` | 6 | Trần riêng cho embedding câu hỏi, nằm trong 25 s. Hết trần: bỏ vector, truy hồi full-text, LLM trả lời vẫn dùng phần còn lại của 25 s |
| `LLM_ROUTER_TIMEOUT_SECONDS` | 8 | Router: timeout riêng, không retry (và không vượt phần còn lại của 25 s). Hết hạn: trả lời như `UNKNOWN` |
| `SUMMARY_DEADLINE_SECONDS` | 90 | Tóm tắt (nhiều lần gọi map-reduce), thay cho 25 s. Hết hạn: `SUMMARY_UNAVAILABLE_TEXT`, không ghi cache |

Hạn chót chỉ bao các lời gọi provider; truy vấn PostgreSQL (phạm vi, truy hồi full-text, trích dẫn, ghi cache) không bị cắt.

Thời gian đo được với cấu hình mặc định, provider giả lập bằng `httpx.MockTransport` trả `429` kèm `Retry-After: 120` (SDK sẽ chờ 120 s trước khi thử lại), không bao giờ trả lời, hoặc trả lời ngay; `handle_chat()` trên `docgrading_test`, 2026-10-16 (log: `docs/benchmarks/test-runs/2026-10-16-chat-deadline-measurements.txt`, lệnh: `RUN_SLOW_DEADLINE_TESTS=1` trong `tests/test_chat_deadlines_db.py`):

| Lượt chat | Provider | Thời gian đo | Kết quả |
|---|---|---:|---|
| Hỏi nội dung | embedding không trả lời, LLM trả lời ngay | 6,08 s | câu trả lời của LLM (cắt embedding ở 6 s) |
| Hỏi nội dung | `Retry-After: 120` cho embedding và trả lời | 25,05 s | câu dự phòng + đoạn full-text |
| Tìm đoạn | `Retry-After: 120` cho embedding | 6,05 s | đoạn full-text |
| Câu `UNKNOWN` (router) | không bao giờ trả lời | 8,01 s | câu mặc định `UNKNOWN` |
| Router mất 7 s rồi chuyển sang hỏi nội dung | `Retry-After: 120` cho phần còn lại | 25,04 s | câu dự phòng + đoạn full-text |
| Tóm tắt | `Retry-After: 120` | 90,03 s | `SUMMARY_UNAVAILABLE_TEXT`, không cache |

Trước thay đổi này, các kịch bản tương ứng trong `tests/test_chat_deadlines.py` vẫn còn chờ khi guard 10 s của test hết hạn (test fail); thời gian thực khi không có hạn chót không được đo.

## Chạy toàn bộ stack

```bash
docker compose up --build
```

Frontend production assets qua Caddy: `http://localhost:5173`; API loopback trực tiếp: `http://localhost:8000`; OpenAPI: `http://localhost:8000/api/v1/openapi.json`. Production giữ port API private, đặt `JOIN_RATE_LIMIT_HASH_SECRET` ngẫu nhiên tối thiểu 32 ký tự, terminate TLS trực tiếp tại Caddy và dùng `/api` same-origin. Compose mặc định chỉ trust IP Caddy cố định `172.30.255.3`; nếu đổi topology, đặt `FORWARDED_ALLOW_IPS` thành đúng IP proxy. Nếu có TLS proxy phía trước, cấu hình Caddy chỉ trust CIDR chính xác của proxy bằng `trusted_proxies` + `trusted_proxies_strict`.

Kiểm tra API:

```bash
curl http://localhost:8000/api/v1/health
```

Kết quả: `{"status":"ok"}`.

Kiểm tra queue:

```bash
docker compose exec api python -c "from app.workers.tasks import healthcheck; result = healthcheck.delay(); print(result.get(timeout=10))"
```

Kết quả: `{'status': 'ok'}`.

Dừng stack:

```bash
docker compose down
```

Thêm `--volumes` chỉ khi chủ động muốn xóa dữ liệu development.

## Load, metrics, backup và restore smoke

Các smoke service chỉ chạy khi `APP_ENV=development`. Từ repository root, sau khi stack healthy:

```bash
docker compose --profile smoke run --rm load-smoke
docker compose --profile ops run --rm backup
docker compose --profile ops run --rm restore-smoke
docker compose --profile smoke --profile ops config --quiet
```

Load mặc định dùng 8 user đồng thời trong 30 giây, think time 0,05 giây và tối đa 5 upload/publish round cho mỗi Student. Đổi tải bằng `LOAD_USERS` và `LOAD_DURATION_SECONDS`. Kết quả JSON nằm tại `artifacts/t022-load-results.json`.

`GET /metrics` trả Prometheus text cho Admin đã đăng nhập: số AnalysisJob theo status, queue depth và tuổi trung bình của job `QUEUED`/`RUNNING`.

Backup logical nằm tại `backups/docgrading.dump`; row count nguồn nằm cạnh backup. Cả `artifacts/` và `backups/` đều bị Git ignore. Backup dừng nếu row count thay đổi trong lúc `pg_dump`. Restore luôn drop/recreate `docgrading_restore` trên PostgreSQL tmpfs tách mạng ứng dụng, đối chiếu row count, kiểm tra critical-flow join và chứng minh `TRUNCATE public.audit_events` vẫn bị chặn.

## Chạy process Python local

Khởi động PostgreSQL và Redis trước, đặt `POSTGRES_HOST=localhost`, `REDIS_HOST=localhost` trong `.env`, rồi:

```bash
cd backend
uv sync
uv run alembic upgrade head
uv run uvicorn app.main:app --reload
```

Terminal khác:

```bash
cd backend
uv run celery -A app.workers.celery_app:celery_app worker --loglevel=INFO
```

## Migration

Tạo revision mới sau khi T-006 bổ sung model:

```bash
cd backend
uv run alembic revision --autogenerate -m "describe change"
uv run alembic upgrade head
```

Revision `20260825_0001` là baseline rỗng và không tạo schema domain.

## Lập chỉ mục lại sau khi đổi parser

Khi `PARSER_VERSION` (trong `app/services/document_ir.py`) tăng, IR, chunk và embedding cũ không tự cập nhật. `scripts/reindex_documents.py` dựng lại chúng cho mọi phiên bản có IR cũ hơn (chạy lại an toàn: phiên bản đã ở parser hiện tại được bỏ qua) và, với `--summaries`, tạo lại tóm tắt để row có `source_hash` thật. PDF lấy từ object storage hoặc `--pdf-dir` (so khớp theo SHA-256); không tìm thấy PDF thì giữ nguyên dữ liệu cũ của phiên bản đó. Ghi thật cần `--expect-db` đúng tên database đang cấu hình.

```bash
cd backend
uv run python -m scripts.reindex_documents --dry-run --pdf-dir ../test_submissions
uv run python -m scripts.reindex_documents --pdf-dir ../test_submissions \
  --expect-db <POSTGRES_DB> --summaries --report reindex.json
```

Sao lưu database trước khi ghi. Lệnh gọi API embedding/LLM thật (tốn token).

## Chất lượng mã

```bash
cd backend
uv run ruff check .
uv run black --check .
uv run pytest
```

## Lỗi thường gặp

- Compose báo thiếu biến: tạo `.env` từ `.env.example`.
- API dừng khi khởi động: xem log migration bằng `docker compose logs api`.
- Worker không trả task: kiểm tra `docker compose ps` và `docker compose logs worker redis`.
- Port bận: đổi `API_PORT`, `POSTGRES_PORT` hoặc `REDIS_PORT` trong `.env`.
