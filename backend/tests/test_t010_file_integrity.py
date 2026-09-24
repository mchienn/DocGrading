from __future__ import annotations

import asyncio
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

from app.models.review import EvidenceAnchor, Finding
from app.services.file_integrity import evaluate_file_integrity


def _result(
    *, scalars: object | None = None, tuples: object | None = None
) -> MagicMock:
    result = MagicMock()
    if scalars is not None:
        result.scalars.return_value = scalars
    if tuples is not None:
        result.tuples.return_value = tuples
    return result


def test_file_integrity_creates_region_finding_once() -> None:
    async def run() -> None:
        criterion_id = uuid.uuid4()
        job = SimpleNamespace(id=uuid.uuid4(), rubric_version_id=uuid.uuid4())
        document_ir = SimpleNamespace(
            id=uuid.uuid4(),
            content={
                "links": [
                    {
                        "id": "link-1",
                        "page_number": 2,
                        "bbox": {"x0": 10, "top": 20, "x1": 30, "bottom": 40},
                        "display_text": "https://trusted.example",
                        "target": "https://other.example",
                        "status": "MISMATCH",
                    }
                ]
            },
        )
        criterion = SimpleNamespace(
            id=criterion_id,
            evaluation_method="FILE_INTEGRITY",
            evaluator_config={},
        )
        db = SimpleNamespace(
            execute=AsyncMock(
                side_effect=[
                    _result(scalars=[criterion]),
                    _result(scalars=[]),
                ]
            ),
            add=MagicMock(),
            flush=AsyncMock(),
        )

        assert await evaluate_file_integrity(db, job, document_ir) == 1

        finding = db.add.call_args_list[0].args[0]
        anchor = db.add.call_args_list[1].args[0]
        assert isinstance(finding, Finding)
        assert finding.severity == "error"
        assert "trusted.example" in finding.description
        assert "other.example" in finding.description
        assert isinstance(anchor, EvidenceAnchor)
        assert anchor.finding_id == finding.id
        assert anchor.document_ir_id == document_ir.id
        assert anchor.element_id == "link-1"
        assert anchor.page_number == 2

        replay_db = SimpleNamespace(
            execute=AsyncMock(
                side_effect=[
                    _result(scalars=[criterion]),
                    _result(scalars=[finding.id]),
                    MagicMock(),
                    MagicMock(),
                ]
            ),
            add=MagicMock(),
            flush=AsyncMock(),
        )
        document_ir.content["links"] = []
        assert await evaluate_file_integrity(replay_db, job, document_ir) == 0
        replay_db.add.assert_not_called()
        assert replay_db.execute.await_count == 4

    asyncio.run(run())
