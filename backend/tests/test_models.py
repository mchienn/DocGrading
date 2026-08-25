from sqlalchemy import CheckConstraint, ForeignKeyConstraint, Index, inspect
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
    AnalysisJob: "analysis_jobs",
    AuditEvent: "audit_events",
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

    analysis_jobs_indexes = {
        idx.name
        for idx in Base.metadata.tables["analysis_jobs"].indexes
        if isinstance(idx, Index)
    }
    assert "uq_analysis_jobs_active_document_rubric" in analysis_jobs_indexes


def test_criterion_version_nested_json_mutation_tracks_dirty() -> None:
    cv = CriterionVersion(levels=[{"name": "Level 1", "description": "initial"}])
    state = inspect(cv)
    state._commit_all(state.dict)
    assert not state.modified

    cv.levels[0]["description"] = "updated"
    assert state.modified
