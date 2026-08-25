# Backend Foundation T-005 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Tạo backend FastAPI độc lập có PostgreSQL/Alembic, Celery/Redis, local PDF volume, Docker Compose và CI pull request chạy xanh mà chưa tạo schema domain.

**Architecture:** Backend là Python project layer-first trong `backend/`; FastAPI và Celery dùng chung settings/code nhưng chạy thành hai process. PostgreSQL là persistence duy nhất, Redis là broker/result backend, PDF development nằm trên named volume riêng; `docker-compose.yml` ở root nối bốn service mà không thay đổi `frontend/`.

**Tech Stack:** Python 3.13, uv 0.11.19, FastAPI, Pydantic Settings 2, SQLAlchemy 2 async + asyncpg, Alembic, Celery 5.6 + Redis 7, PostgreSQL 17, pytest, Ruff, Black, Docker Compose, GitHub Actions.

---

## File map

**Tạo mới**

- `.env.example`: catalog cấu hình development không chứa secret thật.
- `.github/workflows/backend-ci.yml`: lint, format check, pytest và Docker build trên pull request.
- `docker-compose.yml`: API, worker, PostgreSQL, Redis và các named volume.
- `backend/pyproject.toml`, `backend/uv.lock`: dependency và tool configuration đã khóa.
- `backend/app/main.py`: FastAPI application factory.
- `backend/app/api/routers/system.py`: liveness endpoint `/api/v1/health`.
- `backend/app/core/config.py`: settings và URL được dựng an toàn từ env.
- `backend/app/db/base.py`: SQLAlchemy declarative base.
- `backend/app/db/session.py`: async engine/session factory.
- `backend/app/workers/celery_app.py`: Celery application.
- `backend/app/workers/tasks.py`: task queue healthcheck.
- `backend/alembic.ini`, `backend/alembic/env.py`, `backend/alembic/script.py.mako`: Alembic runtime.
- `backend/alembic/versions/20260825_0001_initialize_backend.py`: migration rỗng.
- `backend/tests/test_health.py`: FastAPI smoke test.
- `backend/Dockerfile`, `backend/.dockerignore`: image backend không chạy root.
- `backend/README.md`: hướng dẫn local và Compose.
- Các `__init__.py` trong package mới: package boundary rõ ràng, không có domain code.

**Sửa**

- `.gitignore`: bỏ qua Python cache, virtualenv, coverage và local PDF storage.
- `README.md`: thêm backend vào cấu trúc repository và liên kết hướng dẫn.

- [ ] Không sửa file nào dưới `frontend/`.
- [ ] Không tạo model/domain table hoặc migration DDL.

### Task 1: Scaffold Python project and FastAPI smoke endpoint

**Files:**
- Create: `backend/pyproject.toml`
- Create: `backend/app/__init__.py`
- Create: `backend/app/api/__init__.py`
- Create: `backend/app/api/routers/__init__.py`
- Create: `backend/app/api/routers/system.py`
- Create: `backend/app/core/__init__.py`
- Create: `backend/app/db/__init__.py`
- Create: `backend/app/models/__init__.py`
- Create: `backend/app/services/__init__.py`
- Create: `backend/app/workers/__init__.py`
- Create: `backend/app/main.py`
- Create: `backend/tests/test_health.py`
- Create: `backend/uv.lock`

- [ ] **Step 1: Create package directories, empty `__init__.py` files, and project metadata**

Use this `backend/pyproject.toml`:

```toml
[project]
name = "docgrading-backend"
version = "0.1.0"
description = "Backend API and workers for DocGrading"
requires-python = ">=3.13,<3.14"
dependencies = [
  "alembic>=1.16,<2",
  "asyncpg>=0.30,<1",
  "celery[redis]>=5.6,<6",
  "fastapi>=0.116,<1",
  "pydantic-settings>=2.10,<3",
  "sqlalchemy[asyncio]>=2.0.41,<3",
  "uvicorn[standard]>=0.35,<1",
]

[dependency-groups]
dev = [
  "black>=25.1,<27",
  "httpx2>=2.12,<3",
  "pytest>=8.4,<9",
  "ruff>=0.12,<1",
]

[build-system]
requires = ["hatchling>=1.27,<2"]
build-backend = "hatchling.build"

[tool.hatch.build.targets.wheel]
packages = ["app"]

[tool.ruff]
target-version = "py313"
line-length = 88

[tool.ruff.lint]
select = ["E", "F", "I", "UP", "B", "SIM"]

[tool.black]
target-version = ["py313"]
line-length = 88

[tool.pytest.ini_options]
testpaths = ["tests"]
addopts = "-ra"
```

