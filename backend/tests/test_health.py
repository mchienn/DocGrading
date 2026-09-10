import uuid
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from app import main as main_module
from app.main import create_app
from app.services.auth import csrf_token_for_session


def test_health_endpoint_reports_api_is_alive() -> None:
    client = TestClient(create_app())

    response = client.get("/api/v1/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_mutations_require_matching_csrf_cookie_and_header(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        main_module,
        "get_settings",
        lambda: SimpleNamespace(session_cookie_secure=False),
    )
    application = create_app()

    @application.post("/csrf-check")
    async def csrf_check() -> dict[str, bool]:
        return {"ok": True}

    client = TestClient(application)
    missing = client.post("/csrf-check")

    assert missing.status_code == 403
    assert missing.json() == {"detail": "CSRF validation failed"}

    session_id = uuid.uuid4()
    csrf_token = csrf_token_for_session(session_id)
    client.cookies.set("session_id", str(session_id))
    client.cookies.set("csrf_token", "forged-token")
    forged = client.post(
        "/csrf-check",
        headers={"X-CSRF-Token": "forged-token"},
    )
    assert forged.status_code == 403

    client.cookies.set("csrf_token", csrf_token)
    matched = client.post(
        "/csrf-check",
        headers={"X-CSRF-Token": csrf_token},
    )

    assert matched.status_code == 200
    assert matched.json() == {"ok": True}
