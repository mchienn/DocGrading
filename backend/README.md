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

## Chạy toàn bộ stack

```bash
docker compose up --build
```

API: `http://localhost:8000`; OpenAPI: `http://localhost:8000/api/v1/openapi.json`.

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
