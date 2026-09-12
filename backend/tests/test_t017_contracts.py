from __future__ import annotations

import ast
import uuid
from pathlib import Path

import pytest
from pydantic import ValidationError

import app.models  # noqa: F401
from app.api.schemas_notification import (
    NotificationBulkReadRequest,
    NotificationResponse,
)
from app.db.base import Base
from app.main import app
from app.models.enums import NotificationType

MIGRATION = (
    Path(__file__).parents[1]
    / "alembic"
    / "versions"
    / "20260912_0012_notifications.py"
)


def _payload(notification_type: NotificationType) -> dict[str, uuid.UUID]:
    if notification_type is NotificationType.ANALYSIS_JOB_ERROR:
        return {"analysis_job_id": uuid.uuid4()}
    if notification_type is NotificationType.RESULT_PUBLISHED:
        return {
            "published_result_version_id": uuid.uuid4(),
            "submission_id": uuid.uuid4(),
        }
    return {"review_request_id": uuid.uuid4()}


@pytest.mark.parametrize("notification_type", NotificationType)
def test_notification_response_allows_only_reference_ids(
    notification_type: NotificationType,
) -> None:
    value = NotificationResponse(
        id=uuid.uuid4(),
        type=notification_type,
        payload=_payload(notification_type),
        read_at=None,
        created_at="2026-09-12T00:00:00Z",
    )
    assert set(value.model_dump(mode="json")["payload"]) == set(value.payload)

    invalid = dict(_payload(notification_type))
    invalid["source_error"] = uuid.uuid4()
    with pytest.raises(ValidationError):
        NotificationResponse(
            id=uuid.uuid4(),
            type=notification_type,
            payload=invalid,
            read_at=None,
            created_at="2026-09-12T00:00:00Z",
        )


def test_notification_model_and_routes_are_allowlisted() -> None:
    table = Base.metadata.tables["notifications"]
    assert set(table.columns.keys()) == {
        "id",
        "recipient_id",
        "type",
        "payload",
        "read_at",
        "created_at",
    }
    assert set(NotificationResponse.model_fields) == {
        "id",
        "type",
        "payload",
        "read_at",
        "created_at",
    }
    schema = app.openapi()
    assert {
        "get",
    } <= set(schema["paths"]["/api/v1/notifications"])
    assert {
        "patch",
    } <= set(schema["paths"]["/api/v1/notifications/read"])
    assert {
        "patch",
    } <= set(schema["paths"]["/api/v1/notifications/{notification_id}/read"])


def test_bulk_read_ids_are_unique_and_bounded() -> None:
    value = uuid.uuid4()
    with pytest.raises(ValidationError):
        NotificationBulkReadRequest(notification_ids=[value, value])
    with pytest.raises(ValidationError):
        NotificationBulkReadRequest(notification_ids=[])
    with pytest.raises(ValidationError):
        NotificationBulkReadRequest(notification_ids=[uuid.uuid4() for _ in range(101)])


def test_notification_migration_security_contract() -> None:
    source = MIGRATION.read_text(encoding="utf-8")
    tree = ast.parse(source)
    functions = {
        node.name: node for node in tree.body if isinstance(node, ast.FunctionDef)
    }
    for function_name in ("upgrade", "downgrade"):
        function = functions[function_name]
        assert "SET search_path TO public" in ast.unparse(function.body[0])
    assert "audit_events" not in source
    assert "published_result_versions" not in source
    assert "LOCK TABLE public.notifications" in source
    assert "Refusing downgrade" in source
    for function_name in ("upgrade", "downgrade"):
        for call in ast.walk(functions[function_name]):
            if not isinstance(call, ast.Call):
                continue
            if getattr(call.func, "attr", None) == "create_table":
                assert any(
                    keyword.arg == "schema"
                    and getattr(keyword.value, "value", None) == "public"
                    for keyword in call.keywords
                )
            if getattr(call.func, "attr", None) == "drop_table":
                assert any(
                    keyword.arg == "schema"
                    and getattr(keyword.value, "value", None) == "public"
                    for keyword in call.keywords
                )
