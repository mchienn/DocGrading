"""Shared map and notebook pipeline 2 graph/retrieval/verification/scoring."""

from __future__ import annotations

import asyncio
import json
import re
from collections import defaultdict
from decimal import Decimal

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.models.analysis import AnalysisJob, DocumentIR
from app.models.review import EvidenceAnchor, Finding
from app.models.rubric import CriterionVersion
from app.services import logical_pipeline as verification
from app.services import logical_prompts as prompts
from app.services.analysis_logging import error_details, log_event, timed, timed_step
from app.services.logical_llm import (
    EvaluationUnavailable,
    LogicalLLM,
    is_ollama_base_url,
)
from app.services.logical_pipeline import process_pdf_structured_fast
from app.services.logical_schemas import (
    CompactScoredReview,
    ScoredReview,
    map_output_schema,
)
from app.services.score_scale import ten_point_levels

KINDS = frozenset(
    {
        "LOGICAL_CONSISTENCY",
        "TERMINOLOGY_CONSISTENCY",
        "DATA_CONSISTENCY",
        "LOCAL_COHERENCE",
        "GLOBAL_COHERENCE",
    }
)


def criterion_kind(criterion: CriterionVersion) -> str | None:
    method = criterion.evaluation_method.upper()
    # Explicit methods take precedence over stale config after editing a rubric.
    if method in KINDS:
        return method
    if method == "MANUAL":
        return None
    configured = str(criterion.evaluator_config.get("type", "")).upper()
    return configured if configured in KINDS else None


def _normalize(text: str) -> str:
    return " ".join(text.split())


def evidence_for_issue(issue: dict, chunks: list[dict], content: dict) -> list[dict]:
    """Only exact document quotes get PDF anchors; never guess a page or box."""
    indices = issue.get("chunk_indices", [])
    if any(i < 0 or i >= len(chunks) for i in indices):
        return []
    allowed = [_normalize(chunks[i]["content"]) for i in indices]
    quotes = [_normalize(q) for q in issue.get("quotes", []) if len(q.strip()) >= 12]
    quotes = [q for q in quotes if any(q in text for text in allowed)]
    anchors = []
    for paragraph in content.get("paragraphs", []):
        if not paragraph.get("bbox"):
            continue
        text = _normalize(paragraph.get("text", ""))
        matches = [q for q in quotes if q in text]
        if not matches:
            continue
        lines = paragraph.get("lines", [])
        if not lines:
            anchors.append(paragraph)
            continue
        intervals = []
        for quote in matches:
            start = text.find(quote)
            intervals.append((start, start + len(quote)))
        offset = 0
        for line in lines:
            end = offset + len(_normalize(line["text"]))
            if any(offset < stop and end > start for start, stop in intervals):
                anchors.append(line)
            offset = end + 1
    return anchors


def _issue_description(error: object) -> str:
    if isinstance(error, str):
        return error
    if not isinstance(error, dict):
        return json.dumps(error, ensure_ascii=False)
    if isinstance(error.get("description"), str):
        return error["description"]
    if isinstance(error.get("reason"), str) and error["reason"].strip():
        return error["reason"]
    if error.get("type") == "data_conflict":
        left = " ".join(
            str(error.get(key, ""))
            for key in (
                "entity_1",
                "attribute_1",
                "value_1",
                "unit_1",
                "condition_1",
                "time_1",
            )
            if error.get(key)
        )
        right = " ".join(
            str(error.get(key, ""))
            for key in (
                "entity_2",
                "attribute_2",
                "value_2",
                "unit_2",
                "condition_2",
                "time_2",
            )
            if error.get(key)
        )
        return f"Mâu thuẫn số liệu: {left} <> {right}"
    return json.dumps(error, ensure_ascii=False)


def _fallback_issue(error: object) -> dict:
    return {
        "description": _issue_description(error),
        "suggestion": "Giảng viên cần kiểm tra lỗi và xác nhận mức trừ điểm.",
        "chunk_indices": (
            error.get("chunk_indices", []) if isinstance(error, dict) else []
        ),
        "quotes": error.get("quotes", []) if isinstance(error, dict) else [],
    }


def _unavailable_result(
    kind: str,
    errors: list | None = None,
    *,
    stage: str = "",
    error: Exception | None = None,
) -> dict:
    detail = f" Bước {stage} gặp lỗi {type(error).__name__}." if error else ""
    return {
        "status": "NEEDS_REVIEW",
        "score": None,
        "analysis": f"{kind}: Không thể hoàn tất đánh giá tự động. "
        "Giảng viên cần kiểm tra detector/LLM và chấm thủ công." + detail,
        "issues": [_fallback_issue(error) for error in (errors or [])],
        "detector_output": errors or [],
    }


