# DocGrading

DocGrading hỗ trợ đánh giá báo cáo PDF theo rubric. Kết quả tự động chỉ là đề xuất; giảng viên duyệt, chỉnh sửa và công bố trước khi sinh viên thấy.

Release hiện tại: `v0.1.0`.

## Yêu cầu

- Git.
- Docker Engine hoặc Docker Desktop.
- Docker Compose v2 (`docker compose version`).
- Port local mặc định: `5173`, `8000`, `5432`, `6379`, `9000`.

Python, Node.js và pnpm chỉ cần khi chạy development ngoài container.

## Chạy toàn bộ project bằng Docker Compose

Clone repository:

```bash
git clone https://github.com/mchienn/DocGrading.git
cd DocGrading
```

Tạo file môi trường.

Linux/macOS:

```bash
cp .env.example .env
```

PowerShell:

```powershell
Copy-Item .env.example .env
```

Đổi `POSTGRES_PASSWORD` trong `.env`. Chỉ đặt `LOAD_SMOKE_PASSWORD` khi chạy load smoke. `.env` bị Git ignore; không commit secrets.

Build và khởi động:

```bash
docker compose up --build
```

API tự chạy Alembic migration tới head. Stack gồm PostgreSQL, Redis, LocalStack S3, FastAPI, Celery worker và frontend production assets do Caddy phục vụ.

Kiểm tra:

```bash
docker compose ps
curl http://localhost:5173/api/v1/health
```

Kết quả health:

```json
{"status":"ok"}
```

Địa chỉ local:

- App: <http://localhost:5173>
- API trực tiếp, loopback-only: <http://localhost:8000>
- OpenAPI: <http://localhost:8000/api/v1/openapi.json>
- LocalStack S3: <http://localhost:9000>

Database mới chưa có account mặc định. Project không có public signup hoặc default password. Việc provision Admin đầu tiên đang được theo dõi tại [#27](https://github.com/mchienn/DocGrading/issues/27); sau khi có Admin, tạo Teacher/Student tại `/admin/users`.

## Lệnh vận hành local

Chạy nền:

```bash
docker compose up --build -d
```

Xem log:

```bash
docker compose logs -f api worker frontend
```

Build lại service đã đổi:

```bash
docker compose up --build -d api worker frontend
```

Dừng stack, giữ dữ liệu:

```bash
docker compose down
```

**Cảnh báo:** Lệnh sau xóa vĩnh viễn toàn bộ dữ liệu PostgreSQL, Redis và LocalStack local:

```bash
docker compose down --volumes
```

## Chạy development ngoài container

Khởi động dependencies:

```bash
docker compose up -d postgres redis storage storage-init
```

API:

```bash
cd backend
uv sync --frozen
uv run alembic upgrade head
uv run uvicorn app.main:app --reload
```

Worker trong terminal khác:

```bash
cd backend
uv run celery -A app.workers.celery_app:celery_app worker --loglevel=INFO
```

Frontend trong terminal khác:

```bash
cd frontend
pnpm install --frozen-lockfile
pnpm dev
```

Vite proxy `/api` và `/health` tới `http://127.0.0.1:8000`.

## Kiểm chứng

Backend:

```bash
cd backend
uv sync --frozen
uv run ruff check .
uv run black --check .
uv run pytest
```

Frontend:

```bash
cd frontend
pnpm install --frozen-lockfile
pnpm typecheck
pnpm build
```

Compose:

```bash
docker compose --profile smoke --profile ops config --quiet
```

## Production

Compose host ports mặc định chỉ bind loopback, phù hợp development/UAT. Trước production:

- terminate TLS trực tiếp tại Caddy và expose một HTTPS origin; nếu phải đặt load balancer TLS phía trước Caddy, chỉ trust CIDR chính xác của proxy đó bằng `trusted_proxies` + `trusted_proxies_strict` để giữ client IP;
- đặt `APP_ENV` khác `development`;
- đặt `FRONTEND_ORIGIN` thành public HTTPS origin;
- dùng storage credentials thật và `STORAGE_PUBLIC_ENDPOINT_URL` HTTPS;
- giữ API port `8000` private; browser gọi `/api` same-origin qua Caddy;
- chạy và kiểm tra migration trước khi nhận traffic.

Không dùng LocalStack làm object storage production.

## Known gaps

- Student submission status, result history và version comparison UI: [#26](https://github.com/mchienn/DocGrading/issues/26).
- First-Admin bootstrap cho fresh deployment: [#27](https://github.com/mchienn/DocGrading/issues/27).

## Cấu trúc repository

- `frontend/`: React/Vite, Caddy production image.
- `backend/`: FastAPI, Celery, Alembic và tests.
- `docs/design/`: phạm vi, business rules và kiến trúc.
- `docs/superpowers/plans/`: implementation/UAT reports.
- `docker-compose.yml`: stack development/UAT và smoke/ops profiles.

Chi tiết: [`frontend/README.md`](frontend/README.md), [`backend/README.md`](backend/README.md), [`docs/design/PROJECT_SCOPE_BUSINESS_RULES_TECH_STACK.md`](docs/design/PROJECT_SCOPE_BUSINESS_RULES_TECH_STACK.md).
