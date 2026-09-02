from functools import lru_cache
from pathlib import Path

from pydantic import Field, model_validator
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

    postgres_db: str = Field(min_length=1)
    postgres_user: str = Field(min_length=1)
    postgres_password: str = Field(min_length=1)
    postgres_host: str = "localhost"
    postgres_port: int = 5432

    redis_host: str = "localhost"
    redis_port: int = 6379
    session_lifetime_seconds: int = 86400

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
    pdf_max_size_bytes: int = Field(default=50_000_000, gt=0)
    pdf_max_page_count: int = Field(default=100, gt=0)

    analysis_job_lease_seconds: int = Field(default=300, gt=0)
    analysis_job_heartbeat_seconds: int = Field(default=30, gt=0)

    @model_validator(mode="after")
    def _validate_invariants(self) -> "Settings":
        if self.analysis_job_heartbeat_seconds >= self.analysis_job_lease_seconds:
            raise ValueError(
                "analysis_job_heartbeat_seconds must be strictly shorter than "
                "analysis_job_lease_seconds"
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
