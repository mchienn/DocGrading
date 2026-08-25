# DocGrading backend

FastAPI API và Celery worker của DocGrading. Backend dùng PostgreSQL cho dữ liệu, Redis cho queue/result và volume riêng cho PDF development.

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

Đổi `POSTGRES_PASSWORD` trong `.env`. Không commit `.env`.

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