Keep every package `__init__.py` empty. Run `cd backend && uv lock && uv sync` to create `backend/uv.lock` and the virtual environment.

Expected: dependency resolution succeeds for Python 3.13.

- [ ] **Step 2: Write the failing health smoke test**

Create `backend/tests/test_health.py`:

```python
from fastapi.testclient import TestClient

from app.main import create_app


def test_health_endpoint_reports_api_is_alive() -> None:
    client = TestClient(create_app())

    response = client.get("/api/v1/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
```

- [ ] **Step 3: Run the smoke test and verify the missing implementation fails**

Run: `cd backend && uv run pytest tests/test_health.py -v`

Expected: FAIL during collection because `app.main` does not exist yet.

- [ ] **Step 4: Implement the minimal router and application factory**

Create `backend/app/api/routers/system.py`:

```python
from typing import Literal

from fastapi import APIRouter
from pydantic import BaseModel

router = APIRouter(tags=["system"])


class HealthResponse(BaseModel):
    status: Literal["ok"] = "ok"


@router.get("/health", response_model=HealthResponse)
async def healthcheck() -> HealthResponse:
    return HealthResponse()
```

Create `backend/app/main.py`:

```python
from fastapi import FastAPI

from app.api.routers.system import router as system_router


def create_app() -> FastAPI:
    application = FastAPI(
        title="DocGrading API",
        version="0.1.0",
        openapi_url="/api/v1/openapi.json",
    )
    application.include_router(system_router, prefix="/api/v1")
    return application


app = create_app()
```

- [ ] **Step 5: Run the smoke test and quality tools**

Run: `cd backend && uv run pytest tests/test_health.py -v`

Expected: 1 passed.

Run: `cd backend && uv run ruff check . && uv run black --check .`

Expected: both commands exit 0.

- [ ] **Step 6: Commit the scaffold**

```bash
git add backend/pyproject.toml backend/uv.lock backend/app backend/tests
git commit -m "feat(backend): scaffold FastAPI application"
```

### Task 2: Add environment settings and SQLAlchemy foundation

**Files:**
- Create: `.env.example`
- Create: `backend/app/core/config.py`
- Create: `backend/app/db/base.py`
- Create: `backend/app/db/session.py`
- Modify: `.gitignore`

- [ ] **Step 1: Define non-secret example configuration**

Create root `.env.example`:

```dotenv
APP_ENV=development
API_HOST=0.0.0.0
API_PORT=8000
POSTGRES_DB=docgrading
POSTGRES_USER=docgrading
POSTGRES_PASSWORD=change-me-for-local-development
POSTGRES_HOST=localhost
POSTGRES_PORT=5432
REDIS_HOST=localhost
REDIS_PORT=6379
STORAGE_PATH=storage
```

Do not create or commit a populated `.env` in this step.

- [ ] **Step 2: Implement typed settings and safe connection URL construction**

Create `backend/app/core/config.py`:

```python
from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy import URL

ROOT_ENV_FILE = Path(__file__).resolve().parents[3] / ".env"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=ROOT_ENV_FILE,
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_env: str = "development"
    api_host: str = "0.0.0.0"
    api_port: int = 8000

    postgres_db: str = Field(min_length=1)
    postgres_user: str = Field(min_length=1)
    postgres_password: str = Field(min_length=1)
    postgres_host: str = "localhost"
    postgres_port: int = 5432

    redis_host: str = "localhost"
    redis_port: int = 6379
    storage_path: Path = Path("storage")

    @property
    def database_url(self) -> str:
        return URL.create(
            drivername="postgresql+asyncpg",
            username=self.postgres_user,
            password=self.postgres_password,
            host=self.postgres_host,
            port=self.postgres_port,
            database=self.postgres_db,
        ).render_as_string(hide_password=False)

    @property
    def celery_broker_url(self) -> str:
        return f"redis://{self.redis_host}:{self.redis_port}/0"

    @property
    def celery_result_backend(self) -> str:
        return f"redis://{self.redis_host}:{self.redis_port}/1"


@lru_cache
def get_settings() -> Settings:
    return Settings()
```

