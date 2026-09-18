from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.analysis import AnalysisJob, DocumentIR
from app.models.review import EvidenceAnchor, Finding
from app.models.rubric import CriterionVersion


def _is_file_integrity_criterion(criterion: CriterionVersion) -> bool:
    evaluator_type = str(criterion.evaluator_config.get("type", ""))
    return (
        criterion.evaluation_method.upper() == "FILE_INTEGRITY"
        or evaluator_type.upper() == "FILE_INTEGRITY"
    )


def _finding_text(link: Mapping[str, Any]) -> tuple[str, str]:
    label = str(link.get("display_text", ""))[:160] or "unreadable label"
    target = str(link.get("target", ""))[:160] or "unreadable target"
    if link.get("status") == "MISMATCH":
        return (
            f'Visible link label "{label}" points to "{target}".',
            "Replace the link target or change the visible label "
            "so both identify the same destination.",
        )
    return (
        f'Link target "{target}" could not be verified against label "{label}".',
        "Open the PDF link and verify its destination before grading.",
    )


async def evaluate_file_integrity(
    db: AsyncSession,
    job: AnalysisJob,
    document_ir: DocumentIR,
) -> int:
    """Create rubric findings for bounded link-integrity evidence."""
    links = [
        link
        for link in document_ir.content.get("links", ())
        if isinstance(link, Mapping)
        and link.get("status") in {"MISMATCH", "NEEDS_REVIEW"}
        and isinstance(link.get("id"), str)
        and isinstance(link.get("page_number"), int)
        and isinstance(link.get("bbox"), Mapping)
    ]
    if not links:
        return 0

    criteria = (
        await db.execute(
            sa.select(CriterionVersion).where(
                CriterionVersion.rubric_version_id == job.rubric_version_id,
                CriterionVersion.is_enabled.is_(True),
            )
        )
    ).scalars()
    integrity_criteria = [
        criterion for criterion in criteria if _is_file_integrity_criterion(criterion)
    ]
    if not integrity_criteria:
        return 0

    criterion_ids = [criterion.id for criterion in integrity_criteria]
    existing = set(
        (
            await db.execute(
                sa.select(Finding.criterion_version_id, EvidenceAnchor.element_id)
                .join(EvidenceAnchor, EvidenceAnchor.finding_id == Finding.id)
                .where(
                    Finding.analysis_job_id == job.id,
                    Finding.criterion_version_id.in_(criterion_ids),
                )
            )
        ).tuples()
    )

    created = 0
    pending: list[tuple[Finding, Mapping[str, Any]]] = []
    for criterion in integrity_criteria:
        for link in links:
            element_id = link["id"]
            if (criterion.id, element_id) in existing:
                continue
            description, suggestion = _finding_text(link)
            finding = Finding(
                analysis_job_id=job.id,
                criterion_version_id=criterion.id,
                severity=("error" if link["status"] == "MISMATCH" else "needs_review"),
                description=description,
                suggestion=suggestion,
                proposed_score=None,
            )
            db.add(finding)
            pending.append((finding, link))
            created += 1
    if pending:
        await db.flush()
        for finding, link in pending:
            db.add(
                EvidenceAnchor(
                    finding_id=finding.id,
                    document_ir_id=document_ir.id,
                    element_id=link["id"],
                    page_number=link["page_number"],
                )
            )
    return created
