from __future__ import annotations

from typing import Any

from app.main import app

OPENAPI = app.openapi()
PAGED_FIELDS = {"items", "page", "page_size", "total"}
USER_FIELDS = {"id", "email", "display_name", "roles", "status"}
COURSE_FIELDS = {
    "id",
    "code",
    "name",
    "term",
    "status",
    "owner_teacher_id",
    "revision",
}
RUBRIC_FIELDS = {
    "id",
    "rubric_id",
    "version_number",
    "name",
    "description",
    "status",
    "calculation_method",
    "total_weight",
    "owner_user_id",
    "created_by_user_id",
    "published_at",
    "source_version_id",
    "revision",
}
CRITERION_FIELDS = {
    "id",
    "criterion_id",
    "rubric_version_id",
    "code",
    "title",
    "description",
    "weight",
    "position",
    "is_enabled",
    "scope",
    "evaluation_method",
    "evaluator_config",
    "evidence_requirements",
    "levels",
    "revision",
}
ASSIGNMENT_FIELDS = {
    "id",
    "course_id",
    "created_by_teacher_id",
    "rubric_version_id",
    "title",
    "description",
    "due_at",
    "max_submissions",
    "status",
    "published_at",
    "closed_at",
    "revision",
}
PRESIGN_FIELDS = {
    "submission_id",
    "document_version_id",
    "object_key",
    "upload_url",
    "fields",
    "expires_in",
    "status",
    "reused",
    "analysis_job_id",
}
DOWNLOAD_FIELDS = {"url", "expires_in"}
COMPLETION_FIELDS = {
    "submission_id",
    "document_version_id",
    "analysis_job_id",
    "status",
}
ANALYSIS_JOB_FIELDS = {
    "id",
    "document_version_id",
    "rubric_version_id",
    "status",
    "attempt_count",
    "max_attempts",
    "error_code",
    "error_detail",
    "queued_at",
    "started_at",
    "finished_at",
}
QUEUE_ITEM_FIELDS = {
    "submission_id",
    "document_version_id",
    "student_id",
    "document_status",
    "queue_status",
    "submitted_at",
    "review_lock",
}
EVIDENCE_WORKSPACE_FIELDS = {
    "submission_id",
    "document_version_id",
    "findings",
    "citation",
}
FINDING_FIELDS = {
    "id",
    "criterion_version_id",
    "severity",
    "description",
    "suggestion",
    "proposed_score",
    "evidence",
}
EVIDENCE_FIELDS = {"document_ir_id", "element_id", "page_number", "bbox"}
REVIEW_LOCK_FIELDS = {
    "acquired",
    "submission_id",
    "reviewer_user_id",
    "reviewer_display_name",
    "expires_at",
}
REVIEW_DRAFT_FIELDS = {
    "id",
    "submission_id",
    "document_version_id",
    "reviewer_user_id",
    "revision",
    "comment",
    "decisions",
}
APPROVAL_FIELDS = {"document_version_id", "status", "approved_at"}
PUBLISHED_RESULT_FIELDS = {
    "published_result_id",
    "submission_id",
    "document_version_id",
    "version_number",
    "published_at",
    "comment",
    "findings",
}
PUBLISHED_FINDING_FIELDS = {
    "criterion_version_id",
    "finding_id",
    "score",
    "description",
    "suggestion",
    "evidence",
}
REVIEW_REQUEST_FIELDS = {
    "id",
    "published_result_id",
    "submission_id",
    "student_id",
    "criterion_id",
    "finding_id",
    "status",
    "reason",
    "response",
    "responded_by_user_id",
    "responded_at",
    "created_at",
    "updated_at",
}
NOTIFICATION_FIELDS = {"id", "type", "payload", "read_at", "created_at"}
SUBMISSION_VERSION_FIELDS = {
    "document_version_id",
    "version_number",
    "created_at",
    "processing_status",
    "publication_status",
    "published_result_id",
    "published_at",
}
VERSION_COMPARISON_FIELDS = {"submission_id", "left", "right"}
VERSION_SIDE_FIELDS = {"document_version_id", "version_number", "comment", "findings"}
VERSION_FINDING_FIELDS = {
    "criterion_version_id",
    "finding_id",
    "score",
    "decision",
    "evidence_count",
}
ADMIN_USER_FIELDS = {
    "id",
    "email",
    "display_name",
    "roles",
    "status",
    "revision",
    "created_at",
    "updated_at",
}
ADMIN_JOB_LIST_ITEM_FIELDS = {
    "id",
    "course_id",
    "course_code",
    "course_name",
    "assignment_id",
    "submission_id",
    "document_version_id",
    "rubric_version_id",
    "status",
    "attempt_count",
    "max_attempts",
    "error_code",
    "queued_at",
    "started_at",
    "finished_at",
    "created_at",
    "updated_at",
}
ADMIN_JOB_DETAIL_FIELDS = ADMIN_JOB_LIST_ITEM_FIELDS | {"error_detail"}
AUDIT_EVENT_FIELDS = {
    "id",
    "resource_type",
    "resource_id",
    "action",
    "actor_type",
    "actor_user_id",
    "before",
    "after",
    "reason",
    "occurred_at",
}
DASHBOARD_FIELDS = {
    "jobs_by_status",
    "submissions_by_course",
    "open_review_requests",
}
COURSE_COUNT_FIELDS = {"course_id", "course_code", "course_name", "submission_count"}


