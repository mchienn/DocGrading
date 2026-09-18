from __future__ import annotations

import asyncio
import importlib.util
import uuid
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException

from app.main import create_app
from app.services import review


def test_validation_report_authorizes_document_reader(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def run() -> None:
        version = SimpleNamespace(
            id=uuid.uuid4(),
            submission_id=uuid.uuid4(),
            validation_report={
                "schema_version": 1,
                "outcome": "ACCEPTED_WITH_WARNINGS",
                "diagnostics": [
                    {
                        "code": "PDF_LINK_TARGET_MISMATCH",
                        "category": "INTEGRITY",
                        "disposition": "REVIEW",
                        "scope": "REGION",
                        "page_number": 1,
                        "bbox": {"x0": 1, "top": 2, "x1": 3, "bottom": 4},
                        "metrics": {},
                        "message_key": "pdf_link_target_mismatch",
                        "action_key": "pdf.review_link_target",
                    }
                ],
            },
        )
        user = SimpleNamespace(id=uuid.uuid4())
        db = SimpleNamespace(get=AsyncMock(return_value=version))
        authorize = AsyncMock(return_value=(SimpleNamespace(), None, False))
        monkeypatch.setattr(review, "_submission_for_read", authorize)

        response = await review.get_document_validation_report(
            db,
            version_id=version.id,
            user=user,
        )

        authorize.assert_awaited_once_with(db, version.submission_id, user)
        assert response.document_version_id == version.id
        assert response.diagnostics[0].code == "PDF_LINK_TARGET_MISMATCH"
        assert response.diagnostics[0].bbox is not None

        version.validation_report = {"outcome": "ACCEPTED"}
        with pytest.raises(HTTPException) as error:
            await review.get_document_validation_report(
                db,
                version_id=version.id,
                user=user,
            )
        assert error.value.status_code == 500

    asyncio.run(run())


def test_validation_report_openapi_contract() -> None:
    operation = create_app().openapi()["paths"][
        "/api/v1/document-versions/{version_id}/validation-report"
    ]["get"]

    response = operation["responses"]["200"]["content"]["application/json"]["schema"]
    assert response["$ref"].endswith("/ValidationReportResponse")


def test_validation_report_migration_contract() -> None:
    migration_path = (
        Path(__file__).resolve().parents[1]
        / "alembic"
        / "versions"
        / "20260918_0016_pdf_validation_report.py"
    )
    spec = importlib.util.spec_from_file_location(
        "migration_0016_pdf_validation_report",
        migration_path,
    )
    assert spec is not None and spec.loader is not None
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)

    assert migration.revision == "20260918_0016"
    assert migration.down_revision == "20260916_0015"
    assert callable(migration.upgrade)
    assert callable(migration.downgrade)