- [ ] **Step 3: Implement SQLAlchemy declarative base and async session factory**

Create `backend/app/db/base.py`:

```python
from sqlalchemy.ext.asyncio import AsyncAttrs
from sqlalchemy.orm import DeclarativeBase


class Base(AsyncAttrs, DeclarativeBase):
    pass
```

Create `backend/app/db/session.py`:

```python
from collections.abc import AsyncIterator

from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.core.config import get_settings

settings = get_settings()
engine = create_async_engine(settings.database_url, pool_pre_ping=True)
async_session_factory = async_sessionmaker(engine, expire_on_commit=False)


async def get_db_session() -> AsyncIterator[AsyncSession]:
    async with async_session_factory() as session:
        yield session
```

`create_async_engine` constructs an engine but does not open a database connection at import.

- [ ] **Step 4: Extend Git ignore rules**

Append to root `.gitignore`:

```gitignore

# Python backend
__pycache__/
*.py[cod]
.pytest_cache/
.ruff_cache/
.coverage
htmlcov/
.venv/
backend/storage/
```

The existing rules already ignore `.env` while allowing `.env.example`.

- [ ] **Step 5: Verify settings without exposing the credential**

Copy `.env.example` to `.env` locally, then run:

`cd backend && uv run python -c "from app.core.config import get_settings; s=get_settings(); assert s.database_url.startswith('postgresql+asyncpg://'); assert s.celery_broker_url.endswith('/0')"`

Expected: exit 0 and no credential printed.

Run: `cd backend && uv run ruff check app/core app/db && uv run black --check app/core app/db`

Expected: both commands exit 0.

- [ ] **Step 6: Commit configuration and database foundation**

```bash
git add .env.example .gitignore backend/app/core backend/app/db
git commit -m "feat(backend): configure database foundation"
```

### Task 3: Configure Alembic with an empty initial migration

**Files:**
- Create: `backend/alembic.ini`
- Create: `backend/alembic/env.py`
- Create: `backend/alembic/script.py.mako`
- Create: `backend/alembic/versions/20260825_0001_initialize_backend.py`

- [ ] **Step 1: Initialize Alembic files**

Run: `cd backend && uv run alembic init alembic`

Expected: Alembic creates `alembic.ini`, `alembic/env.py`, `alembic/script.py.mako`, and `alembic/versions/`.

- [ ] **Step 2: Replace Alembic runtime with async configuration**

Keep generated logging sections in `backend/alembic.ini`, set `script_location = %(here)s/alembic`, `prepend_sys_path = .`, and remove any real `sqlalchemy.url` value because `env.py` owns the URL.

Replace `backend/alembic/env.py` with:

```python
from asyncio import run
from logging.config import fileConfig

from alembic import context
from sqlalchemy import pool
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import create_async_engine

from app.core.config import get_settings
from app.db.base import Base

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    context.configure(
        url=get_settings().database_url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
    )

    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection: Connection) -> None:
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        compare_type=True,
    )

    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    connectable = create_async_engine(
        get_settings().database_url,
        poolclass=pool.NullPool,
    )

    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)

    await connectable.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run(run_async_migrations())
```


Replace `backend/alembic/script.py.mako` so generated revisions use Python 3.13 unions, Ruff-compatible import groups, and omit unused Alembic/SQLAlchemy imports when a revision is empty:

