from __future__ import annotations

import uuid

from app.api.schemas_course import CourseJoinCodeResponse
from app.main import create_app
from app.models.enums import CourseJoinOutcome
from app.services.course_join import CODE_ALPHABET, generate_join_code, normalize_join_code
from app.services.operations import _AUDIT_SAFE_FIELDS


def test_join_code_has_100_bit_unambiguous_shape_and_normalizes_case() -> None:
    code = generate_join_code()
    assert len(code) == 20
    assert set(code) <= set(CODE_ALPHABET)
    assert normalize_join_code(f"  {code.lower()} ") == code
    assert not set(code) & set("01ILO")


def test_t027_openapi_paths_and_fields() -> None:
    schema = create_app().openapi()
    paths = schema["paths"]
    assert {
        "post",
        "get",
        "put",
        "delete",
    } <= set(paths["/api/v1/courses/{course_id}/join-code"])
    assert "post" in paths["/api/v1/courses/{course_id}/join-code/regenerate"]
    assert "get" in paths["/api/v1/courses/{course_id}/join-code/qr"]
    assert "post" in paths["/api/v1/course-joins"]
    assert set(schema["components"]["schemas"]["CourseJoinCodeResponse"]["properties"]) == {
        "id",
        "course_id",
        "code",
        "expires_at",
        "revoked_at",
        "status",
        "join_url",
        "qr_url",
    }


def test_join_outcomes_and_audit_allowlist_redact_credentials() -> None:
    assert {item.value for item in CourseJoinOutcome} == {
        "JOINED",
        "REACTIVATED",
        "ALREADY_MEMBER",
    }
    assert "CourseJoinCode" in _AUDIT_SAFE_FIELDS
    assert "code" not in _AUDIT_SAFE_FIELDS["CourseJoinCode"]
    assert "join_url" not in _AUDIT_SAFE_FIELDS["CourseJoinCode"]
    assert "ip" not in _AUDIT_SAFE_FIELDS["CourseJoinCode"]


def test_teacher_response_schema_is_explicit() -> None:
    response = CourseJoinCodeResponse(
        id=uuid.uuid4(),
        course_id=uuid.uuid4(),
        code="ABCDEFGHJKMNPQRSTUVWX",
        expires_at="2026-09-17T00:00:00Z",
        revoked_at=None,
        status="ACTIVE",
        join_url="http://localhost:5173/student/join?code=ABCDEFGHJKMNPQRSTUVWX",
        qr_url="/api/v1/courses/00000000-0000-0000-0000-000000000000/join-code/qr",
    )
    assert response.status == "ACTIVE"
