from sqlalchemy import CheckConstraint, ForeignKeyConstraint, Index
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, UUID
from sqlalchemy.orm import configure_mappers

from app.db.base import Base
from app.models import (
    AnalysisJob,
    Assignment,
    AssignmentRequirement,
    AuditEvent,
    Course,
    CriterionVersion,
    DocumentVersion,
    Membership,
    RubricVersion,
    Submission,
    TemplateVersion,
    User,
)

EXPECTED_TABLES = {
    "analysis_jobs",
    "assignment_requirements",
    "assignments",
    "audit_events",
    "courses",
    "criterion_versions",
    "document_versions",
    "memberships",
    "rubric_versions",
    "submissions",
    "template_versions",
    "users",
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
    assert set(Base.metadata.tables) == EXPECTED_TABLES


def test_public_ids_use_postgresql_uuid() -> None:
    configure_mappers()
    for table_name in EXPECTED_TABLES:
        assert isinstance(Base.metadata.tables[table_name].c.id.type, UUID)


def test_user_roles_and_json_snapshots_use_postgresql_types() -> None:
    configure_mappers()
    assert isinstance(User.__table__.c.roles.type, ARRAY)
    assert isinstance(AnalysisJob.__table__.c.snapshot.type, JSONB)
    assert isinstance(AuditEvent.__table__.c.before.type, JSONB)
    assert isinstance(AuditEvent.__table__.c.after.type, JSONB)


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


def test_critical_constraints_and_indexes_have_stable_names() -> None:
    configure_mappers()
    names = {
        item.name
        for table in Base.metadata.tables.values()
        for item in (*table.constraints, *table.indexes)
        if isinstance(item, (CheckConstraint, Index)) and item.name is not None
    }
    assert {
        "ck_users_roles_not_empty",
        "ck_assignments_publication_state",
        "ck_audit_events_actor",
        "ck_audit_events_snapshots",
        "uq_analysis_jobs_active_document_rubric",
    } <= names
