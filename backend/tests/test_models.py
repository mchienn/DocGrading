import sqlalchemy as sa
from sqlalchemy import CheckConstraint, ForeignKeyConstraint, inspect
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, UUID
from sqlalchemy.orm import configure_mappers

from app.db.base import Base
from app.models import (
    AnalysisJob,
    AnalysisJobDispatch,
    Assignment,
    AssignmentRequirement,
    AuditEvent,
    Course,
    CriterionVersion,
    DocumentIR,
    DocumentVersion,
    Membership,
    RubricVersion,
    Session,
    Submission,
    TemplateVersion,
    User,
)

MODEL_TABLE_MAP: dict[type[Base], str] = {
    User: "users",
    Course: "courses",
    Membership: "memberships",
    Assignment: "assignments",
    AssignmentRequirement: "assignment_requirements",
    RubricVersion: "rubric_versions",
    CriterionVersion: "criterion_versions",
    TemplateVersion: "template_versions",
    Submission: "submissions",
    DocumentVersion: "document_versions",
    DocumentIR: "document_irs",
    AnalysisJob: "analysis_jobs",
    AnalysisJobDispatch: "analysis_job_dispatches",
    AuditEvent: "audit_events",
    Session: "sessions",
}


def foreign_key_targets(model: type[Base]) -> set[str]:
    return {
        element.target_fullname
        for constraint in model.__table__.constraints
        if isinstance(constraint, ForeignKeyConstraint)
        for element in constraint.elements
    }


def test_domain_models_register_exact_tables() -> None:
    configure_mappers()
    assert set(Base.metadata.tables) == set(MODEL_TABLE_MAP.values())
    for model, table_name in MODEL_TABLE_MAP.items():
        mapper = inspect(model)
        assert mapper.local_table is Base.metadata.tables[table_name]


def test_public_ids_use_postgresql_uuid_and_are_sole_primary_key() -> None:
    configure_mappers()
    for table_name in MODEL_TABLE_MAP.values():
        table = Base.metadata.tables[table_name]
        assert isinstance(table.c.id.type, UUID)
        assert [col.name for col in table.primary_key.columns] == ["id"]
        assert table.primary_key.name == f"pk_{table_name}"


def test_user_roles_and_json_snapshots_use_postgresql_types() -> None:
    configure_mappers()
    assert isinstance(User.__table__.c.roles.type, ARRAY)
    assert isinstance(AnalysisJob.__table__.c.snapshot.type, JSONB)
    assert isinstance(AuditEvent.__table__.c.before.type, JSONB)
    assert isinstance(AuditEvent.__table__.c.after.type, JSONB)
    assert isinstance(DocumentIR.__table__.c.content.type, JSONB)

def test_ownership_and_version_foreign_keys_are_explicit() -> None:
    configure_mappers()
    assert "users.id" in foreign_key_targets(Course)
    assert {"courses.id", "users.id"} <= foreign_key_targets(Membership)
    assert {"courses.id", "users.id", "rubric_versions.id"} <= foreign_key_targets(
        Assignment
    )
    assert {
        "assignments.id",
        "template_versions.id",
    } <= foreign_key_targets(AssignmentRequirement)
    assert {"assignments.id", "users.id"} <= foreign_key_targets(Submission)
    assert "submissions.id" in foreign_key_targets(DocumentVersion)
    assert {"document_versions.id", "rubric_versions.id"} <= foreign_key_targets(
        AnalysisJob
    )
    assert "analysis_jobs.id" in foreign_key_targets(AnalysisJobDispatch)
    assert "document_versions.id" in foreign_key_targets(DocumentIR)