def _scored_result(
    review: ScoredReview, errors: list, extra: dict | None = None
) -> dict:
    indices = [a.issue_index for a in review.annotations]
    if len(set(indices)) != len(indices) or any(i >= len(errors) for i in indices):
        raise EvaluationUnavailable("Invalid issue annotations; manual review required")
    annotations = {a.issue_index: a.model_dump() for a in review.annotations}
    return {
        "status": "SCORED",
        "score": review.score,
        "analysis": review.analysis,
        "issues": [
            annotations.get(i) or {**_fallback_issue(error), "issue_index": i}
            for i, error in enumerate(errors)
        ],
        "detector_output": errors,
        **(extra or {}),
    }


@timed("logical.pipeline")
async def run_pipeline(
    chunks: list[dict],
    criteria: list[CriterionVersion],
    llm: LogicalLLM,
    *,
    section_map: list[dict] | None = None,
) -> dict[str, dict]:
    kinds = {criterion_kind(c) for c in criteria}
    map_prompt = prompts.build_map_prompt(kinds)
    map_schema = map_output_schema(
        {field for kind, (field, _) in prompts.MAP_GROUPS.items() if kind in kinds}
    )
    # Extract only the groups consumed by the selected criteria.
    source_indices = [
        i for i, c in enumerate(chunks) if len(c.get("content", "").strip()) > 50
    ]
    valid = [chunks[i] for i in source_indices]
    if not valid or len(chunks) > get_settings().logical_max_chunks:
        raise EvaluationUnavailable(
            "No usable chunks or document exceeds analysis limit"
        )

    async def map_chunk(index, chunk):
        if not map_prompt:
            # LOCAL_COHERENCE consumes source chunks directly, without MAP.
            return map_schema()
        with timed_step("logical.map.chunk", chunk=index):
            return await llm.call(
                map_prompt,
                prompts.TMPL_MAP.format(
                    sections=_sections(chunk), content=chunk["content"]
                ),
                map_schema,
                phase="map",
            )

    with timed_step("logical.map", chunks=len(valid), total_chunks=len(chunks)):
        mapped = await asyncio.gather(
            *(map_chunk(index, chunk) for index, chunk in enumerate(valid)),
            return_exceptions=True,
        )
    if any(isinstance(item, BaseException) for item in mapped):
        raise EvaluationUnavailable("Incomplete map; manual review required")
    terminology, data_claims, logic_statements = [], [], []
    summaries = defaultdict(list)
    for idx, chunk, parsed in zip(source_indices, valid, mapped, strict=True):
        section = _sections(chunk)
        summaries[section].append(
            {
                "chunk_idx": idx,
                "summary_sentence": getattr(parsed, "summary_sentence", ""),
                "content": chunk["content"],
            }
        )
        terminology.append(
            {
                "chunk_idx": idx,
                "sections": section,
                "data": [t.model_dump() for t in getattr(parsed, "terminology", [])],
            }
        )
        data_claims.extend(
            {**claim.model_dump(), "chunk_idx": idx, "sections": section}
            for claim in getattr(parsed, "data_claims", [])
            if re.search(r"\d", claim.value)
        )
        for stmt in getattr(parsed, "logic_statements", []):
            if any(stmt.model_dump().values()):
                logic_statements.append(
                    {
                        **stmt.model_dump(),
                        "evidence": stmt.source_quote,
                        "section": section,
                        "chunk_idx": idx,
                    }
                )

    def payload(kind, errors):
        return json.dumps(
            {
                "criterion": [
                    {
                        "title": c.title,
                        "description": c.description,
                        "levels": ten_point_levels(c.levels),
                    }
                    for c in criteria
                    if criterion_kind(c) == kind
                ],
                "detected_errors": errors,
                "coverage": {
                    "mapped_chunks": len(valid),
                    "total_chunks": len(chunks),
                    "numeric_claims": len(data_claims),
                    "terminology_entries": sum(len(t["data"]) for t in terminology),
                    "sections": len(summaries),
                },
            },
            ensure_ascii=False,
        )

    errors_by_kind = {}

    async def score(kind, errors=None, extra=None):
        diagnostics = extra if extra is not None else {}
        # Retrieve candidates, then verify them before grading confirmed errors.
        if errors is None:
            try:
                errors = await verification.detect(
                    kind, terminology, data_claims, chunks, llm, diagnostics
                )
            except Exception as exc:
                log_event("detector.unavailable", criterion=kind, **error_details(exc))
                result = _unavailable_result(kind, stage="phát hiện lỗi", error=exc)
                result.update(diagnostics)
                return result
        errors_by_kind[kind] = errors
        log_event("detector.result", criterion=kind, errors=len(errors))
        if not errors and kind == "LOGICAL_CONSISTENCY":
            return _scored_result(
                ScoredReview(
                    score=10,
                    analysis="Không phát hiện lỗi nhất quán logic sau khi hoàn tất "
                    "phát hiện và xác minh các ứng viên. Điểm 10/10 phản ánh "
                    "kết quả kiểm tra tự động trên nội dung đã phân tích.",
                ),
                errors,
                diagnostics,
            )
        if not errors and kind in {
            "TERMINOLOGY_CONSISTENCY",
            "LOCAL_COHERENCE",
            "GLOBAL_COHERENCE",
        }:
            return _scored_result(
                ScoredReview(
                    score=10,
                    analysis="Không phát hiện lỗi đáng kể sau khi hoàn tất kiểm tra "
                    "và xác minh các vị trí nghi vấn. Điểm 10/10 theo pipeline mới; "
                    "kết quả chỉ phản ánh nội dung đã kiểm tra.",
                ),
                errors,
                diagnostics,
            )
        try:
            with timed_step(f"logical.score.{kind}", errors=len(errors)):
                review = await llm.call(
                    prompts.SCORING_PROMPTS[kind],
                    payload(kind, errors),
                    CompactScoredReview,
                )
                review = ScoredReview(**review.model_dump())
                if kind == "LOGICAL_CONSISTENCY" and not any(
                    c.levels for c in criteria if criterion_kind(c) == kind
                ):
                    from app.services.logical_pipeline import score_bounds

                    low, high = score_bounds(errors)
                    review.score = round(min(high, max(low, review.score)), 1)
                return _scored_result(review, errors, diagnostics)
        except EvaluationUnavailable as exc:
            result = _unavailable_result(kind, errors, stage="chấm điểm LLM", error=exc)
            result.update(diagnostics)
            return result

    async def evaluate_kind(kind):
        # Each branch owns its diagnostics and failure boundary. A slow or failed
        # criterion must not prevent the other criteria from completing.
        diagnostics = {}
        try:
            with timed_step(f"logical.criterion.{kind}"):
                if kind == "LOGICAL_CONSISTENCY":
                    with timed_step("logical.detect"):
                        errors = await verification.detect_logic(
                            logic_statements, chunks, llm, diagnostics
                        )
                    return await score(kind, errors, diagnostics)
                if kind == "GLOBAL_COHERENCE":
                    with timed_step("global.assessment"):
                        errors = await verification.detect_global(
                            dict(summaries),
                            llm,
                            diagnostics,
                            **(
                                {"section_map": section_map}
                                if section_map is not None
                                else {}
                            ),
                        )
                    return await score(kind, errors, diagnostics)
                return await score(kind, extra=diagnostics)
        except Exception as exc:
            log_event("criterion.failed", criterion=kind, **error_details(exc))
            return {
                **_unavailable_result(
                    kind,
                    errors_by_kind.get(
                        kind,
                        diagnostics.get(
                            "confirmed_logic_issues",
                            diagnostics.get("confirmed_global_issues", []),
                        ),
                    ),
                    stage="đánh giá tiêu chí",
                    error=exc,
                ),
                **diagnostics,
            }

    # Keep network-bound MAP concurrent, but run CPU-heavy criteria sequentially
    # so SBERT and NLI do not compete for memory and native compute threads.
    selected_kinds = [
        kind
        for kind in (
            "LOGICAL_CONSISTENCY",
            "TERMINOLOGY_CONSISTENCY",
            "DATA_CONSISTENCY",
            "LOCAL_COHERENCE",
            "GLOBAL_COHERENCE",
        )
        if kind in kinds
    ]
    reports = [await evaluate_kind(kind) for kind in selected_kinds]
    results = dict(zip(selected_kinds, reports, strict=True))
    # Preserve original detector output even when scoring fails.
    for kind, errors in errors_by_kind.items():
        results[kind]["detector_output"] = errors
        if results[kind]["status"] == "NEEDS_REVIEW":
            results[kind]["issues"] = [_fallback_issue(error) for error in errors]
    for result in results.values():
        result["chunks"] = chunks
    for kind, result in results.items():
        log_event(
            "criterion.result",
            criterion=kind,
            status=result["status"],
            score=result["score"],
            issues=len(result["issues"]),
        )
    return results


