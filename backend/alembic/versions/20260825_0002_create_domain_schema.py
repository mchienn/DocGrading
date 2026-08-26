"""Create the domain schema and database invariants."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql


revision: str = "20260825_0002"
down_revision: str | None = "20260825_0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


user_role = postgresql.ENUM(
    "ADMIN",
    "TEACHER",
    "STUDENT",
    name="user_role",
    create_type=False,
)
user_status = postgresql.ENUM(
    "ACTIVE",
    "LOCKED",
    name="user_status",
    create_type=False,
)
membership_role = postgresql.ENUM(
    "TEACHER",
    "STUDENT",
    name="membership_role",
    create_type=False,
)
membership_status = postgresql.ENUM(
    "ACTIVE",
    "INACTIVE",
    name="membership_status",
    create_type=False,
)
assignment_status = postgresql.ENUM(
    "DRAFT",
    "OPEN",
    "CLOSED",
    "ARCHIVED",
    name="assignment_status",
    create_type=False,
)
rubric_status = postgresql.ENUM(
    "DRAFT",
    "PUBLISHED",
    "ARCHIVED",
    name="rubric_status",
    create_type=False,
)
document_status = postgresql.ENUM(
    "UPLOADING",
    "VALIDATING",
    "INVALID",
    "QUEUED",
    "PROCESSING",
    "AWAITING_REVIEW",
    "APPROVED",
    "PUBLISHED",
    "PROCESSING_FAILED",
    name="document_status",
    create_type=False,
)
analysis_job_status = postgresql.ENUM(
    "QUEUED",
    "RUNNING",
    "SUCCEEDED",
    "FAILED",
    "CANCELLED",
    name="analysis_job_status",
    create_type=False,
)
audit_actor_type = postgresql.ENUM(
    "USER",
    "SYSTEM",
    name="audit_actor_type",
    create_type=False,
)

_ENUMS = (
    user_role,
    user_status,
    membership_role,
    membership_status,
    assignment_status,
    rubric_status,
    document_status,
    analysis_job_status,
    audit_actor_type,
)


def _create_enum_types() -> None:
    bind = op.get_bind()
    for enum_type in _ENUMS:
        enum_type.create(bind, checkfirst=False)


def _drop_enum_types() -> None:
    bind = op.get_bind()
    for enum_type in reversed(_ENUMS):
        enum_type.drop(bind, checkfirst=False)


def upgrade() -> None:
    _create_enum_types()

    op.create_table(
        "users",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("revision", sa.Integer(), server_default=sa.text("1"), nullable=False),
        sa.Column("email", sa.String(length=320), nullable=False),
        sa.Column("display_name", sa.String(length=255), nullable=False),
        sa.Column("password_hash", sa.String(length=255), nullable=False),
        sa.Column("roles", postgresql.ARRAY(user_role), nullable=False),
        sa.Column("status", user_status, server_default=sa.text("'ACTIVE'::user_status"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.CheckConstraint("cardinality(roles) > 0", name="ck_users_roles_not_empty"),
        sa.CheckConstraint("revision > 0", name="ck_users_revision_positive"),
    )
    op.create_index(
        "uq_users_email_lower",
        "users",
        [sa.text("lower(email)")],
        unique=True,
    )

    op.create_table(
        "courses",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("revision", sa.Integer(), server_default=sa.text("1"), nullable=False),
        sa.Column("code", sa.String(length=64), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("term", sa.String(length=128), nullable=False),
        sa.Column("owner_teacher_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("code", name="uq_courses_code"),
        sa.CheckConstraint("revision > 0", name="ck_courses_revision_positive"),
        sa.ForeignKeyConstraint(
            ["owner_teacher_id"],
            ["users.id"],
            name="fk_courses_owner_teacher_id_users",
            ondelete="RESTRICT",
        ),
    )

    op.create_table(
        "memberships",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("course_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("role", membership_role, nullable=False),
        sa.Column("status", membership_status, server_default=sa.text("'ACTIVE'::membership_status"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("course_id", "user_id", "role", name="uq_memberships_course_user_role"),
        sa.ForeignKeyConstraint(
            ["course_id"],
            ["courses.id"],
            name="fk_memberships_course_id_courses",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name="fk_memberships_user_id_users",
            ondelete="RESTRICT",
        ),
    )

    op.create_table(
        "rubric_versions",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("revision", sa.Integer(), server_default=sa.text("1"), nullable=False),
        sa.Column("rubric_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("version_number", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("status", rubric_status, server_default=sa.text("'DRAFT'::rubric_status"), nullable=False),
        sa.Column("calculation_method", sa.String(length=64), server_default=sa.text("'WEIGHTED_SUM'"), nullable=False),
        sa.Column("total_weight", sa.Numeric(precision=6, scale=2), server_default=sa.text("0.00"), nullable=False),
        sa.Column("owner_user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("created_by_user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("source_version_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("rubric_id", "version_number", name="uq_rubric_versions_rubric_version"),
        sa.CheckConstraint("version_number > 0", name="ck_rubric_versions_version_number_positive"),
        sa.CheckConstraint("total_weight >= 0.00 AND total_weight <= 100.00", name="ck_rubric_versions_total_weight_range"),
        sa.CheckConstraint(
            "(status = 'DRAFT' AND published_at IS NULL) OR "
            "(status IN ('PUBLISHED', 'ARCHIVED') AND published_at IS NOT NULL)",
            name="ck_rubric_versions_publication_state",
        ),
        sa.CheckConstraint("revision > 0", name="ck_rubric_versions_revision_positive"),
        sa.ForeignKeyConstraint(
            ["owner_user_id"],
            ["users.id"],
            name="fk_rubric_versions_owner_user_id_users",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["created_by_user_id"],
            ["users.id"],
            name="fk_rubric_versions_created_by_user_id_users",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["source_version_id"],
            ["rubric_versions.id"],
            name="fk_rubric_versions_source_version_id_rubric_versions",
            ondelete="RESTRICT",
        ),
    )

    op.create_table(
        "criterion_versions",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("revision", sa.Integer(), server_default=sa.text("1"), nullable=False),
        sa.Column("criterion_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("rubric_version_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("code", sa.String(length=64), nullable=False),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("scope", sa.String(length=255), nullable=True),
        sa.Column("weight", sa.Numeric(precision=6, scale=2), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("is_enabled", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("evaluation_method", sa.String(length=64), nullable=False),
        sa.Column("levels", postgresql.JSONB(), server_default=sa.text("'[]'::jsonb"), nullable=False),
        sa.Column("evaluator_config", postgresql.JSONB(), server_default=sa.text("'{}'::jsonb"), nullable=False),
        sa.Column("evidence_requirements", postgresql.JSONB(), server_default=sa.text("'{}'::jsonb"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("rubric_version_id", "criterion_id", name="uq_criterion_versions_rubric_version_criterion"),
        sa.UniqueConstraint("rubric_version_id", "code", name="uq_criterion_versions_rubric_version_code"),
        sa.UniqueConstraint("rubric_version_id", "position", name="uq_criterion_versions_rubric_version_position"),
        sa.CheckConstraint("weight >= 0.00 AND weight <= 100.00", name="ck_criterion_versions_weight_range"),
        sa.CheckConstraint("position > 0", name="ck_criterion_versions_position_positive"),
        sa.CheckConstraint("revision > 0", name="ck_criterion_versions_revision_positive"),
        sa.CheckConstraint("jsonb_typeof(levels) = 'array'", name="ck_criterion_versions_levels_is_array"),
        sa.CheckConstraint("jsonb_typeof(evaluator_config) = 'object'", name="ck_criterion_versions_evaluator_config_is_object"),
        sa.CheckConstraint("jsonb_typeof(evidence_requirements) = 'object'", name="ck_criterion_versions_evidence_requirements_is_object"),
        sa.ForeignKeyConstraint(
            ["rubric_version_id"],
            ["rubric_versions.id"],
            name="fk_criterion_versions_rubric_version_id_rubric_versions",
            ondelete="CASCADE",
        ),
    )

    op.create_table(
        "template_versions",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("template_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("version_number", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("owner_user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("created_by_user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("structure", postgresql.JSONB(), server_default=sa.text("'{}'::jsonb"), nullable=False),
        sa.Column("storage_key", sa.String(length=1024), nullable=True),
        sa.Column("sha256", sa.String(length=64), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("template_id", "version_number", name="uq_template_versions_template_version"),
        sa.CheckConstraint("version_number > 0", name="ck_template_versions_version_number_positive"),
        sa.CheckConstraint("jsonb_typeof(structure) = 'object'", name="ck_template_versions_structure_is_object"),
        sa.CheckConstraint("sha256 IS NULL OR sha256 ~ '^[0-9a-f]{64}$'", name="ck_template_versions_sha256_format"),
        sa.ForeignKeyConstraint(
            ["owner_user_id"],
            ["users.id"],
            name="fk_template_versions_owner_user_id_users",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["created_by_user_id"],
            ["users.id"],
            name="fk_template_versions_created_by_user_id_users",
            ondelete="RESTRICT",
        ),
    )

    op.create_table(
        "assignments",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("revision", sa.Integer(), server_default=sa.text("1"), nullable=False),
        sa.Column("course_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("created_by_teacher_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("rubric_version_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("due_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("max_submissions", sa.Integer(), server_default=sa.text("3"), nullable=False),
        sa.Column("status", assignment_status, server_default=sa.text("'DRAFT'::assignment_status"), nullable=False),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("closed_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.CheckConstraint("max_submissions >= 1 AND max_submissions <= 5", name="ck_assignments_max_submissions"),
        sa.CheckConstraint(
            "(status = 'DRAFT' AND published_at IS NULL AND closed_at IS NULL) OR "
            "(status = 'OPEN' AND published_at IS NOT NULL AND closed_at IS NULL) OR "
            "(status IN ('CLOSED', 'ARCHIVED') AND published_at IS NOT NULL AND closed_at IS NOT NULL)",
            name="ck_assignments_publication_state",
        ),
        sa.CheckConstraint("revision > 0", name="ck_assignments_revision_positive"),
        sa.ForeignKeyConstraint(
            ["course_id"],
            ["courses.id"],
            name="fk_assignments_course_id_courses",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["created_by_teacher_id"],
            ["users.id"],
            name="fk_assignments_created_by_teacher_id_users",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["rubric_version_id"],
            ["rubric_versions.id"],
            name="fk_assignments_rubric_version_id_rubric_versions",
            ondelete="RESTRICT",
        ),
    )

    op.create_table(
        "assignment_requirements",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("assignment_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("kind", sa.String(length=32), nullable=False),
        sa.Column("label", sa.String(length=255), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("is_required", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("max_file_size_bytes", sa.BigInteger(), nullable=True),
        sa.Column("max_page_count", sa.Integer(), nullable=True),
        sa.Column("text_layer_required", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("template_version_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("assignment_id", "position", name="uq_assignment_requirements_position"),
        sa.CheckConstraint("position > 0", name="ck_assignment_requirements_position_positive"),
        sa.CheckConstraint("max_file_size_bytes IS NULL OR max_file_size_bytes > 0", name="ck_assignment_requirements_max_file_size_bytes_positive"),
        sa.CheckConstraint("max_page_count IS NULL OR max_page_count > 0", name="ck_assignment_requirements_max_page_count_positive"),
        sa.ForeignKeyConstraint(
            ["assignment_id"],
            ["assignments.id"],
            name="fk_assignment_requirements_assignment_id_assignments",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["template_version_id"],
            ["template_versions.id"],
            name="fk_assignment_requirements_template_version_templates",
            ondelete="RESTRICT",
        ),
    )

    op.create_table(
        "submissions",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("assignment_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("student_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("assignment_id", "student_id", name="uq_submissions_assignment_student"),
        sa.ForeignKeyConstraint(
            ["assignment_id"],
            ["assignments.id"],
            name="fk_submissions_assignment_id_assignments",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["student_id"],
            ["users.id"],
            name="fk_submissions_student_id_users",
            ondelete="RESTRICT",
        ),
    )

    op.create_table(
        "document_versions",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("submission_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("version_number", sa.Integer(), nullable=False),
        sa.Column("previous_version_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("storage_key", sa.String(length=1024), nullable=False),
        sa.Column("original_filename", sa.String(length=255), nullable=False),
        sa.Column("content_type", sa.String(length=128), nullable=False),
        sa.Column("size_bytes", sa.BigInteger(), nullable=False),
        sa.Column("page_count", sa.Integer(), nullable=True),
        sa.Column("sha256", sa.String(length=64), nullable=False),
        sa.Column("status", document_status, server_default=sa.text("'UPLOADING'::document_status"), nullable=False),
        sa.Column("failure_code", sa.String(length=64), nullable=True),
        sa.Column("failure_detail", sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("submission_id", "version_number", name="uq_document_versions_submission_version"),
        sa.UniqueConstraint("submission_id", "sha256", name="uq_document_versions_submission_sha256"),
        sa.CheckConstraint("version_number > 0", name="ck_document_versions_version_number_positive"),
        sa.CheckConstraint("size_bytes > 0", name="ck_document_versions_size_bytes_positive"),
        sa.CheckConstraint("page_count IS NULL OR page_count > 0", name="ck_document_versions_page_count_positive"),
        sa.CheckConstraint("sha256 ~ '^[0-9a-f]{64}$'", name="ck_document_versions_sha256_format"),
        sa.ForeignKeyConstraint(
            ["submission_id"],
            ["submissions.id"],
            name="fk_document_versions_submission_id_submissions",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["previous_version_id"],
            ["document_versions.id"],
            name="fk_document_versions_previous_version_id_document_versions",
            ondelete="RESTRICT",
        ),
    )

    op.create_table(
        "analysis_jobs",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("document_version_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("rubric_version_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("status", analysis_job_status, server_default=sa.text("'QUEUED'::analysis_job_status"), nullable=False),
        sa.Column("attempt_count", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("max_attempts", sa.Integer(), server_default=sa.text("3"), nullable=False),
        sa.Column("snapshot", postgresql.JSONB(), server_default=sa.text("'{}'::jsonb"), nullable=False),
        sa.Column("queued_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("error_code", sa.String(length=64), nullable=True),
        sa.Column("error_detail", sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.CheckConstraint("max_attempts > 0 AND attempt_count >= 0 AND attempt_count <= max_attempts", name="ck_analysis_jobs_attempts"),
        sa.CheckConstraint("jsonb_typeof(snapshot) = 'object'", name="ck_analysis_jobs_snapshot_object"),
        sa.ForeignKeyConstraint(
            ["document_version_id"],
            ["document_versions.id"],
            name="fk_analysis_jobs_document_version_id_document_versions",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["rubric_version_id"],
            ["rubric_versions.id"],
            name="fk_analysis_jobs_rubric_version_id_rubric_versions",
            ondelete="RESTRICT",
        ),
    )
    op.create_index(
        "uq_analysis_jobs_active_document_rubric",
        "analysis_jobs",
        ["document_version_id", "rubric_version_id"],
        unique=True,
        postgresql_where=sa.text("status IN ('QUEUED', 'RUNNING')"),
    )

    op.create_table(
        "audit_events",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("resource_type", sa.String(length=128), nullable=False),
        sa.Column("resource_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("action", sa.String(length=128), nullable=False),
        sa.Column("actor_type", audit_actor_type, nullable=False),
        sa.Column("actor_user_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("before", postgresql.JSONB(), nullable=True),
        sa.Column("after", postgresql.JSONB(), nullable=True),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.CheckConstraint(
            "(actor_type = 'USER' AND actor_user_id IS NOT NULL) OR "
            "(actor_type = 'SYSTEM' AND actor_user_id IS NULL)",
            name="ck_audit_events_actor",
        ),
        sa.CheckConstraint("before IS NOT NULL OR after IS NOT NULL", name="ck_audit_events_snapshots"),
        sa.CheckConstraint("before IS NULL OR jsonb_typeof(before) = 'object'", name="ck_audit_events_before_object"),
        sa.CheckConstraint("after IS NULL OR jsonb_typeof(after) = 'object'", name="ck_audit_events_after_object"),
        sa.CheckConstraint("length(trim(reason)) > 0", name="ck_audit_events_reason_not_blank"),
        sa.ForeignKeyConstraint(
            ["actor_user_id"],
            ["users.id"],
            name="fk_audit_events_actor_user_id_users",
            ondelete="RESTRICT",
        ),
    )
    op.create_index("ix_audit_events_resource", "audit_events", ["resource_type", "resource_id"])
    op.create_index("ix_audit_events_occurred_at", "audit_events", ["occurred_at"])

    op.execute(
        sa.text(
            """
            CREATE FUNCTION fn_validate_course_owner()
            RETURNS trigger
            LANGUAGE plpgsql
            AS $$
            BEGIN
                IF NOT EXISTS (
                    SELECT 1
                    FROM users AS u
                    WHERE u.id = NEW.owner_teacher_id
                      AND 'TEACHER'::user_role = ANY (u.roles)
                ) THEN
                    RAISE EXCEPTION USING
                        ERRCODE = '23514',
                        MESSAGE = 'course owner must have TEACHER role';
                END IF;
                RETURN NEW;
            END;
            $$;
            """
        )
    )
    op.execute(
        sa.text(
            """
            CREATE TRIGGER trg_validate_course_owner
            BEFORE INSERT OR UPDATE OF owner_teacher_id ON courses
            FOR EACH ROW EXECUTE FUNCTION fn_validate_course_owner();
            """
        )
    )

    op.execute(
        sa.text(
            """
            CREATE FUNCTION fn_validate_membership_role()
            RETURNS trigger
            LANGUAGE plpgsql
            AS $$
            BEGIN
                IF NOT EXISTS (
                    SELECT 1
                    FROM users AS u
                    WHERE u.id = NEW.user_id
                      AND EXISTS (
                          SELECT 1
                          FROM unnest(u.roles) AS r
                          WHERE r::text = NEW.role::text
                      )
                ) THEN
                    RAISE EXCEPTION USING
                        ERRCODE = '23514',
                        MESSAGE = 'membership role must be present in user roles';
                END IF;
                RETURN NEW;
            END;
            $$;
            """
        )
    )
    op.execute(
        sa.text(
            """
            CREATE TRIGGER trg_validate_membership_role
            BEFORE INSERT OR UPDATE OF user_id, role ON memberships
            FOR EACH ROW EXECUTE FUNCTION fn_validate_membership_role();
            """
        )
    )

    op.execute(
        sa.text(
            """
            CREATE FUNCTION fn_prevent_role_removal()
            RETURNS trigger
            LANGUAGE plpgsql
            AS $$
            BEGIN
                IF (
                    NOT ('TEACHER'::user_role = ANY (NEW.roles))
                    AND EXISTS (
                        SELECT 1 FROM courses AS c WHERE c.owner_teacher_id = OLD.id
                    )
                ) OR EXISTS (
                    SELECT 1
                    FROM memberships AS m
                    WHERE m.user_id = OLD.id
                      AND NOT EXISTS (
                          SELECT 1
                          FROM unnest(NEW.roles) AS r
                          WHERE r::text = m.role::text
                      )
                ) THEN
                    RAISE EXCEPTION USING
                        ERRCODE = '23514',
                        MESSAGE = 'cannot remove role used by course or membership';
                END IF;
                RETURN NEW;
            END;
            $$;
            """
        )
    )
    op.execute(
        sa.text(
            """
            CREATE TRIGGER trg_prevent_role_removal
            BEFORE UPDATE OF roles ON users
            FOR EACH ROW EXECUTE FUNCTION fn_prevent_role_removal();
            """
        )
    )

    op.execute(
        sa.text(
            """
            CREATE FUNCTION fn_validate_submission_student()
            RETURNS trigger
            LANGUAGE plpgsql
            AS $$
            BEGIN
                IF NOT EXISTS (
                    SELECT 1
                    FROM users AS u
                    WHERE u.id = NEW.student_id
                      AND 'STUDENT'::user_role = ANY (u.roles)
                ) OR NOT EXISTS (
                    SELECT 1
                    FROM assignments AS a
                    JOIN memberships AS m ON m.course_id = a.course_id
                    WHERE a.id = NEW.assignment_id
                      AND m.user_id = NEW.student_id
                      AND m.role::text = 'STUDENT'
                      AND m.status = 'ACTIVE'::membership_status
                ) THEN
                    RAISE EXCEPTION USING
                        ERRCODE = '23514',
                        MESSAGE = 'student must have active course membership';
                END IF;
                RETURN NEW;
            END;
            $$;
            """
        )
    )
    op.execute(
        sa.text(
            """
            CREATE TRIGGER trg_validate_submission_student
            BEFORE INSERT OR UPDATE OF assignment_id, student_id ON submissions
            FOR EACH ROW EXECUTE FUNCTION fn_validate_submission_student();
            """
        )
    )

    op.execute(
        sa.text(
            """
            CREATE FUNCTION fn_immut_rubric_version()
            RETURNS trigger
            LANGUAGE plpgsql
            AS $$
            BEGIN
                IF EXISTS (
                    SELECT 1
                    FROM assignments AS a
                    JOIN submissions AS s ON s.assignment_id = a.id
                    WHERE a.rubric_version_id = OLD.id
                ) THEN
                    RAISE EXCEPTION USING
                        ERRCODE = '23514',
                        MESSAGE = 'rubric version is immutable after first submission';
                END IF;
                IF TG_OP = 'DELETE' THEN
                    RETURN OLD;
                END IF;
                RETURN NEW;
            END;
            $$;
            """
        )
    )
    op.execute(
        sa.text(
            """
            CREATE TRIGGER trg_immut_rubric_version
            BEFORE UPDATE OR DELETE ON rubric_versions
            FOR EACH ROW EXECUTE FUNCTION fn_immut_rubric_version();
            """
        )
    )

    op.execute(
        sa.text(
            """
            CREATE FUNCTION fn_immut_criterion_version()
            RETURNS trigger
            LANGUAGE plpgsql
            AS $$
            BEGIN
                IF EXISTS (
                    SELECT 1
                    FROM assignments AS a
                    JOIN submissions AS s ON s.assignment_id = a.id
                    WHERE a.rubric_version_id = OLD.rubric_version_id
                ) THEN
                    RAISE EXCEPTION USING
                        ERRCODE = '23514',
                        MESSAGE = 'criterion version is immutable after first submission';
                END IF;
                IF TG_OP = 'DELETE' THEN
                    RETURN OLD;
                END IF;
                RETURN NEW;
            END;
            $$;
            """
        )
    )
    op.execute(
        sa.text(
            """
            CREATE TRIGGER trg_immut_criterion_version
            BEFORE UPDATE OR DELETE ON criterion_versions
            FOR EACH ROW EXECUTE FUNCTION fn_immut_criterion_version();
            """
        )
    )

    op.execute(
        sa.text(
            """
            CREATE FUNCTION fn_immut_assignment_rubric()
            RETURNS trigger
            LANGUAGE plpgsql
            AS $$
            BEGIN
                IF NEW.rubric_version_id IS DISTINCT FROM OLD.rubric_version_id
                   AND EXISTS (
                       SELECT 1 FROM submissions AS s WHERE s.assignment_id = OLD.id
                   ) THEN
                    RAISE EXCEPTION USING
                        ERRCODE = '23514',
                        MESSAGE = 'assignment rubric is immutable after first submission';
                END IF;
                RETURN NEW;
            END;
            $$;
            """
        )
    )
    op.execute(
        sa.text(
            """
            CREATE TRIGGER trg_immut_assignment_rubric
            BEFORE UPDATE OF rubric_version_id ON assignments
            FOR EACH ROW EXECUTE FUNCTION fn_immut_assignment_rubric();
            """
        )
    )

    op.execute(
        sa.text(
            """
            CREATE FUNCTION fn_audit_events_append_only()
            RETURNS trigger
            LANGUAGE plpgsql
            AS $$
            BEGIN
                RAISE EXCEPTION USING
                    ERRCODE = '23514',
                    MESSAGE = 'audit events are append-only';
            END;
            $$;
            """
        )
    )
    op.execute(
        sa.text(
            """
            CREATE TRIGGER trg_audit_events_append_only
            BEFORE UPDATE OR DELETE ON audit_events
            FOR EACH ROW EXECUTE FUNCTION fn_audit_events_append_only();
            """
        )
    )


def downgrade() -> None:
    op.execute(sa.text("DROP TRIGGER IF EXISTS trg_audit_events_append_only ON audit_events"))
    op.execute(sa.text("DROP TRIGGER IF EXISTS trg_immut_assignment_rubric ON assignments"))
    op.execute(sa.text("DROP TRIGGER IF EXISTS trg_immut_criterion_version ON criterion_versions"))
    op.execute(sa.text("DROP TRIGGER IF EXISTS trg_immut_rubric_version ON rubric_versions"))
    op.execute(sa.text("DROP TRIGGER IF EXISTS trg_validate_submission_student ON submissions"))
    op.execute(sa.text("DROP TRIGGER IF EXISTS trg_prevent_role_removal ON users"))
    op.execute(sa.text("DROP TRIGGER IF EXISTS trg_validate_membership_role ON memberships"))
    op.execute(sa.text("DROP TRIGGER IF EXISTS trg_validate_course_owner ON courses"))

    op.execute(sa.text("DROP FUNCTION IF EXISTS fn_audit_events_append_only()"))
    op.execute(sa.text("DROP FUNCTION IF EXISTS fn_immut_assignment_rubric()"))
    op.execute(sa.text("DROP FUNCTION IF EXISTS fn_immut_criterion_version()"))
    op.execute(sa.text("DROP FUNCTION IF EXISTS fn_immut_rubric_version()"))
    op.execute(sa.text("DROP FUNCTION IF EXISTS fn_validate_submission_student()"))
    op.execute(sa.text("DROP FUNCTION IF EXISTS fn_prevent_role_removal()"))
    op.execute(sa.text("DROP FUNCTION IF EXISTS fn_validate_membership_role()"))
    op.execute(sa.text("DROP FUNCTION IF EXISTS fn_validate_course_owner()"))

    op.drop_index("ix_audit_events_occurred_at", table_name="audit_events")
    op.drop_index("ix_audit_events_resource", table_name="audit_events")
    op.drop_index("uq_analysis_jobs_active_document_rubric", table_name="analysis_jobs")
    op.drop_index("uq_users_email_lower", table_name="users")

    op.drop_table("audit_events")
    op.drop_table("analysis_jobs")
    op.drop_table("document_versions")
    op.drop_table("submissions")
    op.drop_table("assignment_requirements")
    op.drop_table("assignments")
    op.drop_table("template_versions")
    op.drop_table("criterion_versions")
    op.drop_table("rubric_versions")
    op.drop_table("memberships")
    op.drop_table("courses")
    op.drop_table("users")

    _drop_enum_types()
