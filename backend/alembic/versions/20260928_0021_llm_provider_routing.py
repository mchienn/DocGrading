"""Add Admin-managed LLM providers and semantic route."""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "20260928_0021"
down_revision: str | None = "20260927_0020"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_PROVIDER_IDS = {
    "OPENAI": "00000000-0000-0000-0000-000000000001",
    "ANTHROPIC": "00000000-0000-0000-0000-000000000002",
    "GEMINI": "00000000-0000-0000-0000-000000000003",
    "DEEPSEEK": "00000000-0000-0000-0000-000000000004",
    "OPENCODE_ZEN": "00000000-0000-0000-0000-000000000005",
    "BEDROCK": "00000000-0000-0000-0000-000000000006",
}
_ROUTE_ID = "00000000-0000-0000-0000-000000000010"


def _enum(name: str, values: list[str]) -> postgresql.ENUM:
    value = postgresql.ENUM(*values, name=name, create_type=False)
    value.create(op.get_bind(), checkfirst=True)
    return value


def upgrade() -> None:
    op.execute(sa.text("SET search_path TO public"))
    provider = _enum("llm_provider", list(_PROVIDER_IDS))
    credential_source = _enum(
        "llm_credential_source", ["NONE", "ENVIRONMENT", "STORED"]
    )
    catalog_status = _enum(
        "llm_catalog_status",
        [
            "UNTESTED",
            "CATALOG_VERIFIED",
            "INVALID_CREDENTIAL",
            "RATE_LIMITED",
            "UNAVAILABLE",
            "TIMEOUT",
            "INVALID_RESPONSE",
        ],
    )
    protocol = _enum(
        "llm_protocol",
        [
            "OPENAI_CHAT",
            "OPENAI_RESPONSES",
            "ANTHROPIC_MESSAGES",
            "GEMINI_GENERATE_CONTENT",
            "BEDROCK_CONVERSE",
        ],
    )
    task = _enum("llm_task", ["CITATION_SEMANTIC"])
    state = _enum("llm_route_state", ["DRAFT", "ACTIVE", "DISABLED"])
    uid = postgresql.UUID(as_uuid=True)
    op.create_table(
        "llm_provider_configs",
        sa.Column("id", uid, nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("revision", sa.Integer, server_default="1", nullable=False),
        sa.Column("provider", provider, nullable=False),
        sa.Column("enabled", sa.Boolean, server_default=sa.false(), nullable=False),
        sa.Column(
            "data_policy_approved",
            sa.Boolean,
            server_default=sa.false(),
            nullable=False,
        ),
        sa.Column(
            "data_policy_approved_by_user_id",
            uid,
            sa.ForeignKey(
                "users.id",
                name="fk_llm_provider_configs_policy_user_users",
                ondelete="RESTRICT",
            ),
        ),
        sa.Column("data_policy_approved_at", sa.DateTime(timezone=True)),
        sa.Column(
            "credential_source",
            credential_source,
            server_default="NONE",
            nullable=False,
        ),
        sa.Column("environment_key_name", sa.String(64)),
        sa.Column("ciphertext", sa.LargeBinary),
        sa.Column("encryption_key_id", sa.String(128)),
        sa.Column("masked_hint", sa.String(32)),
        sa.Column("credential_fingerprint", sa.String(64)),
        sa.Column(
            "credential_revision", sa.Integer, server_default="1", nullable=False
        ),
        sa.Column(
            "catalog_status", catalog_status, server_default="UNTESTED", nullable=False
        ),
        sa.Column("catalog_checked_at", sa.DateTime(timezone=True)),
        sa.Column("catalog_latency_ms", sa.Integer),
        sa.Column("catalog_error_code", sa.String(64)),
        sa.Column("catalog_verified_credential_revision", sa.Integer),
        sa.PrimaryKeyConstraint("id", name="pk_llm_provider_configs"),
        sa.UniqueConstraint("provider", name="uq_llm_provider_configs_provider"),
        sa.CheckConstraint(
            "revision > 0", name="ck_llm_provider_configs_revision_positive"
        ),
        sa.CheckConstraint(
            "credential_revision > 0",
            name="ck_llm_provider_configs_credential_revision_positive",
        ),
        sa.CheckConstraint(
            "data_policy_approved = TRUE OR "
            "(data_policy_approved_by_user_id IS NULL "
            "AND data_policy_approved_at IS NULL)",
            name="ck_llm_provider_configs_policy_approval",
        ),
        sa.CheckConstraint(
            "data_policy_approved = FALSE OR "
            "data_policy_approved_by_user_id IS NOT NULL",
            name="ck_llm_provider_configs_policy_actor",
        ),
        sa.CheckConstraint(
            "data_policy_approved = FALSE OR data_policy_approved_at IS NOT NULL",
            name="ck_llm_provider_configs_policy_time",
        ),
        sa.CheckConstraint(
            "credential_source <> 'STORED' OR ciphertext IS NOT NULL",
            name="ck_llm_provider_configs_stored_ciphertext",
        ),
        sa.CheckConstraint(
            "credential_source <> 'STORED' OR encryption_key_id IS NOT NULL",
            name="ck_llm_provider_configs_stored_key_id",
        ),
        schema="public",
    )
    op.create_table(
        "llm_routes",
        sa.Column("id", uid, nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("revision", sa.Integer, server_default="1", nullable=False),
        sa.Column("task", task, nullable=False),
        sa.Column(
            "provider_config_id",
            uid,
            sa.ForeignKey(
                "llm_provider_configs.id",
                name="fk_llm_routes_provider_config_id_llm_provider_configs",
                ondelete="RESTRICT",
            ),
            nullable=False,
        ),
        sa.Column("state", state, server_default="DRAFT", nullable=False),
        sa.Column("model_id", sa.String(255)),
        sa.Column(
            "protocol", protocol, server_default="BEDROCK_CONVERSE", nullable=False
        ),
        sa.Column("region", sa.String(64)),
        sa.Column("geographic_profile", sa.String(32)),
        sa.Column("max_tokens", sa.Integer, server_default="512", nullable=False),
        sa.Column("call_budget", sa.Integer, server_default="32", nullable=False),
        sa.Column(
            "quality_approved", sa.Boolean, server_default=sa.false(), nullable=False
        ),
        sa.Column(
            "quality_approved_by_user_id",
            uid,
            sa.ForeignKey(
                "users.id", name="fk_llm_routes_quality_user_users", ondelete="RESTRICT"
            ),
        ),
        sa.Column("quality_approved_at", sa.DateTime(timezone=True)),
        sa.Column("active", sa.Boolean, server_default=sa.false(), nullable=False),
        sa.Column(
            "activated_by_user_id",
            uid,
            sa.ForeignKey(
                "users.id",
                name="fk_llm_routes_activated_user_users",
                ondelete="RESTRICT",
            ),
        ),
        sa.Column("activated_at", sa.DateTime(timezone=True)),
        sa.Column(
            "provider_credential_revision",
            sa.Integer,
            server_default="1",
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name="pk_llm_routes"),
        sa.UniqueConstraint("task", name="uq_llm_routes_task"),
        sa.CheckConstraint("revision > 0", name="ck_llm_routes_revision_positive"),
        sa.CheckConstraint(
            "max_tokens > 0 AND max_tokens <= 1024", name="ck_llm_routes_max_tokens"
        ),
        sa.CheckConstraint(
            "call_budget > 0 AND call_budget <= 256", name="ck_llm_routes_call_budget"
        ),
        sa.CheckConstraint(
            "quality_approved = FALSE OR quality_approved_by_user_id IS NOT NULL",
            name="ck_llm_routes_quality_actor",
        ),
        sa.CheckConstraint(
            "quality_approved = FALSE OR quality_approved_at IS NOT NULL",
            name="ck_llm_routes_quality_time",
        ),
        sa.CheckConstraint(
            "quality_approved = TRUE OR "
            "(quality_approved_by_user_id IS NULL "
            "AND quality_approved_at IS NULL)",
            name="ck_llm_routes_quality_clear",
        ),
        sa.CheckConstraint(
            "active = FALSE OR activated_by_user_id IS NOT NULL",
            name="ck_llm_routes_active_actor",
        ),
        sa.CheckConstraint(
            "active = FALSE OR activated_at IS NOT NULL",
            name="ck_llm_routes_active_time",
        ),
        sa.CheckConstraint(
            "active = TRUE OR (activated_by_user_id IS NULL AND activated_at IS NULL)",
            name="ck_llm_routes_active_clear",
        ),
        sa.CheckConstraint(
            "(active = TRUE AND state = 'ACTIVE') OR "
            "(active = FALSE AND state <> 'ACTIVE')",
            name="ck_llm_routes_active_state",
        ),
        schema="public",
    )
    rows = [{"id": value, "provider": key} for key, value in _PROVIDER_IDS.items()]
    op.bulk_insert(
        sa.table(
            "llm_provider_configs",
            sa.column("id", uid),
            sa.column("provider", provider),
        ),
        rows,
    )
    op.bulk_insert(
        sa.table(
            "llm_routes",
            sa.column("id", uid),
            sa.column("task", task),
            sa.column("provider_config_id", uid),
        ),
        [
            {
                "id": _ROUTE_ID,
                "task": "CITATION_SEMANTIC",
                "provider_config_id": _PROVIDER_IDS["BEDROCK"],
            }
        ],
    )


def downgrade() -> None:
    op.execute(sa.text("SET search_path TO public"))
    op.execute(
        sa.text(
            "LOCK TABLE public.llm_provider_configs, public.llm_routes "
            "IN ACCESS EXCLUSIVE MODE"
        )
    )
    if op.get_bind().scalar(
        sa.text("SELECT EXISTS (SELECT 1 FROM public.llm_routes WHERE active)")
    ):
        raise RuntimeError("Refusing downgrade: active LLM route would be lost")
    if op.get_bind().scalar(
        sa.text(
            "SELECT EXISTS ("
            "SELECT 1 FROM public.llm_provider_configs "
            "WHERE enabled OR data_policy_approved "
            "OR credential_source <> 'NONE' OR revision <> 1 "
            "OR credential_revision <> 1 OR catalog_status <> 'UNTESTED' "
            "OR ciphertext IS NOT NULL OR encryption_key_id IS NOT NULL "
            "OR masked_hint IS NOT NULL OR credential_fingerprint IS NOT NULL)"
        )
    ):
        raise RuntimeError(
            "Refusing downgrade: LLM provider configuration would be lost"
        )
    if op.get_bind().scalar(
        sa.text(
            "SELECT EXISTS ("
            "SELECT 1 FROM public.llm_routes "
            "WHERE state <> 'DRAFT' OR revision <> 1 "
            "OR model_id IS NOT NULL OR quality_approved "
            "OR region IS NOT NULL OR geographic_profile IS NOT NULL "
            "OR max_tokens <> 512 OR call_budget <> 32)"
        )
    ):
        raise RuntimeError("Refusing downgrade: LLM route data would be lost")
    op.drop_table("llm_routes", schema="public")
    op.drop_table("llm_provider_configs", schema="public")
    for name in (
        "llm_route_state",
        "llm_task",
        "llm_protocol",
        "llm_catalog_status",
        "llm_credential_source",
        "llm_provider",
    ):
        op.execute(sa.text(f"DROP TYPE public.{name}"))