def _resolve(schema: dict[str, Any]) -> dict[str, Any]:
    reference = schema.get("$ref")
    if reference is None:
        return schema
    name = reference.rsplit("/", 1)[-1]
    return OPENAPI["components"]["schemas"][name]


def _properties(schema: dict[str, Any]) -> dict[str, Any]:
    schema = _resolve(schema)
    properties = dict(schema.get("properties", {}))
    for part in schema.get("allOf", []):
        properties.update(_properties(part))
    return properties


def _response_schema(path: str, method: str, status: int) -> dict[str, Any]:
    return OPENAPI["paths"][path][method]["responses"][str(status)]["content"][
        "application/json"
    ]["schema"]


def _assert_contract(
    path: str,
    method: str,
    status: int,
    fields: set[str],
    *,
    validation: bool = True,
) -> None:
    responses = OPENAPI["paths"][path][method]["responses"]
    expected_statuses = {str(status), "422"} if validation else {str(status)}
    assert set(responses) == expected_statuses
    assert set(_properties(_response_schema(path, method, status))) == fields
    if validation:
        assert responses["422"]["content"]["application/json"]["schema"] == {
            "$ref": "#/components/schemas/HTTPValidationError"
        }


def _assert_nested_fields(
    path: str,
    method: str,
    status: int,
    property_path: tuple[str, ...],
    fields: set[str],
) -> None:
    schema = _response_schema(path, method, status)
    for name in property_path:
        schema = _properties(schema)[name]
        schema = _resolve(schema)
        if schema.get("type") == "array":
            schema = _resolve(schema["items"])
    assert set(_properties(schema)) == fields


def test_step_1_teacher_setup_contracts() -> None:
    contracts = (
        ("/api/v1/auth/login", "post", 200, USER_FIELDS),
        ("/api/v1/courses", "post", 201, COURSE_FIELDS),
        ("/api/v1/rubrics", "post", 201, RUBRIC_FIELDS),
        (
            "/api/v1/rubrics/{rubric_id}/criteria",
            "post",
            201,
            CRITERION_FIELDS,
        ),
        ("/api/v1/rubrics/{rubric_id}/publish", "post", 200, RUBRIC_FIELDS),
        (
            "/api/v1/courses/{course_id}/assignments",
            "post",
            201,
            ASSIGNMENT_FIELDS,
        ),
        (
            "/api/v1/courses/{course_id}/assignments/{assignment_id}/publish",
            "post",
            200,
            ASSIGNMENT_FIELDS,
        ),
        (
            "/api/v1/courses/{course_id}/submission-queue",
            "get",
            200,
            PAGED_FIELDS,
        ),
    )
    for contract in contracts:
        _assert_contract(*contract)
    _assert_nested_fields(
        "/api/v1/courses/{course_id}/submission-queue",
        "get",
        200,
        ("items",),
        QUEUE_ITEM_FIELDS,
    )


def test_step_2_student_upload_and_analysis_contracts() -> None:
    contracts = (
        (
            "/api/v1/courses/{course_id}/assignments/{assignment_id}",
            "get",
            200,
            ASSIGNMENT_FIELDS,
        ),
        (
            "/api/v1/assignments/{assignment_id}/uploads/presign",
            "post",
            201,
            PRESIGN_FIELDS,
        ),
        (
            "/api/v1/document-versions/{version_id}/complete",
            "post",
            202,
            COMPLETION_FIELDS,
        ),
        ("/api/v1/analysis-jobs/{job_id}", "get", 200, ANALYSIS_JOB_FIELDS),
        (
            "/api/v1/document-versions/{version_id}/download",
            "get",
            200,
            DOWNLOAD_FIELDS,
        ),
    )
    for contract in contracts:
        _assert_contract(*contract)


def test_step_3_teacher_review_approval_publication_contracts() -> None:
    contracts = (
        (
            "/api/v1/courses/{course_id}/submission-queue",
            "get",
            200,
            PAGED_FIELDS,
        ),
        (
            "/api/v1/submissions/{submission_id}/evidence",
            "get",
            200,
            EVIDENCE_WORKSPACE_FIELDS,
        ),
        (
            "/api/v1/submissions/{submission_id}/review-lock",
            "post",
            200,
            REVIEW_LOCK_FIELDS,
        ),
        (
            "/api/v1/submissions/{submission_id}/review-draft",
            "put",
            200,
            REVIEW_DRAFT_FIELDS,
        ),
        (
            "/api/v1/document-versions/{version_id}/approve",
            "post",
            200,
            APPROVAL_FIELDS,
        ),
        (
            "/api/v1/document-versions/{version_id}/publish",
            "post",
            200,
            PUBLISHED_RESULT_FIELDS,
        ),
    )
    for contract in contracts:
        _assert_contract(*contract)
    evidence_path = "/api/v1/submissions/{submission_id}/evidence"
    _assert_nested_fields(evidence_path, "get", 200, ("findings",), FINDING_FIELDS)
    _assert_nested_fields(
        evidence_path,
        "get",
        200,
        ("findings", "evidence"),
        EVIDENCE_FIELDS,
    )