def test_critical_constraints_and_indexes_have_stable_names() -> None:
    configure_mappers()
    users_checks = {
        c.name
        for c in Base.metadata.tables["users"].constraints
        if isinstance(c, CheckConstraint)
    }
    assert "ck_users_roles_not_empty" in users_checks

    assignments_checks = {
        c.name
        for c in Base.metadata.tables["assignments"].constraints
        if isinstance(c, CheckConstraint)
    }
    assert "ck_assignments_publication_state" in assignments_checks

    audit_events_checks = {
        c.name
        for c in Base.metadata.tables["audit_events"].constraints
        if isinstance(c, CheckConstraint)
    }
    assert {"ck_audit_events_actor", "ck_audit_events_snapshots"} <= audit_events_checks

    analysis_jobs_constraints = {
        constraint.name
        for constraint in Base.metadata.tables["analysis_jobs"].constraints
        if isinstance(constraint, sa.UniqueConstraint)
    }
    assert "uq_analysis_jobs_document_rubric" in analysis_jobs_constraints

    document_irs_checks = {
        c.name
        for c in Base.metadata.tables["document_irs"].constraints
        if isinstance(c, CheckConstraint)
    }
    assert {
        "ck_document_irs_schema_version_positive",
        "ck_document_irs_parser_version_not_blank",
        "ck_document_irs_content_object",
    } <= document_irs_checks

    document_irs_unique = {
        constraint.name
        for constraint in Base.metadata.tables["document_irs"].constraints
        if isinstance(constraint, sa.UniqueConstraint)
    }
    assert "uq_document_irs_document_version_id" in document_irs_unique


def test_required_text_columns_have_stable_nonblank_constraints() -> None:
    configure_mappers()
    expected = {
        "users": {
            "ck_users_email_not_blank",
            "ck_users_display_name_not_blank",
            "ck_users_password_hash_not_blank",
        },
        "courses": {
            "ck_courses_code_not_blank",
            "ck_courses_name_not_blank",
            "ck_courses_term_not_blank",
        },
        "assignments": {"ck_assignments_title_not_blank"},
        "assignment_requirements": {
            "ck_assignment_requirements_kind_not_blank",
            "ck_assignment_requirements_label_not_blank",
        },
        "rubric_versions": {
            "ck_rubric_versions_name_not_blank",
            "ck_rubric_versions_calculation_method_not_blank",
        },
        "criterion_versions": {
            "ck_criterion_versions_code_not_blank",
            "ck_criterion_versions_title_not_blank",
            "ck_criterion_versions_description_not_blank",
            "ck_criterion_versions_evaluation_method_not_blank",
        },
        "template_versions": {"ck_template_versions_name_not_blank"},
        "document_versions": {
            "ck_document_versions_storage_key_not_blank",
            "ck_document_versions_original_filename_not_blank",
            "ck_document_versions_content_type_not_blank",
        },
        "audit_events": {
            "ck_audit_events_resource_type_not_blank",
            "ck_audit_events_action_not_blank",
            "ck_audit_events_reason_not_blank",
        },
        "document_irs": {
            "ck_document_irs_parser_version_not_blank",
        },
    }
    actual = {
        table_name: {
            constraint.name
            for constraint in Base.metadata.tables[table_name].constraints
            if isinstance(constraint, CheckConstraint)
            and constraint.name
            and constraint.name.startswith(f"ck_{table_name}_")
            and constraint.name.endswith("_not_blank")
        }
        for table_name in expected
    }
    assert actual == expected


def test_assignment_first_submission_metadata_is_nullable_timezone() -> None:
    configure_mappers()
    column = Base.metadata.tables["assignments"].c.first_submission_at
    assert column.nullable
    assert isinstance(column.type, sa.DateTime)
    assert column.type.timezone


def test_document_version_declared_sha256_hint_is_nullable() -> None:
    configure_mappers()
    column = Base.metadata.tables["document_versions"].c.declared_sha256
    assert column.nullable


def test_criterion_version_nested_json_mutation_tracks_dirty() -> None:
    cv = CriterionVersion(levels=[{"name": "Level 1", "description": "initial"}])
    state = inspect(cv)
    state._commit_all(state.dict)
    assert not state.modified

    cv.levels[0]["description"] = "updated"
    assert state.modified
