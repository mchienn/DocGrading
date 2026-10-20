import re
from functools import lru_cache
from pathlib import Path
from urllib.parse import urlsplit

from pydantic import Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy import URL

ROOT_ENV_FILE = Path(__file__).resolve().parents[3] / ".env"

KNOWN_STORAGE_PLACEHOLDERS = frozenset(
    {
        "local-development-access-key",
        "local-development-secret-key",
        "test",
        "minioadmin",
        "change-me-for-local-development",
        "changeme",
    }
)
JOIN_RATE_LIMIT_HASH_SECRET_PLACEHOLDER = "change-me-for-local-development-only"
POSTGRES_PASSWORD_PLACEHOLDER = "change-me-for-local-development"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=ROOT_ENV_FILE,
        env_file_encoding="utf-8",
        extra="ignore",
        hide_input_in_errors=True,
    )

    app_env: str = "development"
    api_host: str = "0.0.0.0"
    api_port: int = 8000
    frontend_origin: str = "http://localhost:5173"
    join_rate_limit_max_requests: int = Field(default=10, ge=1)
    join_rate_limit_window_seconds: int = Field(default=60, gt=0)
    join_rate_limit_hash_secret: str = Field(
        default=JOIN_RATE_LIMIT_HASH_SECRET_PLACEHOLDER,
        min_length=32,
    )

    postgres_db: str = Field(min_length=1)
    postgres_user: str = Field(min_length=1)
    postgres_password: str = Field(min_length=1)
    postgres_host: str = "localhost"
    postgres_port: int = 5432

    redis_host: str = "localhost"
    redis_port: int = 6379
    session_lifetime_seconds: int = 86400
    login_max_failed_attempts: int = Field(default=5, ge=1)
    login_failure_window_seconds: int = Field(default=900, gt=0)
    login_lockout_seconds: int = Field(default=900, gt=0)
    login_ip_max_failed_attempts: int = Field(default=30, ge=1)

    storage_bucket: str = "docgrading"
    storage_endpoint_url: str = "http://localhost:9000"
    storage_public_endpoint_url: str = "http://localhost:9000"
    storage_region: str = "us-east-1"
    # Development-only placeholders; deployments must override these via env.
    storage_access_key_id: str = Field(
        default="local-development-access-key", min_length=1
    )
    storage_secret_access_key: str = Field(
        default="local-development-secret-key", min_length=1
    )
    storage_presign_expiry_seconds: int = Field(default=300, ge=1, le=300)
    storage_recovery_dir: str = ""
    pdf_max_size_bytes: int = Field(default=100_000_000, gt=0)
    pdf_max_decoded_bytes: int = Field(default=50_000_000, gt=0)
    pdf_max_page_count: int = Field(default=100, gt=0)
    pdf_ir_max_nodes: int = Field(default=100_000, gt=0)
    # Download verified sources (arXiv, OpenAlex open-access PDFs) into the cache.
    semantic_source_fetch_enabled: bool = False
    semantic_source_cache_prefix: str = ""
    semantic_model_call_budget: int = Field(default=32, ge=1, le=256)
    semantic_coverage_threshold: float = Field(default=1.0, gt=0, le=1)
    semantic_max_source_bytes: int = Field(default=50_000_000, gt=0, le=50_000_000)
    # OpenAI-compatible embeddings endpoint (Text Embeddings Inference, OpenAI,
    # Gemini...) and optional TEI reranker; empty keeps BM25 retrieval.
    semantic_encoder_url: str = ""
    semantic_encoder_model: str = ""
    semantic_encoder_api_key: SecretStr = Field(default=SecretStr(""), repr=False)
    semantic_encoder_query_prefix: str = ""
    semantic_encoder_document_prefix: str = ""
    semantic_reranker_url: str = ""
    llm_credential_keyring: SecretStr = Field(default=SecretStr(""), repr=False)
    llm_credential_active_key_id: str = ""

    analysis_job_lease_seconds: int = Field(default=300, gt=0)
    analysis_job_heartbeat_seconds: int = Field(default=30, gt=0)

    @model_validator(mode="after")
    def _validate_invariants(self) -> "Settings":
        if self.analysis_job_heartbeat_seconds >= self.analysis_job_lease_seconds:
            raise ValueError(
                "analysis_job_heartbeat_seconds must be strictly shorter than "
                "analysis_job_lease_seconds"
            )
        recovery_dir = self.storage_recovery_dir.strip()
        if self.app_env == "development" and not recovery_dir:
            recovery_dir = "storage"
        self.storage_recovery_dir = recovery_dir
        if self.app_env != "development" and recovery_dir:
            # A local copy re-uploads objects that were deleted from the bucket.
            raise ValueError(
                "Local storage recovery is only allowed in development environment"
            )
        if self.app_env != "development" and (
            self.storage_access_key_id.strip().lower() in KNOWN_STORAGE_PLACEHOLDERS
            or self.storage_secret_access_key.strip().lower()
            in KNOWN_STORAGE_PLACEHOLDERS
        ):
            raise ValueError(
                "Known placeholder storage credentials are not allowed outside "
                "development environment"
            )
        if (
            self.app_env != "development"
            and self.postgres_password.strip().lower() == POSTGRES_PASSWORD_PLACEHOLDER
        ):
            raise ValueError(
                "Default PostgreSQL password is not allowed outside "
                "development environment"
            )
        rate_limit_secret = self.join_rate_limit_hash_secret.strip()
        if sum(not character.isspace() for character in rate_limit_secret) < 32:
            raise ValueError(
                "Join rate-limit hash secret must contain at least "
                "32 non-whitespace characters"
            )
        self.join_rate_limit_hash_secret = rate_limit_secret
        if (
            self.app_env != "development"
            and rate_limit_secret.lower() == JOIN_RATE_LIMIT_HASH_SECRET_PLACEHOLDER
        ):
            raise ValueError(
                "Default join rate-limit hash secret is not allowed outside "
                "development environment"
            )
        if (
            self.app_env != "development"
            and urlsplit(self.storage_public_endpoint_url.strip()).scheme.lower()
            != "https"
        ):
            raise ValueError(
                "Public storage endpoint must use HTTPS outside development "
                "environment"
            )
        prefix = self.semantic_source_cache_prefix.strip()
        if prefix:
            if (
                prefix.startswith("/")
                or ".." in prefix
                or "//" in prefix
                or not re.fullmatch(r"[a-zA-Z0-9_\-\./]+", prefix)
            ):
                raise ValueError(
                    "semantic_source_cache_prefix must be a safe relative S3 prefix"
                )
            self.semantic_source_cache_prefix = prefix.strip("/")
        else:
            self.semantic_source_cache_prefix = ""
        for name in ("semantic_encoder_url", "semantic_reranker_url"):
            url = getattr(self, name).strip()
            parts = urlsplit(url)
            if url and (
                parts.scheme not in {"http", "https"}
                or not parts.hostname
                or parts.username
                or parts.password
                or parts.query
                or parts.fragment
            ):
                raise ValueError(f"{name} must be a plain http(s) URL")
            setattr(self, name, url.rstrip("/"))
        if self.semantic_encoder_url and not self.semantic_encoder_model.strip():
            raise ValueError("semantic_encoder_model is required with an encoder URL")
        if self.semantic_reranker_url and not self.semantic_encoder_url:
            raise ValueError("semantic_reranker_url requires semantic_encoder_url")
        if (
            self.semantic_encoder_api_key.get_secret_value()
            and urlsplit(self.semantic_encoder_url).scheme != "https"
        ):
            raise ValueError("an encoder API key requires an HTTPS encoder URL")
        return self

    @property
    def session_cookie_secure(self) -> bool:
        """Require HTTPS for session cookies outside local development."""
        return self.app_env != "development"

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