def _sections(chunk: dict) -> str:
    return (
        ", ".join(f"{key}: {value}" for key, value in chunk.get("sections", {}).items())
        or "N/A"
    )


@timed("logical.evaluate")
async def evaluate_logical_consistency(
    db: AsyncSession, job: AnalysisJob, document_ir: DocumentIR, pdf_data: bytes
) -> int:
    criteria = list(
        (
            await db.execute(
                sa.select(CriterionVersion).where(
                    CriterionVersion.rubric_version_id == job.rubric_version_id,
                    CriterionVersion.is_enabled.is_(True),
                )
            )
        ).scalars()
    )
    criteria = [c for c in criteria if criterion_kind(c)]
    if not criteria:
        return 0
    settings = get_settings()
    llm = LogicalLLM()
    try:
        requires_api_key = not is_ollama_base_url(
            getattr(settings, "logical_llm_base_url", ""),
            getattr(settings, "logical_llm_provider", "auto"),
        )
        if (
            not settings.logical_llm_enabled
            or (
                requires_api_key and not settings.logical_llm_api_key.get_secret_value()
            )
            or not settings.logical_llm_model
        ):
            raise EvaluationUnavailable()
        chunks = await asyncio.to_thread(process_pdf_structured_fast, pdf_data)
        results = await run_pipeline(
            chunks["paragraphs"], criteria, llm, section_map=chunks.get("section_map")
        )
    except Exception as exc:
        log_event("logical.unavailable", **error_details(exc))
        results = {
            criterion_kind(c): _unavailable_result(
                criterion_kind(c),
                stage="chuẩn bị và trích xuất dữ liệu",
                error=exc,
            )
            for c in criteria
        }
    finally:
        # Celery creates a new event loop per job; never reuse sockets across loops.
        await llm.aclose()
    # Same-job retries replace findings atomically; approval remains teacher-owned.
    old_ids = list(
        (
            await db.execute(
                sa.select(Finding.id).where(
                    Finding.analysis_job_id == job.id,
                    Finding.criterion_version_id.in_([c.id for c in criteria]),
                )
            )
        ).scalars()
    )
    if old_ids:
        await db.execute(
            sa.delete(EvidenceAnchor).where(EvidenceAnchor.finding_id.in_(old_ids))
        )
        await db.execute(sa.delete(Finding).where(Finding.id.in_(old_ids)))
    reports = []
    count = 0
    for criterion in criteria:
        kind = criterion_kind(criterion)
        result = results.get(
            kind,
            {
                "status": "NEEDS_REVIEW",
                "score": None,
                "analysis": "Chưa chấm tự động được tiêu chí này. "
                "Kiểm tra cấu hình LLM và mô hình; giảng viên cần chấm thủ công.",
                "issues": [],
            },
        )
        finding = Finding(
            analysis_job_id=job.id,
            criterion_version_id=criterion.id,
            severity="criterion_score",
            description=result["analysis"],
            suggestion=None,
            proposed_score=(
                Decimal(str(result["score"])).quantize(Decimal("0.01"))
                if result["score"] is not None
                else None
            ),
        )
        db.add(finding)
        await db.flush()
        report = {k: v for k, v in result.items() if k != "chunks"}
        report.update(
            criterion_version_id=str(criterion.id),
            title=criterion.title,
            kind=kind,
            score_finding_id=str(finding.id),
        )
        reports.append(report)
        count += 1
        for issue in result["issues"]:
            detail = Finding(
                analysis_job_id=job.id,
                criterion_version_id=criterion.id,
                severity="logical_issue",
                description=issue["description"],
                suggestion=issue["suggestion"],
                proposed_score=None,
            )
            db.add(detail)
            await db.flush()
            for anchor in evidence_for_issue(
                issue, result.get("chunks", []), document_ir.content
            ):
                db.add(
                    EvidenceAnchor(
                        finding_id=detail.id,
                        document_ir_id=document_ir.id,
                        element_id=anchor["id"],
                        page_number=anchor["page_number"],
                    )
                )
            count += 1
    job.snapshot = {
        **(job.snapshot or {}),
        "logical_consistency": {
            "schema_version": 3,
            "pipeline_version": "notebook-pipeline-2-graph",
            "score_scale": 10,
            "reports": reports,
            "usage": llm.usage,
        },
    }
    await db.flush()
    return count
