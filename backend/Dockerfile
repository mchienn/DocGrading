FROM ghcr.io/astral-sh/uv:0.11.19 AS uv

FROM python:3.13-slim-bookworm

ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy

WORKDIR /app
ARG INSTALL_LOGICAL=false

# hnswlib builds its CPU extension in the logical worker image.
RUN if [ "$INSTALL_LOGICAL" = "true" ]; then \
    apt-get update && apt-get install -y --no-install-recommends g++ \
    && rm -rf /var/lib/apt/lists/*; fi

COPY --from=uv /uv /uvx /bin/
COPY pyproject.toml uv.lock ./
RUN --mount=type=cache,target=/root/.cache/uv \
    if [ "$INSTALL_LOGICAL" = "true" ]; then uv sync --frozen --no-dev --no-install-project --extra logical; else uv sync --frozen --no-dev --no-install-project; fi

COPY alembic.ini ./
COPY alembic ./alembic
COPY app ./app
RUN --mount=type=cache,target=/root/.cache/uv \
    if [ "$INSTALL_LOGICAL" = "true" ]; then uv sync --frozen --no-dev --extra logical; else uv sync --frozen --no-dev; fi

RUN groupadd --system appgroup \
    && useradd --system --gid appgroup --home-dir /app appuser \
    && mkdir -p /var/lib/docgrading/storage /var/lib/docgrading/huggingface \
    && chown -R appuser:appgroup /var/lib/docgrading

ENV HF_HOME=/var/lib/docgrading/huggingface

USER appuser
EXPOSE 8000

HEALTHCHECK --interval=10s --timeout=3s --start-period=15s --retries=5 \
    CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/api/v1/health', timeout=2)"]

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
