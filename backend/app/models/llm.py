from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.models.enums import (
    LLMCatalogStatus,
    LLMCredentialSource,
    LLMProtocol,
    LLMProvider,
    LLMRouteState,
    LLMTask,
    pg_enum,
)
from app.models.mixins import RevisionMixin, TimestampMixin, UUIDPrimaryKeyMixin

if TYPE_CHECKING:
    pass


class LLMProviderConfig(UUIDPrimaryKeyMixin, TimestampMixin, RevisionMixin, Base):
    __tablename__ = "llm_provider_configs"
    __table_args__ = (
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
    )

    provider: Mapped[LLMProvider] = mapped_column(
        pg_enum(LLMProvider, name="llm_provider"), nullable=False
    )
    enabled: Mapped[bool] = mapped_column(
        sa.Boolean, nullable=False, default=False, server_default=sa.false()
    )
    data_policy_approved: Mapped[bool] = mapped_column(
        sa.Boolean, nullable=False, default=False, server_default=sa.false()
    )
    data_policy_approved_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        sa.ForeignKey(
            "users.id",
            ondelete="RESTRICT",
            name="fk_llm_provider_configs_policy_user_users",
        ),
        nullable=True,
    )
    data_policy_approved_at: Mapped[datetime | None] = mapped_column(
        sa.DateTime(timezone=True), nullable=True
    )
    credential_source: Mapped[LLMCredentialSource] = mapped_column(
        pg_enum(LLMCredentialSource, name="llm_credential_source"),
        nullable=False,
        default=LLMCredentialSource.NONE,
        server_default=sa.text("'NONE'"),
    )
    environment_key_name: Mapped[str | None] = mapped_column(
        sa.String(64), nullable=True
    )
    ciphertext: Mapped[bytes | None] = mapped_column(sa.LargeBinary, nullable=True)
    encryption_key_id: Mapped[str | None] = mapped_column(sa.String(128), nullable=True)
    masked_hint: Mapped[str | None] = mapped_column(sa.String(32), nullable=True)
    credential_fingerprint: Mapped[str | None] = mapped_column(
        sa.String(64), nullable=True
    )
    credential_revision: Mapped[int] = mapped_column(
        sa.Integer, nullable=False, default=1, server_default=sa.text("1")
    )
    catalog_status: Mapped[LLMCatalogStatus] = mapped_column(
        pg_enum(LLMCatalogStatus, name="llm_catalog_status"),
        nullable=False,
        default=LLMCatalogStatus.UNTESTED,
        server_default=sa.text("'UNTESTED'"),
    )
    catalog_checked_at: Mapped[datetime | None] = mapped_column(
        sa.DateTime(timezone=True), nullable=True
    )
    catalog_latency_ms: Mapped[int | None] = mapped_column(sa.Integer, nullable=True)
    catalog_error_code: Mapped[str | None] = mapped_column(sa.String(64), nullable=True)
    catalog_verified_credential_revision: Mapped[int | None] = mapped_column(
        sa.Integer, nullable=True
    )

    routes: Mapped[list[LLMRoute]] = relationship(
        "LLMRoute",
        back_populates="provider_config",
        foreign_keys="LLMRoute.provider_config_id",
    )


class LLMRoute(UUIDPrimaryKeyMixin, TimestampMixin, RevisionMixin, Base):
    __tablename__ = "llm_routes"
    __table_args__ = (
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
    )

    task: Mapped[LLMTask] = mapped_column(
        pg_enum(LLMTask, name="llm_task"), nullable=False
    )
    provider_config_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        sa.ForeignKey(
            "llm_provider_configs.id",
            ondelete="RESTRICT",
            name="fk_llm_routes_provider_config_id_llm_provider_configs",
        ),
        nullable=False,
    )
    state: Mapped[LLMRouteState] = mapped_column(
        pg_enum(LLMRouteState, name="llm_route_state"),
        nullable=False,
        default=LLMRouteState.DRAFT,
        server_default=sa.text("'DRAFT'"),
    )
    model_id: Mapped[str | None] = mapped_column(sa.String(255), nullable=True)
    protocol: Mapped[LLMProtocol] = mapped_column(
        pg_enum(LLMProtocol, name="llm_protocol"),
        nullable=False,
        default=LLMProtocol.BEDROCK_CONVERSE,
        server_default=sa.text("'BEDROCK_CONVERSE'"),
    )
    region: Mapped[str | None] = mapped_column(sa.String(64), nullable=True)
    geographic_profile: Mapped[str | None] = mapped_column(sa.String(32), nullable=True)
    max_tokens: Mapped[int] = mapped_column(
        sa.Integer, nullable=False, default=512, server_default=sa.text("512")
    )
    call_budget: Mapped[int] = mapped_column(
        sa.Integer, nullable=False, default=32, server_default=sa.text("32")
    )
    quality_approved: Mapped[bool] = mapped_column(
        sa.Boolean, nullable=False, default=False, server_default=sa.false()
    )
    quality_approved_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        sa.ForeignKey(
            "users.id", ondelete="RESTRICT", name="fk_llm_routes_quality_user_users"
        ),
        nullable=True,
    )
    quality_approved_at: Mapped[datetime | None] = mapped_column(
        sa.DateTime(timezone=True), nullable=True
    )
    active: Mapped[bool] = mapped_column(
        sa.Boolean, nullable=False, default=False, server_default=sa.false()
    )
    activated_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        sa.ForeignKey(
            "users.id", ondelete="RESTRICT", name="fk_llm_routes_activated_user_users"
        ),
        nullable=True,
    )
    activated_at: Mapped[datetime | None] = mapped_column(
        sa.DateTime(timezone=True), nullable=True
    )
    provider_credential_revision: Mapped[int] = mapped_column(
        sa.Integer, nullable=False, default=1, server_default=sa.text("1")
    )

    provider_config: Mapped[LLMProviderConfig] = relationship(
        "LLMProviderConfig", back_populates="routes", foreign_keys=[provider_config_id]
    )
