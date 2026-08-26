"""Create the domain schema and database invariants."""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

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
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "revision", sa.Integer(), server_default=sa.text("1"), nullable=False
        ),
        sa.Column("email", sa.String(length=320), nullable=False),
        sa.Column("display_name", sa.String(length=255), nullable=False),
        sa.Column("password_hash", sa.String(length=255), nullable=False),
        sa.Column("roles", postgresql.ARRAY(user_role), nullable=False),
        sa.Column("status", user_status, nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_users"),
        sa.CheckConstraint(
            "cardinality(roles) > 0 AND array_position(roles, NULL::user_role) IS NULL",
            name="ck_users_roles_not_empty",
        ),
        sa.CheckConstraint(
            "length(btrim(email)) > 0 AND email !~ '^[[:space:]]*$'",
            name="ck_users_email_not_blank",
        ),
        sa.CheckConstraint(
            "length(btrim(display_name)) > 0 "
            "AND display_name !~ '^[[:space:]]*$'",
            name="ck_users_display_name_not_blank",
        ),
        sa.CheckConstraint(
            "length(btrim(password_hash)) > 0 "
            "AND password_hash !~ '^[[:space:]]*$'",
            name="ck_users_password_hash_not_blank",
        ),
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
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "revision", sa.Integer(), server_default=sa.text("1"), nullable=False
        ),
        sa.Column("code", sa.String(length=64), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("term", sa.String(length=128), nullable=False),
        sa.Column("owner_teacher_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_courses"),
        sa.UniqueConstraint("code", name="uq_courses_code"),
        sa.CheckConstraint(
            "length(btrim(code)) > 0 AND code !~ '^[[:space:]]*$'",
            name="ck_courses_code_not_blank",
        ),
        sa.CheckConstraint(
            "length(btrim(name)) > 0 AND name !~ '^[[:space:]]*$'",
            name="ck_courses_name_not_blank",
        ),
        sa.CheckConstraint(
            "length(btrim(term)) > 0 AND term !~ '^[[:space:]]*$'",
            name="ck_courses_term_not_blank",
        ),
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
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("course_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("role", membership_role, nullable=False),
        sa.Column("status", membership_status, nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_memberships"),
        sa.UniqueConstraint(
            "course_id", "user_id", "role", name="uq_memberships_course_user_role"
        ),
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
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "revision", sa.Integer(), server_default=sa.text("1"), nullable=False
        ),
        sa.Column("rubric_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("version_number", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("status", rubric_status, nullable=False),
        sa.Column(
            "calculation_method",
            sa.String(length=64),
            server_default=sa.text("'WEIGHTED_SUM'"),
            nullable=False,
        ),
        sa.Column(
            "total_weight",
            sa.Numeric(precision=6, scale=2),
            server_default=sa.text("0.00"),
            nullable=False,
        ),
        sa.Column("owner_user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("created_by_user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("source_version_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id", name="pk_rubric_versions"),
        sa.UniqueConstraint(
            "rubric_id", "version_number", name="uq_rubric_versions_rubric_version"
        ),
        sa.CheckConstraint(
            "length(btrim(name)) > 0 AND name !~ '^[[:space:]]*$'",
            name="ck_rubric_versions_name_not_blank",
        ),
        sa.CheckConstraint(
            "length(btrim(calculation_method)) > 0 "
            "AND calculation_method !~ '^[[:space:]]*$'",
            name="ck_rubric_versions_calculation_method_not_blank",
        ),
        sa.CheckConstraint(
            "version_number > 0", name="ck_rubric_versions_version_number_positive"
        ),
        sa.CheckConstraint(
            "total_weight >= 0.00 AND total_weight <= 100.00",
            name="ck_rubric_versions_total_weight_range",
        ),
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
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "revision", sa.Integer(), server_default=sa.text("1"), nullable=False
        ),
        sa.Column("criterion_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("rubric_version_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("code", sa.String(length=64), nullable=False),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("scope", sa.String(length=255), nullable=True),
        sa.Column("weight", sa.Numeric(precision=6, scale=2), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column(
            "is_enabled", sa.Boolean(), server_default=sa.text("true"), nullable=False
        ),
        sa.Column("evaluation_method", sa.String(length=64), nullable=False),
        sa.Column(
            "levels",
            postgresql.JSONB(),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "evaluator_config",
            postgresql.JSONB(),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "evidence_requirements",
            postgresql.JSONB(),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name="pk_criterion_versions"),
        sa.UniqueConstraint(
            "rubric_version_id",
            "criterion_id",
            name="uq_criterion_versions_rubric_version_criterion",
        ),
        sa.UniqueConstraint(
            "rubric_version_id",
            "code",
            name="uq_criterion_versions_rubric_version_code",
        ),
        sa.UniqueConstraint(
            "rubric_version_id",
            "position",
            name="uq_criterion_versions_rubric_version_position",
        ),
        sa.CheckConstraint(
            "length(btrim(code)) > 0 AND code !~ '^[[:space:]]*$'",
            name="ck_criterion_versions_code_not_blank",
        ),
        sa.CheckConstraint(
            "length(btrim(title)) > 0 AND title !~ '^[[:space:]]*$'",
            name="ck_criterion_versions_title_not_blank",
        ),
        sa.CheckConstraint(
            "length(btrim(description)) > 0 "
            "AND description !~ '^[[:space:]]*$'",
            name="ck_criterion_versions_description_not_blank",
        ),
        sa.CheckConstraint(
            "length(btrim(evaluation_method)) > 0 "
            "AND evaluation_method !~ '^[[:space:]]*$'",
            name="ck_criterion_versions_evaluation_method_not_blank",
        ),
        sa.CheckConstraint(
            "weight >= 0.00 AND weight <= 100.00",
            name="ck_criterion_versions_weight_range",
        ),
        sa.CheckConstraint(
            "position > 0", name="ck_criterion_versions_position_positive"
        ),
        sa.CheckConstraint(
            "revision > 0", name="ck_criterion_versions_revision_positive"
        ),
        sa.CheckConstraint(
            "jsonb_typeof(levels) = 'array'",
            name="ck_criterion_versions_levels_is_array",
        ),
        sa.CheckConstraint(
            "jsonb_typeof(evaluator_config) = 'object'",
            name="ck_criterion_versions_evaluator_config_is_object",
        ),
        sa.CheckConstraint(
            "jsonb_typeof(evidence_requirements) = 'object'",
            name="ck_criterion_versions_evidence_requirements_is_object",
        ),
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
        sa.Column(
            "structure",
            postgresql.JSONB(),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column("storage_key", sa.String(length=1024), nullable=True),
        sa.Column("sha256", sa.String(length=64), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name="pk_template_versions"),
        sa.UniqueConstraint(
            "template_id",
            "version_number",
            name="uq_template_versions_template_version",
        ),
        sa.CheckConstraint(
            "length(btrim(name)) > 0 AND name !~ '^[[:space:]]*$'",
            name="ck_template_versions_name_not_blank",
        ),
        sa.CheckConstraint(
            "version_number > 0", name="ck_template_versions_version_number_positive"
        ),
        sa.CheckConstraint(
            "jsonb_typeof(structure) = 'object'",
            name="ck_template_versions_structure_is_object",
        ),
        sa.CheckConstraint(
            "sha256 IS NULL OR sha256 ~ '^[0-9a-f]{64}$'",
            name="ck_template_versions_sha256_format",
        ),
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
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "revision", sa.Integer(), server_default=sa.text("1"), nullable=False
        ),
        sa.Column("course_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "created_by_teacher_id", postgresql.UUID(as_uuid=True), nullable=False
        ),
        sa.Column("rubric_version_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("due_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "first_submission_at", sa.DateTime(timezone=True), nullable=True
        ),
        sa.Column(
            "max_submissions", sa.Integer(), server_default=sa.text("3"), nullable=False
        ),
        sa.Column("status", assignment_status, nullable=False),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("closed_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id", name="pk_assignments"),
        sa.CheckConstraint(
            "max_submissions >= 1 AND max_submissions <= 5",
            name="ck_assignments_max_submissions",
        ),
        sa.CheckConstraint(
            "(status = 'DRAFT' AND published_at IS NULL AND closed_at IS NULL) OR "
            "(status = 'OPEN' AND published_at IS NOT NULL AND closed_at IS NULL) OR "
            "(status IN ('CLOSED', 'ARCHIVED') AND published_at IS NOT NULL "
            "AND closed_at IS NOT NULL)",
            name="ck_assignments_publication_state",
        ),
        sa.CheckConstraint("revision > 0", name="ck_assignments_revision_positive"),
        sa.CheckConstraint(
            "length(btrim(title)) > 0 AND title !~ '^[[:space:]]*$'",
            name="ck_assignments_title_not_blank",
        ),
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
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("assignment_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("kind", sa.String(length=32), nullable=False),
        sa.Column("label", sa.String(length=255), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column(
            "is_required", sa.Boolean(), server_default=sa.text("true"), nullable=False
        ),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("max_file_size_bytes", sa.BigInteger(), nullable=True),
        sa.Column("max_page_count", sa.Integer(), nullable=True),
        sa.Column(
            "text_layer_required",
            sa.Boolean(),
            server_default=sa.text("true"),
            nullable=False,
        ),
        sa.Column("template_version_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.PrimaryKeyConstraint("id", name="pk_assignment_requirements"),
        sa.UniqueConstraint(
            "assignment_id", "position", name="uq_assignment_requirements_position"
        ),
        sa.CheckConstraint(
            "position > 0", name="ck_assignment_requirements_position_positive"
        ),
        sa.CheckConstraint(
            "max_file_size_bytes IS NULL OR max_file_size_bytes > 0",
            name="ck_assignment_requirements_max_file_size_bytes_positive",
        ),
        sa.CheckConstraint(
            "max_page_count IS NULL OR max_page_count > 0",
            name="ck_assignment_requirements_max_page_count_positive",
        ),
        sa.CheckConstraint(
            "length(btrim(kind)) > 0 AND kind !~ '^[[:space:]]*$'",
            name="ck_assignment_requirements_kind_not_blank",
        ),
        sa.CheckConstraint(
            "length(btrim(label)) > 0 AND label !~ '^[[:space:]]*$'",
            name="ck_assignment_requirements_label_not_blank",
        ),
        sa.ForeignKeyConstraint(
            ["assignment_id"],
            ["assignments.id"],
            name="fk_assignment_requirements_assignment_id_assignments",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["template_version_id"],
            ["template_versions.id"],
            name="fk_assignment_requirements_template_version_template_versions",
            ondelete="RESTRICT",
        ),
    )

    op.create_table(
        "submissions",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("assignment_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("student_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_submissions"),
        sa.UniqueConstraint(
            "assignment_id", "student_id", name="uq_submissions_assignment_student"
        ),
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
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("submission_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("version_number", sa.Integer(), nullable=False),
        sa.Column("previous_version_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("storage_key", sa.String(length=1024), nullable=False),
        sa.Column("original_filename", sa.String(length=255), nullable=False),
        sa.Column("content_type", sa.String(length=128), nullable=False),
        sa.Column("size_bytes", sa.BigInteger(), nullable=False),
        sa.Column("page_count", sa.Integer(), nullable=True),
        sa.Column("sha256", sa.String(length=64), nullable=False),
        sa.Column("status", document_status, nullable=False),
        sa.Column("failure_code", sa.String(length=64), nullable=True),
        sa.Column("failure_detail", sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint("id", name="pk_document_versions"),
        sa.UniqueConstraint(
            "submission_id",
            "version_number",
            name="uq_document_versions_submission_version",
        ),
        sa.UniqueConstraint(
            "submission_id", "sha256", name="uq_document_versions_submission_sha256"
        ),
        sa.CheckConstraint(
            "version_number > 0", name="ck_document_versions_version_number_positive"
        ),
        sa.CheckConstraint(
            "size_bytes > 0", name="ck_document_versions_size_bytes_positive"
        ),
        sa.CheckConstraint(
            "page_count IS NULL OR page_count > 0",
            name="ck_document_versions_page_count_positive",
        ),
        sa.CheckConstraint(
            "sha256 ~ '^[0-9a-f]{64}$'", name="ck_document_versions_sha256_format"
        ),
        sa.CheckConstraint(
            "length(btrim(storage_key)) > 0 "
            "AND storage_key !~ '^[[:space:]]*$'",
            name="ck_document_versions_storage_key_not_blank",
        ),
        sa.CheckConstraint(
            "length(btrim(original_filename)) > 0 "
            "AND original_filename !~ '^[[:space:]]*$'",
            name="ck_document_versions_original_filename_not_blank",
        ),
        sa.CheckConstraint(
            "length(btrim(content_type)) > 0 "
            "AND content_type !~ '^[[:space:]]*$'",
            name="ck_document_versions_content_type_not_blank",
        ),
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
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("document_version_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("rubric_version_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("status", analysis_job_status, nullable=False),
        sa.Column(
            "attempt_count", sa.Integer(), server_default=sa.text("0"), nullable=False
        ),
        sa.Column(
            "max_attempts", sa.Integer(), server_default=sa.text("3"), nullable=False
        ),
        sa.Column(
            "snapshot",
            postgresql.JSONB(),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "queued_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("error_code", sa.String(length=64), nullable=True),
        sa.Column("error_detail", sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint("id", name="pk_analysis_jobs"),
        sa.CheckConstraint(
            "max_attempts > 0 AND attempt_count >= 0 AND attempt_count <= max_attempts",
            name="ck_analysis_jobs_attempts",
        ),
        sa.CheckConstraint(
            "jsonb_typeof(snapshot) = 'object'", name="ck_analysis_jobs_snapshot_object"
        ),
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
        sa.Column(
            "occurred_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name="pk_audit_events"),
        sa.CheckConstraint(
            "(actor_type = 'USER' AND actor_user_id IS NOT NULL) OR "
            "(actor_type = 'SYSTEM' AND actor_user_id IS NULL)",
            name="ck_audit_events_actor",
        ),
        sa.CheckConstraint(
            "before IS NOT NULL OR after IS NOT NULL", name="ck_audit_events_snapshots"
        ),
        sa.CheckConstraint(
            "before IS NULL OR jsonb_typeof(before) = 'object'",
            name="ck_audit_events_before_object",
        ),
        sa.CheckConstraint(
            "after IS NULL OR jsonb_typeof(after) = 'object'",
            name="ck_audit_events_after_object",
        ),
        sa.CheckConstraint(
            "reason !~ '^[[:space:]]*$'", name="ck_audit_events_reason_not_blank"
        ),
        sa.CheckConstraint(
            "length(btrim(resource_type)) > 0 "
            "AND resource_type !~ '^[[:space:]]*$'",
            name="ck_audit_events_resource_type_not_blank",
        ),
        sa.CheckConstraint(
            "length(btrim(action)) > 0 AND action !~ '^[[:space:]]*$'",
            name="ck_audit_events_action_not_blank",
        ),
        sa.ForeignKeyConstraint(
            ["actor_user_id"],
            ["users.id"],
            name="fk_audit_events_actor_user_id_users",
            ondelete="RESTRICT",
        ),
    )
    op.create_index(
        "ix_audit_events_resource", "audit_events", ["resource_type", "resource_id"]
    )
    op.create_index("ix_audit_events_occurred_at", "audit_events", ["occurred_at"])
    # Canonical per-statement lock order: rubric/user keys precede assignment;
    # when both are needed, user precedes assignment. Future multi-statement
    # services must pre-acquire locks in this order.
    op.execute(sa.text("""
            CREATE FUNCTION fn_domain_lock(lock_scope text, entity_id uuid)
            RETURNS void
            LANGUAGE plpgsql
            AS $$
            BEGIN
                PERFORM pg_advisory_xact_lock(
                    hashtextextended(lock_scope || ':' || entity_id::text, 0)
                );
            END;
            $$;
            """))

    op.execute(sa.text("""
            CREATE FUNCTION fn_validate_course_owner()
            RETURNS trigger
            LANGUAGE plpgsql
            AS $$
            BEGIN
                PERFORM fn_domain_lock('user', NEW.owner_teacher_id);
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
            """))
    op.execute(sa.text("""
            CREATE TRIGGER trg_validate_course_owner
            BEFORE INSERT OR UPDATE OF owner_teacher_id ON courses
            FOR EACH ROW EXECUTE FUNCTION fn_validate_course_owner();
            """))

    op.execute(sa.text("""
            CREATE FUNCTION fn_validate_membership_role()
            RETURNS trigger
            LANGUAGE plpgsql
            AS $$
            BEGIN
                PERFORM fn_domain_lock('user', NEW.user_id);
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
            """))
    op.execute(sa.text("""
            CREATE TRIGGER trg_validate_membership_role
            BEFORE INSERT OR UPDATE OF user_id, role ON memberships
            FOR EACH ROW EXECUTE FUNCTION fn_validate_membership_role();
            """))

    op.execute(sa.text("""
            CREATE FUNCTION fn_prevent_role_removal()
            RETURNS trigger
            LANGUAGE plpgsql
            AS $$
            BEGIN
                PERFORM fn_domain_lock('user', NEW.id);
                IF (
                    EXISTS (
                        SELECT 1 FROM courses AS c WHERE c.owner_teacher_id = OLD.id
                    )
                    AND NOT EXISTS (
                        SELECT 1
                        FROM unnest(NEW.roles) AS r
                        WHERE r::text = 'TEACHER'
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
            """))
    op.execute(sa.text("""
            CREATE TRIGGER trg_prevent_role_removal
            BEFORE UPDATE OF roles ON users
            FOR EACH ROW EXECUTE FUNCTION fn_prevent_role_removal();
            """))

    op.execute(sa.text("""
            CREATE FUNCTION fn_validate_submission_student()
            RETURNS trigger
            LANGUAGE plpgsql
            AS $$
            BEGIN
                PERFORM fn_domain_lock('user', NEW.student_id);
                PERFORM fn_domain_lock('assignment', NEW.assignment_id);
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
                UPDATE assignments
                SET first_submission_at = COALESCE(
                    first_submission_at, CURRENT_TIMESTAMP
                )
                WHERE id = NEW.assignment_id;
                RETURN NEW;
            END;
            $$;
            """))
    op.execute(sa.text("""
            CREATE TRIGGER trg_validate_submission_student
            BEFORE INSERT OR UPDATE OF assignment_id, student_id ON submissions
            FOR EACH ROW EXECUTE FUNCTION fn_validate_submission_student();
            """))
    op.execute(sa.text("""
            CREATE FUNCTION fn_lock_assignment_rubric_insert()
            RETURNS trigger
            LANGUAGE plpgsql
            AS $$
            BEGIN
                PERFORM fn_domain_lock('rubric', NEW.rubric_version_id);
                RETURN NEW;
            END;
            $$;
            """))
    op.execute(sa.text("""
            CREATE TRIGGER trg_lock_assignment_rubric_insert
            BEFORE INSERT ON assignments
            FOR EACH ROW EXECUTE FUNCTION fn_lock_assignment_rubric_insert();
            """))
    op.execute(sa.text("""
            CREATE FUNCTION fn_protect_assignment_submission_freeze()
            RETURNS trigger
            LANGUAGE plpgsql
            AS $$
            BEGIN
                IF OLD.first_submission_at IS NOT NULL
                   AND NEW.first_submission_at IS DISTINCT FROM OLD.first_submission_at THEN
                    RAISE EXCEPTION USING
                        ERRCODE = '23514',
                        MESSAGE = 'assignment submission freeze is immutable';
                END IF;
                RETURN NEW;
            END;
            $$;
            """))
    op.execute(sa.text("""
            CREATE TRIGGER trg_protect_assignment_submission_freeze
            BEFORE UPDATE OF first_submission_at ON assignments
            FOR EACH ROW EXECUTE FUNCTION fn_protect_assignment_submission_freeze();
            """))

    op.execute(sa.text("""
            CREATE FUNCTION fn_immut_rubric_version()
            RETURNS trigger
            LANGUAGE plpgsql
            AS $$
            DECLARE
                assignment_row record;
            BEGIN
                PERFORM fn_domain_lock('rubric', OLD.id);
                FOR assignment_row IN
                    SELECT a.id
                    FROM assignments AS a
                    WHERE a.rubric_version_id = OLD.id
                    ORDER BY a.id
                LOOP
                    PERFORM fn_domain_lock('assignment', assignment_row.id);
                    IF EXISTS (
                        SELECT 1
                        FROM assignments AS a
                        WHERE a.id = assignment_row.id
                          AND a.first_submission_at IS NOT NULL
                    ) THEN
                        RAISE EXCEPTION USING
                            ERRCODE = '23514',
                            MESSAGE = 'rubric version is immutable after first submission';
                    END IF;
                END LOOP;
                IF TG_OP = 'DELETE' THEN
                    RETURN OLD;
                END IF;
                RETURN NEW;
            END;
            $$;
            """))
    op.execute(sa.text("""
            CREATE TRIGGER trg_immut_rubric_version
            BEFORE UPDATE OR DELETE ON rubric_versions
            FOR EACH ROW EXECUTE FUNCTION fn_immut_rubric_version();
            """))
    op.execute(sa.text("""
            CREATE FUNCTION fn_assert_criterion_parent_mutable(parent_id uuid)
            RETURNS void
            LANGUAGE plpgsql
            AS $$
            DECLARE
                assignment_row record;
            BEGIN
                PERFORM fn_domain_lock('rubric', parent_id);
                FOR assignment_row IN
                    SELECT a.id
                    FROM assignments AS a
                    WHERE a.rubric_version_id = parent_id
                    ORDER BY a.id
                LOOP
                    PERFORM fn_domain_lock('assignment', assignment_row.id);
                    IF EXISTS (
                        SELECT 1
                        FROM assignments AS a
                        WHERE a.id = assignment_row.id
                          AND a.first_submission_at IS NOT NULL
                    ) THEN
                        RAISE EXCEPTION USING
                            ERRCODE = '23514',
                            MESSAGE = 'criterion version is immutable after first submission';
                    END IF;
                END LOOP;
            END;
            $$;
            """))

    op.execute(sa.text("""
            CREATE FUNCTION fn_immut_criterion_version()
            RETURNS trigger
            LANGUAGE plpgsql
            AS $$
            DECLARE
                parent_row record;
            BEGIN
                IF TG_OP = 'INSERT' THEN
                    PERFORM fn_assert_criterion_parent_mutable(NEW.rubric_version_id);
                ELSIF TG_OP = 'DELETE' THEN
                    PERFORM fn_assert_criterion_parent_mutable(OLD.rubric_version_id);
                ELSE
                    FOR parent_row IN
                        SELECT parent_id
                        FROM (
                            SELECT OLD.rubric_version_id AS parent_id
                            UNION
                            SELECT NEW.rubric_version_id AS parent_id
                        ) AS parent_ids
                        ORDER BY parent_id
                    LOOP
                        PERFORM fn_assert_criterion_parent_mutable(parent_row.parent_id);
                    END LOOP;
                END IF;
                IF TG_OP = 'DELETE' THEN
                    RETURN OLD;
                END IF;
                RETURN NEW;
            END;
            $$;
            """))
    op.execute(sa.text("""
            CREATE TRIGGER trg_immut_criterion_version
            BEFORE INSERT OR UPDATE OR DELETE ON criterion_versions
            FOR EACH ROW EXECUTE FUNCTION fn_immut_criterion_version();
            """))

    op.execute(sa.text("""
            CREATE FUNCTION fn_immut_assignment_rubric()
            RETURNS trigger
            LANGUAGE plpgsql
            AS $$
            BEGIN
                PERFORM fn_domain_lock('rubric', NEW.rubric_version_id);
                PERFORM fn_domain_lock('assignment', OLD.id);
                IF NEW.rubric_version_id IS DISTINCT FROM OLD.rubric_version_id
                   AND OLD.first_submission_at IS NOT NULL THEN
                    RAISE EXCEPTION USING
                        ERRCODE = '23514',
                        MESSAGE = 'assignment rubric is immutable after first submission';
                END IF;
                RETURN NEW;
            END;
            $$;
            """))
    op.execute(sa.text("""
            CREATE TRIGGER trg_immut_assignment_rubric
            BEFORE UPDATE OF rubric_version_id ON assignments
            FOR EACH ROW EXECUTE FUNCTION fn_immut_assignment_rubric();
            """))

    op.execute(sa.text("""
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
            """))
    op.execute(sa.text("""
            CREATE TRIGGER trg_audit_events_append_only
            BEFORE UPDATE OR DELETE ON audit_events
            FOR EACH ROW EXECUTE FUNCTION fn_audit_events_append_only();
            """))


def downgrade() -> None:
    op.execute(
        sa.text("DROP TRIGGER IF EXISTS trg_audit_events_append_only ON audit_events")
    )
    op.execute(
        sa.text(
            "DROP TRIGGER IF EXISTS trg_lock_assignment_rubric_insert ON assignments"
        )
    )
    op.execute(
        sa.text(
            "DROP TRIGGER IF EXISTS trg_protect_assignment_submission_freeze ON assignments"
        )
    )
    op.execute(
        sa.text("DROP TRIGGER IF EXISTS trg_immut_assignment_rubric ON assignments")
    )
    op.execute(
        sa.text(
            "DROP TRIGGER IF EXISTS trg_immut_criterion_version ON criterion_versions"
        )
    )
    op.execute(
        sa.text("DROP TRIGGER IF EXISTS trg_immut_rubric_version ON rubric_versions")
    )
    op.execute(
        sa.text("DROP TRIGGER IF EXISTS trg_validate_submission_student ON submissions")
    )
    op.execute(sa.text("DROP TRIGGER IF EXISTS trg_prevent_role_removal ON users"))
    op.execute(
        sa.text("DROP TRIGGER IF EXISTS trg_validate_membership_role ON memberships")
    )
    op.execute(sa.text("DROP TRIGGER IF EXISTS trg_validate_course_owner ON courses"))

    op.execute(sa.text("DROP FUNCTION IF EXISTS fn_audit_events_append_only()"))
    op.execute(sa.text("DROP FUNCTION IF EXISTS fn_immut_assignment_rubric()"))
    op.execute(sa.text("DROP FUNCTION IF EXISTS fn_lock_assignment_rubric_insert()"))
    op.execute(sa.text("DROP FUNCTION IF EXISTS fn_protect_assignment_submission_freeze()"))
    op.execute(sa.text("DROP FUNCTION IF EXISTS fn_assert_criterion_parent_mutable(uuid)"))
    op.execute(sa.text("DROP FUNCTION IF EXISTS fn_immut_criterion_version()"))
    op.execute(sa.text("DROP FUNCTION IF EXISTS fn_immut_rubric_version()"))
    op.execute(sa.text("DROP FUNCTION IF EXISTS fn_validate_submission_student()"))
    op.execute(sa.text("DROP FUNCTION IF EXISTS fn_prevent_role_removal()"))
    op.execute(sa.text("DROP FUNCTION IF EXISTS fn_validate_membership_role()"))
    op.execute(sa.text("DROP FUNCTION IF EXISTS fn_validate_course_owner()"))
    op.execute(sa.text("DROP FUNCTION IF EXISTS fn_domain_lock(text, uuid)"))

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