```mako
"""${message}

Revision ID: ${up_revision}
Revises: ${down_revision | comma,n}
Create Date: ${create_date}

"""
from collections.abc import Sequence
% if upgrades or downgrades:

import sqlalchemy as sa

from alembic import op
% endif
${imports if imports else ""}
# revision identifiers, used by Alembic.
revision: str = ${repr(up_revision)}
down_revision: str | Sequence[str] | None = ${repr(down_revision)}
branch_labels: str | Sequence[str] | None = ${repr(branch_labels)}
depends_on: str | Sequence[str] | None = ${repr(depends_on)}


def upgrade() -> None:
    """Upgrade schema."""
    ${upgrades if upgrades else "pass"}


def downgrade() -> None:
    """Downgrade schema."""
    ${downgrades if downgrades else "pass"}
```

Enable Black as Alembic's post-write hook in `backend/alembic.ini` so generated string literals and layout already satisfy CI:

```ini
[post_write_hooks]
hooks = black
black.type = console_scripts
black.entrypoint = black
black.options = -l 88 REVISION_SCRIPT_FILENAME
```

- [ ] **Step 3: Create the empty base revision**

Run:

`cd backend && uv run alembic revision --rev-id 20260825_0001 -m "initialize backend"`

Replace the generated revision body with:

```python
"""Initialize backend without domain schema."""

from collections.abc import Sequence

revision: str = "20260825_0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
```

No `op.create_table`, enum, index, extension, or domain identifier is allowed.

- [ ] **Step 4: Verify the migration offline and formatting**

Run: `cd backend && uv run alembic upgrade head --sql`

Expected: command exits 0 and targets revision `20260825_0001`; no domain table DDL appears.

Run: `cd backend && uv run ruff check alembic app/db && uv run black --check alembic app/db`

Expected: both commands exit 0.

- [ ] **Step 5: Commit Alembic foundation**

```bash
git add backend/alembic.ini backend/alembic
git commit -m "feat(backend): initialize Alembic migrations"
```

### Task 4: Add Celery application and queue healthcheck task

**Files:**
- Create: `backend/app/workers/celery_app.py`
- Create: `backend/app/workers/tasks.py`

- [ ] **Step 1: Configure Celery from shared settings**

Create `backend/app/workers/celery_app.py`:

```python
from celery import Celery

from app.core.config import get_settings

settings = get_settings()
celery_app = Celery(
    "docgrading",
    broker=settings.celery_broker_url,
    backend=settings.celery_result_backend,
    include=["app.workers.tasks"],
)
celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    result_accept_content=["json"],
    enable_utc=True,
    timezone="UTC",
)
```

- [ ] **Step 2: Add the named healthcheck task**

Create `backend/app/workers/tasks.py`:

```python
from app.workers.celery_app import celery_app


@celery_app.task(name="app.workers.tasks.healthcheck")
def healthcheck() -> dict[str, str]:
    return {"status": "ok"}
```

- [ ] **Step 3: Verify task registration without a broker**

Run:

`cd backend && uv run python -c "from app.workers.tasks import healthcheck; assert healthcheck.run() == {'status': 'ok'}; assert healthcheck.name == 'app.workers.tasks.healthcheck'"`

Expected: exit 0.

Run: `cd backend && uv run ruff check app/workers && uv run black --check app/workers`

Expected: both commands exit 0.

- [ ] **Step 4: Commit queue foundation**

```bash
git add backend/app/workers
git commit -m "feat(backend): configure Celery healthcheck task"
```

### Task 5: Containerize and compose the backend stack

**Files:**
- Create: `backend/.dockerignore`
- Create: `backend/Dockerfile`
- Create: `docker-compose.yml`

- [ ] **Step 1: Limit Docker build context**

Create `backend/.dockerignore`:

```dockerignore
.env
.venv
__pycache__
*.py[cod]
.pytest_cache
.ruff_cache
.coverage
htmlcov
storage
README.md
tests
```

- [ ] **Step 2: Create a cached, non-root backend image**

Create `backend/Dockerfile`:

```dockerfile
FROM ghcr.io/astral-sh/uv:0.11.19 AS uv

FROM python:3.13-slim-bookworm

ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy

WORKDIR /app

COPY --from=uv /uv /uvx /bin/
COPY pyproject.toml uv.lock ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --no-install-project

COPY alembic.ini ./
COPY alembic ./alembic
COPY app ./app
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev

RUN groupadd --system appgroup \
    && useradd --system --gid appgroup --home-dir /app appuser \
    && mkdir -p /var/lib/docgrading/storage \
    && chown -R appuser:appgroup /app /var/lib/docgrading

USER appuser
EXPOSE 8000

HEALTHCHECK --interval=10s --timeout=3s --start-period=15s --retries=5 \
    CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/api/v1/health', timeout=2)"]

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
```

- [ ] **Step 3: Compose API, worker, PostgreSQL, Redis, and storage**

Create root `docker-compose.yml`:

```yaml
name: docgrading

services:
  postgres:
    image: postgres:17-bookworm
    env_file: .env
    ports:
      - "127.0.0.1:${POSTGRES_PORT:-5432}:5432"
    volumes:
      - postgres_data:/var/lib/postgresql/data
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U $$POSTGRES_USER -d $$POSTGRES_DB"]
      interval: 5s
      timeout: 5s
      retries: 10
    networks: [backend]

  redis:
    image: redis:7-alpine
    ports:
      - "127.0.0.1:${REDIS_PORT:-6379}:6379"
    volumes:
      - redis_data:/data
    healthcheck:
      test: ["CMD", "redis-cli", "ping"]
      interval: 5s
      timeout: 3s
      retries: 10
    networks: [backend]

  api:
    build:
      context: backend
    env_file: .env
    environment:
      POSTGRES_HOST: postgres
      POSTGRES_PORT: 5432
      REDIS_HOST: redis
      REDIS_PORT: 6379
      STORAGE_PATH: /var/lib/docgrading/storage
    command: >-
      sh -c "alembic upgrade head &&
      exec uvicorn app.main:app --host 0.0.0.0 --port 8000"
    ports:
      - "${API_PORT:-8000}:8000"
    volumes:
      - pdf_storage:/var/lib/docgrading/storage
    depends_on:
      postgres:
        condition: service_healthy
      redis:
        condition: service_healthy
    networks: [backend]

  worker:
    build:
      context: backend
    env_file: .env
    environment:
      POSTGRES_HOST: postgres
      POSTGRES_PORT: 5432
      REDIS_HOST: redis
      REDIS_PORT: 6379
      STORAGE_PATH: /var/lib/docgrading/storage
    command: celery -A app.workers.celery_app:celery_app worker --loglevel=INFO
    volumes:
      - pdf_storage:/var/lib/docgrading/storage
    depends_on:
      postgres:
        condition: service_healthy
      redis:
        condition: service_healthy
      api:
        condition: service_healthy
    healthcheck:
      test:
        [
          "CMD-SHELL",
          "celery -A app.workers.celery_app:celery_app inspect ping --destination celery@$$HOSTNAME --timeout 5",
        ]
      interval: 10s
      timeout: 8s
      start_period: 15s
      retries: 5
    networks: [backend]

volumes:
  postgres_data:
  redis_data:
  pdf_storage:

networks:
  backend:
    driver: bridge
```

No credential is written under `environment`; only service DNS names, internal ports, and container storage path are inline.

- [ ] **Step 4: Validate Compose and build the image**

Copy `.env.example` to `.env` locally.

Run: `docker compose config --quiet`

Expected: exit 0.

Run: `docker build --tag docgrading-backend:test backend`

Expected: image builds successfully and the final image config uses user `appuser`.

- [ ] **Step 5: Commit container configuration**

```bash
git add backend/.dockerignore backend/Dockerfile docker-compose.yml
git commit -m "feat(backend): compose API and worker stack"
```

### Task 6: Add pull-request CI

**Files:**
- Create: `.github/workflows/backend-ci.yml`

- [ ] **Step 1: Create the backend pull-request workflow**

Create `.github/workflows/backend-ci.yml`:

```yaml
name: Backend CI

on:
  pull_request:

permissions:
  contents: read

jobs:
  quality:
    name: Lint and test
    runs-on: ubuntu-latest
    timeout-minutes: 10
    defaults:
      run:
        working-directory: backend
    steps:
      - name: Check out repository
        uses: actions/checkout@v4
      - name: Install Python
        uses: actions/setup-python@v5
        with:
          python-version: "3.13"
      - name: Install uv
        uses: astral-sh/setup-uv@v6
        with:
          version: "0.11.19"
          enable-cache: true
      - name: Install dependencies
        run: uv sync --frozen
      - name: Ruff
        run: uv run ruff check .
      - name: Black
        run: uv run black --check .
      - name: Pytest
        run: uv run pytest

  build:
    name: Build backend image
    needs: quality
    runs-on: ubuntu-latest
    timeout-minutes: 15
    steps:
      - name: Check out repository
        uses: actions/checkout@v4
      - name: Build image
        run: docker build --tag docgrading-backend:ci backend
```

The workflow has no runtime env or secrets because test import and image build do not initialize database/Celery settings.

- [ ] **Step 2: Validate workflow syntax and reproduce its commands locally**

Run: `cd backend && uv sync --frozen && uv run ruff check . && uv run black --check . && uv run pytest`

Expected: every command exits 0 and pytest reports 1 passed.

Run: `docker build --tag docgrading-backend:ci backend`

Expected: image build exits 0.

- [ ] **Step 3: Commit CI**

```bash
git add .github/workflows/backend-ci.yml
git commit -m "ci(backend): validate pull requests"
```

### Task 7: Document local operation and repository structure

**Files:**
- Create: `backend/README.md`
- Modify: `README.md`

- [ ] **Step 1: Write backend runbook**

Create `backend/README.md` with these exact sections and commands:

```markdown
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
```

- [ ] **Step 2: Link backend documentation from root README**

Add one repository-structure bullet after `frontend/`:

```markdown
- `backend/`: FastAPI API, Celery worker và cấu hình persistence/queue.
```

Replace the final frontend-only sentence with:

```markdown
Xem hướng dẫn chạy tại `frontend/README.md` và `backend/README.md`.
```

- [ ] **Step 3: Verify documentation commands match real paths**

Run: `docker compose config --quiet`

Expected: exit 0 using root `.env`.

Run: `cd backend && uv run alembic heads`

Expected: output contains `20260825_0001 (head)`.

- [ ] **Step 4: Commit documentation**

```bash
git add backend/README.md README.md
git commit -m "docs(backend): add local runbook"
```

### Task 8: Integrated smoke verification

**Files:**
- Verify only; do not add domain schema or frontend changes.

- [ ] **Step 1: Run the complete local quality gate**

Run:

`cd backend && uv sync --frozen && uv run ruff check . && uv run black --check . && uv run pytest`

Expected: Ruff and Black exit 0; pytest reports 1 passed.

- [ ] **Step 2: Validate configuration and build**

Run: `docker compose config --quiet`

Expected: exit 0.

Run: `docker build --tag docgrading-backend:verify backend`

Expected: exit 0.

- [ ] **Step 3: Start and exercise the real stack**

Run: `docker compose up --build -d`

Wait until `docker compose ps` reports Postgres, Redis, API, and worker healthy/running.

Run: `curl --fail http://localhost:8000/api/v1/health`

Expected: `{"status":"ok"}`.

Run:

`docker compose exec api python -c "from app.workers.tasks import healthcheck; result = healthcheck.delay(); assert result.get(timeout=10) == {'status': 'ok'}; print(result.id)"`

Expected: exit 0 and a Celery task ID.

Run: `docker compose exec api alembic current`

Expected: output contains `20260825_0001 (head)`.

- [ ] **Step 4: Stop containers without deleting persistent volumes**

Run: `docker compose down`

Expected: containers and network stop; named volumes remain.

- [ ] **Step 5: Inspect scope and documentation impact**

Confirm:

- no file under `frontend/` changed;
- migration contains no domain table DDL;
- `.env` is untracked/ignored;
- root architecture document still matches FastAPI + Celery/Redis + PostgreSQL + local development storage;
- README links resolve.

- [ ] **Step 6: Commit any verification-only corrections as one atomic change**

If verification required source corrections, stage only those files and use a scoped conventional commit. If no correction was needed, do not create an empty commit.
