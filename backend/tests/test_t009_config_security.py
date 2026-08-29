import pytest
from pydantic import ValidationError

from app.core.config import Settings


def test_settings_defaults_lease_and_heartbeat() -> None:
    settings = Settings(
        postgres_db="docgrading",
        postgres_user="docgrading",
        postgres_password="pw",
    )
    assert settings.analysis_job_lease_seconds == 300
    assert settings.analysis_job_heartbeat_seconds == 30


def test_settings_enforces_heartbeat_strictly_shorter_than_lease() -> None:
    with pytest.raises(ValidationError, match="heartbeat"):
        Settings(
            postgres_db="docgrading",
            postgres_user="docgrading",
            postgres_password="pw",
            analysis_job_lease_seconds=30,
            analysis_job_heartbeat_seconds=30,
        )

    with pytest.raises(ValidationError, match="heartbeat"):
        Settings(
            postgres_db="docgrading",
            postgres_user="docgrading",
            postgres_password="pw",
            analysis_job_lease_seconds=30,
            analysis_job_heartbeat_seconds=60,
        )


def test_settings_requires_positive_lease_and_heartbeat() -> None:
    with pytest.raises(ValidationError):
        Settings(
            postgres_db="docgrading",
            postgres_user="docgrading",
            postgres_password="pw",
            analysis_job_lease_seconds=0,
        )

    with pytest.raises(ValidationError):
        Settings(
            postgres_db="docgrading",
            postgres_user="docgrading",
            postgres_password="pw",
            analysis_job_heartbeat_seconds=0,
        )


def test_settings_accepts_placeholder_credentials_in_development() -> None:
    settings = Settings(
        app_env="development",
        postgres_db="docgrading",
        postgres_user="docgrading",
        postgres_password="pw",
        storage_access_key_id="local-development-access-key",
        storage_secret_access_key="local-development-secret-key",
    )
    assert settings.storage_access_key_id == "local-development-access-key"

    settings_test = Settings(
        app_env="development",
        postgres_db="docgrading",
        postgres_user="docgrading",
        postgres_password="pw",
        storage_access_key_id="test",
        storage_secret_access_key="test",
    )
    assert settings_test.storage_access_key_id == "test"


@pytest.mark.parametrize(
    ("key_id", "secret_key"),
    [
        ("local-development-access-key", "local-development-secret-key"),
        ("test", "test"),
        ("minioadmin", "minioadmin"),
        ("change-me-for-local-development", "change-me-for-local-development"),
    ],
)
def test_settings_rejects_placeholder_credentials_outside_development(
    key_id: str, secret_key: str
) -> None:
    for env in ("production", "staging", "test_env"):
        with pytest.raises(ValidationError) as exc_info:
            Settings(
                app_env=env,
                postgres_db="docgrading",
                postgres_user="docgrading",
                postgres_password="pw",
                storage_access_key_id=key_id,
                storage_secret_access_key=secret_key,
            )
        error_str = str(exc_info.value)
        # Verify secrets are not leaked in error messages
        assert "placeholder" in error_str.lower() or "credential" in error_str.lower()
        assert key_id not in error_str
        assert secret_key not in error_str


def test_settings_accepts_valid_custom_credentials_outside_development() -> None:
    settings = Settings(
        app_env="production",
        postgres_db="docgrading",
        postgres_user="docgrading",
        postgres_password="pw",
        storage_access_key_id="AKIAIOSFODNN7EXAMPLE",
        storage_secret_access_key="wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY",
    )
    assert settings.storage_access_key_id == "AKIAIOSFODNN7EXAMPLE"


def test_api_startup_fails_in_production_with_default_placeholder_credentials(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from fastapi.testclient import TestClient

    from app.core.config import get_settings
    from app.main import create_app

    get_settings.cache_clear()
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("POSTGRES_DB", "docgrading")
    monkeypatch.setenv("POSTGRES_USER", "docgrading")
    monkeypatch.setenv("POSTGRES_PASSWORD", "secret")
    monkeypatch.delenv("STORAGE_ACCESS_KEY_ID", raising=False)
    monkeypatch.delenv("STORAGE_SECRET_ACCESS_KEY", raising=False)

    app = create_app()
    with pytest.raises(ValidationError), TestClient(app):
        pass
    get_settings.cache_clear()


def test_api_startup_succeeds_in_production_with_valid_custom_credentials(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from fastapi.testclient import TestClient

    from app.core.config import get_settings
    from app.main import create_app

    get_settings.cache_clear()
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("POSTGRES_DB", "docgrading")
    monkeypatch.setenv("POSTGRES_USER", "docgrading")
    monkeypatch.setenv("POSTGRES_PASSWORD", "secret")
    monkeypatch.setenv("STORAGE_ACCESS_KEY_ID", "AKIAIOSFODNN7EXAMPLE")
    monkeypatch.setenv(
        "STORAGE_SECRET_ACCESS_KEY", "wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY"
    )

    app = create_app()
    with TestClient(app) as client:
        res = client.get("/api/v1/health")
        assert res.status_code == 200
        assert res.json() == {"status": "ok"}
    get_settings.cache_clear()