def test_step_4_student_result_and_review_request_contracts() -> None:
    result_path = "/api/v1/submissions/{submission_id}/published-result"
    _assert_contract(result_path, "get", 200, PUBLISHED_RESULT_FIELDS)
    _assert_nested_fields(
        result_path,
        "get",
        200,
        ("findings",),
        PUBLISHED_FINDING_FIELDS,
    )
    _assert_nested_fields(
        result_path,
        "get",
        200,
        ("findings", "evidence"),
        EVIDENCE_FIELDS,
    )
    _assert_contract(
        "/api/v1/published-results/{published_result_id}/review-requests",
        "post",
        201,
        REVIEW_REQUEST_FIELDS,
    )


def test_step_5_teacher_response_and_student_notification_contracts() -> None:
    requests_path = "/api/v1/courses/{course_id}/review-requests"
    _assert_contract(requests_path, "get", 200, PAGED_FIELDS)
    _assert_nested_fields(
        requests_path,
        "get",
        200,
        ("items",),
        REVIEW_REQUEST_FIELDS,
    )
    _assert_contract(
        "/api/v1/review-requests/{review_request_id}",
        "patch",
        200,
        REVIEW_REQUEST_FIELDS,
    )
    _assert_contract("/api/v1/notifications", "get", 200, PAGED_FIELDS)
    _assert_nested_fields(
        "/api/v1/notifications",
        "get",
        200,
        ("items",),
        NOTIFICATION_FIELDS,
    )


def test_step_6_resubmission_and_comparison_contracts() -> None:
    versions_path = "/api/v1/submissions/{submission_id}/versions"
    comparison_path = "/api/v1/submissions/{submission_id}/versions/compare"
    contracts = (
        (
            "/api/v1/assignments/{assignment_id}/uploads/presign",
            "post",
            201,
            PRESIGN_FIELDS,
        ),
        (
            "/api/v1/document-versions/{version_id}/complete",
            "post",
            202,
            COMPLETION_FIELDS,
        ),
        (versions_path, "get", 200, PAGED_FIELDS),
        (comparison_path, "get", 200, VERSION_COMPARISON_FIELDS),
    )
    for contract in contracts:
        _assert_contract(*contract)
    _assert_nested_fields(
        versions_path,
        "get",
        200,
        ("items",),
        SUBMISSION_VERSION_FIELDS,
    )
    for side in ("left", "right"):
        _assert_nested_fields(
            comparison_path,
            "get",
            200,
            (side,),
            VERSION_SIDE_FIELDS,
        )
        _assert_nested_fields(
            comparison_path,
            "get",
            200,
            (side, "findings"),
            VERSION_FINDING_FIELDS,
        )


def test_step_7_admin_operations_and_retry_contracts() -> None:
    jobs_path = "/api/v1/operations/analysis-jobs"
    detail_path = "/api/v1/operations/analysis-jobs/{job_id}"
    retry_path = "/api/v1/operations/analysis-jobs/{job_id}/retry"
    audit_path = "/api/v1/operations/audit-events"
    dashboard_path = "/api/v1/operations/dashboard"
    contracts = (
        ("/api/v1/users", "get", 200, PAGED_FIELDS),
        (jobs_path, "get", 200, PAGED_FIELDS),
        (detail_path, "get", 200, ADMIN_JOB_DETAIL_FIELDS),
        (retry_path, "post", 200, ADMIN_JOB_DETAIL_FIELDS),
        (audit_path, "get", 200, PAGED_FIELDS),
        (dashboard_path, "get", 200, DASHBOARD_FIELDS),
    )
    for path, method, status, fields in contracts:
        _assert_contract(
            path,
            method,
            status,
            fields,
            validation=path != dashboard_path,
        )
    _assert_nested_fields("/api/v1/users", "get", 200, ("items",), ADMIN_USER_FIELDS)
    _assert_nested_fields(jobs_path, "get", 200, ("items",), ADMIN_JOB_LIST_ITEM_FIELDS)
    _assert_nested_fields(audit_path, "get", 200, ("items",), AUDIT_EVENT_FIELDS)
    _assert_nested_fields(
        dashboard_path,
        "get",
        200,
        ("submissions_by_course",),
        COURSE_COUNT_FIELDS,
    )
