from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import (
    AliasChoices,
    BaseModel,
    ConfigDict,
    Field,
    SecretStr,
    field_validator,
)

from app.models.enums import (
    LLMCatalogStatus,
    LLMCredentialSource,
    LLMProtocol,
    LLMProvider,
    LLMRouteState,
    LLMTask,
)


class LLMProviderUpdateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    enabled: bool
    credential_source: LLMCredentialSource = LLMCredentialSource.NONE
    environment_key_name: str | None = Field(default=None, max_length=64)
    credential_key: SecretStr | None = Field(default=None, max_length=4096, repr=False)
    data_policy_approved: bool = False

    @field_validator("credential_key")
    @classmethod
    def validate_key(cls, value: SecretStr | None) -> SecretStr | None:
        if value is not None:
            raw = value.get_secret_value()
            if not raw or any(ord(c) < 32 or ord(c) == 127 for c in raw):
                raise ValueError("credential key is invalid")
        return value


class LLMProviderResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: uuid.UUID
    provider: LLMProvider
    display_name: str
    docs_url: str
    supported_environment_keys: tuple[str, ...]
    supported_protocols: tuple[LLMProtocol, ...]
    enabled: bool
    data_policy_approved: bool
    credential_source: LLMCredentialSource
    environment_key_name: str | None
    masked_hint: str | None
    configured: bool
    stored_credentials_available: bool
    credential_revision: int
    revision: int
    catalog_status: LLMCatalogStatus
    catalog_checked_at: datetime | None
    catalog_latency_ms: int | None
    catalog_error_code: str | None


class LLMProviderListResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    items: list[LLMProviderResponse]


class LLMCatalogTestResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    provider: LLMProvider
    status: LLMCatalogStatus
    model_ids: list[str] = Field(default_factory=list, max_length=100)
    latency_ms: int | None
    credential_revision: int
    catalog_checked_at: datetime


class LLMRouteUpdateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    provider: LLMProvider
    model_id: str | None = Field(default=None, max_length=255)
    protocol: LLMProtocol
    region: str | None = Field(default=None, max_length=64)
    geographic_profile: str | None = Field(default=None, max_length=32)
    max_tokens: int = Field(default=512, ge=1, le=1024)
    call_budget: int = Field(default=32, ge=1, le=256)
    quality_approved: bool = False


class LLMRouteResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: uuid.UUID
    task: LLMTask
    state: LLMRouteState
    active: bool
    provider: LLMProvider
    protocol: LLMProtocol
    model_id: str | None
    region: str | None
    geographic_profile: str | None
    max_tokens: int
    call_budget: int
    quality_approved: bool
    quality_not_approved: bool
    provider_credential_revision: int
    revision: int
    ready: bool
    blockers: list[str]


class LLMFeeAcknowledgement(BaseModel):
    model_config = ConfigDict(extra="forbid")
    acknowledge_provider_fees: bool = Field(
        validation_alias=AliasChoices("acknowledge_provider_fees", "fee_acknowledged")
    )


class LLMRouteActivationRequest(LLMFeeAcknowledgement):
    pass
