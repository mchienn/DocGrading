"""Admin LLM provider configuration and bounded catalog checks."""

from __future__ import annotations

import asyncio
import json
import socket
import ssl
import time
import urllib.error
import urllib.request
import uuid
from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any, Protocol
from urllib.parse import urlsplit

import sqlalchemy as sa
from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.schemas_llm import (
    LLMCatalogTestResponse,
    LLMProviderResponse,
    LLMProviderUpdateRequest,
    LLMRouteActivationRequest,
    LLMRouteResponse,
    LLMRouteUpdateRequest,
)
from app.core.config import get_settings
from app.models import LLMProviderConfig, LLMRoute
from app.models.enums import (
    LLMCatalogStatus,
    LLMCredentialSource,
    LLMProvider,
    LLMRouteState,
    LLMTask,
    llm_provider_protocols,
)
from app.services.audit import record_audit
from app.services.llm_credentials import (
    CredentialError,
    credential_fingerprint,
    encrypt_credential,
    parse_keyring,
    resolve_credential,
    resolve_environment_key,
    supported_environment_keys,
)
from app.services.semantic_citation import bedrock_semantic_config_approved

_PROVIDER_INFO: dict[LLMProvider, tuple[str, str]] = {
    LLMProvider.OPENAI: ("OpenAI", "https://platform.openai.com/docs/api-reference"),
    LLMProvider.ANTHROPIC: ("Anthropic Claude", "https://docs.anthropic.com/en/api"),
    LLMProvider.GEMINI: ("Google Gemini", "https://ai.google.dev/gemini-api/docs"),
    LLMProvider.DEEPSEEK: ("DeepSeek", "https://api-docs.deepseek.com/"),
    LLMProvider.OPENCODE_ZEN: ("OpenCode Zen", "https://opencode.ai/docs/zen/"),
    LLMProvider.BEDROCK: ("Amazon Bedrock", "https://docs.aws.amazon.com/bedrock/"),
}

_CATALOG_ENDPOINTS: dict[LLMProvider, str] = {
    LLMProvider.OPENAI: "https://api.openai.com/v1/models",
    LLMProvider.ANTHROPIC: "https://api.anthropic.com/v1/models",
    LLMProvider.GEMINI: "https://generativelanguage.googleapis.com/v1beta/models",
    LLMProvider.DEEPSEEK: "https://api.deepseek.com/models",
    LLMProvider.OPENCODE_ZEN: "https://opencode.ai/inference/v1/models",
}


def _is_timeout_error(exc: BaseException) -> bool:
    if isinstance(exc, (TimeoutError, socket.timeout)):
        return True
    if isinstance(exc, urllib.error.URLError) and isinstance(exc.reason, BaseException):
        return _is_timeout_error(exc.reason)
    return False


class CatalogTransport(Protocol):
    def __call__(
        self, provider: LLMProvider, credential: str | None
    ) -> tuple[int, bytes]: ...


def _transport(provider: LLMProvider, credential: str | None) -> tuple[int, bytes]:
    if provider is LLMProvider.BEDROCK:
        raise RuntimeError("bedrock catalog handled by SDK")
    endpoint = _CATALOG_ENDPOINTS[provider]
    headers = {
        "Accept": "application/json",
        "Accept-Encoding": "identity",
        # Cloudflare-fronted providers (OpenCode Zen) answer urllib's default
        # "Python-urllib" agent with 403 error 1010, misread as a bad credential.
        "User-Agent": "DocGrading/1.0",
    }
    if credential:
        if provider is LLMProvider.ANTHROPIC:
            headers.update({"x-api-key": credential, "anthropic-version": "2023-06-01"})
        elif provider is LLMProvider.GEMINI:
            headers["x-goog-api-key"] = credential
        else:
            headers["Authorization"] = f"Bearer {credential}"
    request = urllib.request.Request(endpoint, headers=headers, method="GET")

    class _NoRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, *_args: Any, **_kwargs: Any) -> None:
            return None

    context = ssl.create_default_context()
    context.minimum_version = ssl.TLSVersion.TLSv1_2
    opener = urllib.request.build_opener(
        urllib.request.ProxyHandler({}),
        _NoRedirect(),
        urllib.request.HTTPSHandler(context=context),
    )
    try:
        with opener.open(request, timeout=10) as response:
            return int(response.status), response.read(1_000_001)
    except urllib.error.HTTPError as exc:
        return int(exc.code), exc.read(64_000)


def _safe_status(code: int, *, timed_out: bool = False) -> LLMCatalogStatus:
    if timed_out or code == 408:
        return LLMCatalogStatus.TIMEOUT
    if code in {401, 403}:
        return LLMCatalogStatus.INVALID_CREDENTIAL
    if code == 429:
        return LLMCatalogStatus.RATE_LIMITED
    if 500 <= code <= 599:
        return LLMCatalogStatus.UNAVAILABLE
    return LLMCatalogStatus.INVALID_RESPONSE


def _model_ids(provider: LLMProvider, body: bytes) -> list[str]:
    if len(body) > 1_000_000:
        raise ValueError("response too large")
    data = json.loads(body)
    rows = data.get("data", data.get("models")) if isinstance(data, Mapping) else None
    if not isinstance(rows, list):
        raise ValueError("catalog response invalid")
    output: list[str] = []
    for row in rows[:100]:
        value = row.get("id", row.get("name")) if isinstance(row, Mapping) else None
        if isinstance(value, str) and 0 < len(value) <= 255:
            output.append(value.removeprefix("models/"))
    if not output and rows:
        raise ValueError("catalog response invalid")
    return output


def _keyring() -> dict[str, bytes]:
    settings = get_settings()
    return parse_keyring(
        settings.llm_credential_keyring.get_secret_value(),
        settings.llm_credential_active_key_id,
    )


def _environment_name(row: LLMProviderConfig) -> str | None:
    if row.credential_source is not LLMCredentialSource.ENVIRONMENT:
        return None
    allowed = supported_environment_keys(row.provider)
    return (
        row.environment_key_name
        if row.environment_key_name in allowed
        else (allowed[0] if allowed else None)
    )


def _current_fingerprint(row: LLMProviderConfig) -> str | None:
    if row.provider is LLMProvider.BEDROCK:
        return None
    if row.credential_source is LLMCredentialSource.ENVIRONMENT:
        value = resolve_environment_key(row.provider, _environment_name(row))
        return credential_fingerprint(value) if value else None
    if row.credential_source is LLMCredentialSource.STORED:
        if not row.ciphertext or not row.encryption_key_id:
            return None
        try:
            value = resolve_credential(
                row.provider,
                row.credential_source,
                ciphertext=row.ciphertext,
                credential_id=row.id,
                keyring=_keyring(),
                key_id=row.encryption_key_id,
            ).value
            return credential_fingerprint(value) if value else None
        except CredentialError:
            return None
    return None


def provider_response(row: LLMProviderConfig) -> LLMProviderResponse:
    name, docs = _PROVIDER_INFO[row.provider]
    env_name = _environment_name(row)
    env_configured = False
    if row.credential_source is LLMCredentialSource.ENVIRONMENT and env_name:
        try:
            env_configured = bool(resolve_environment_key(row.provider, env_name))
        except CredentialError:
            env_configured = False
    try:
        keyring = _keyring()
    except CredentialError:
        keyring = {}
    stored_available = bool(keyring)
    configured = (
        row.provider is LLMProvider.BEDROCK
        or env_configured
        or (
            row.credential_source is LLMCredentialSource.STORED
            and bool(row.ciphertext)
            and row.encryption_key_id in keyring
        )
    )
    return LLMProviderResponse(
        id=row.id,
        provider=row.provider,
        display_name=name,
        docs_url=docs,
        supported_environment_keys=supported_environment_keys(row.provider),
        supported_protocols=llm_provider_protocols(row.provider),
        enabled=row.enabled,
        data_policy_approved=row.data_policy_approved,
        credential_source=row.credential_source,
        environment_key_name=env_name,
        masked_hint=row.masked_hint,
        configured=configured,
        stored_credentials_available=stored_available,
        credential_revision=row.credential_revision,
        revision=row.revision,
        catalog_status=row.catalog_status,
        catalog_checked_at=row.catalog_checked_at,
        catalog_latency_ms=row.catalog_latency_ms,
        catalog_error_code=row.catalog_error_code,
    )


async def list_providers(db: AsyncSession) -> list[LLMProviderResponse]:
    rows = (
        await db.scalars(
            sa.select(LLMProviderConfig).order_by(LLMProviderConfig.provider)
        )
    ).all()
    return [provider_response(row) for row in rows]


def _check_revision(row: LLMProviderConfig, expected_revision: int) -> None:
    if row.revision != expected_revision:
        raise HTTPException(
            status_code=status.HTTP_412_PRECONDITION_FAILED, detail="Revision mismatch"
        )


async def _lock_provider(db: AsyncSession, row: LLMProviderConfig) -> LLMProviderConfig:
    locked = await db.scalar(
        sa.select(LLMProviderConfig)
        .where(LLMProviderConfig.id == row.id)
        .execution_options(populate_existing=True)
        .with_for_update()
    )
    if locked is None:
        raise HTTPException(status_code=404, detail="LLM provider not found")
    return locked


async def _deactivate_routes(db: AsyncSession, provider_id: uuid.UUID) -> None:
    active = (
        await db.scalars(
            sa.select(LLMRoute)
            .where(LLMRoute.provider_config_id == provider_id, LLMRoute.active)
            .with_for_update()
        )
    ).all()
    for route in active:
        route.active = False
        route.state = LLMRouteState.DISABLED
        route.activated_by_user_id = None
        route.activated_at = None
        route.revision += 1


async def update_provider(
    db: AsyncSession,
    *,
    row: LLMProviderConfig,
    body: LLMProviderUpdateRequest,
    expected_revision: int,
    actor_user_id: uuid.UUID,
) -> LLMProviderResponse:
    row = await _lock_provider(db, row)
    _check_revision(row, expected_revision)
    allowed = supported_environment_keys(row.provider)
    environment_name = body.environment_key_name
    if body.credential_source is LLMCredentialSource.ENVIRONMENT:
        environment_name = environment_name or (allowed[0] if allowed else None)
        if environment_name not in allowed:
            raise HTTPException(
                status_code=422, detail="Environment credential is invalid"
            )
    elif environment_name is not None:
        raise HTTPException(status_code=422, detail="Environment credential is invalid")
    if (
        row.provider is LLMProvider.BEDROCK
        and body.credential_source is not LLMCredentialSource.NONE
    ):
        raise HTTPException(status_code=422, detail="Bedrock uses IAM credentials")
    credential_value = (
        body.credential_key.get_secret_value() if body.credential_key else None
    )
    old_enabled = row.enabled
    old_policy = row.data_policy_approved
    old_source = row.credential_source
    old_environment_name = row.environment_key_name
    changed_credential = (
        body.credential_source != old_source
        or credential_value is not None
        or environment_name != old_environment_name
    )
    if (
        body.credential_source is LLMCredentialSource.STORED
        and not credential_value
        and old_source is not LLMCredentialSource.STORED
    ):
        raise HTTPException(status_code=422, detail="Credential key is required")
    keyring: dict[str, bytes] = {}
    if body.credential_source is LLMCredentialSource.STORED and credential_value:
        try:
            keyring = _keyring()
        except CredentialError as exc:
            raise HTTPException(
                status_code=503, detail="Credential encryption keyring is unavailable"
            ) from exc
    old = {
        "enabled": old_enabled,
        "credential_source": old_source.value,
        "data_policy_approved": old_policy,
        "revision": row.revision,
    }
    row.enabled = body.enabled
    row.data_policy_approved = body.data_policy_approved
    row.data_policy_approved_by_user_id = (
        actor_user_id if body.data_policy_approved else None
    )
    row.data_policy_approved_at = (
        datetime.now(UTC) if body.data_policy_approved else None
    )
    row.environment_key_name = (
        environment_name
        if body.credential_source is LLMCredentialSource.ENVIRONMENT
        else None
    )
    if changed_credential:
        row.credential_revision += 1
        row.catalog_status = LLMCatalogStatus.UNTESTED
        row.catalog_checked_at = None
        row.catalog_latency_ms = None
        row.catalog_error_code = None
        row.catalog_verified_credential_revision = None
        if body.credential_source is LLMCredentialSource.STORED and credential_value:
            try:
                (
                    row.ciphertext,
                    row.encryption_key_id,
                    row.masked_hint,
                    row.credential_fingerprint,
                ) = encrypt_credential(
                    credential_value,
                    credential_id=row.id,
                    provider=row.provider,
                    keyring=keyring,
                    active_key_id=get_settings().llm_credential_active_key_id,
                )
            except CredentialError as exc:
                raise HTTPException(
                    status_code=422, detail="Credential key is invalid"
                ) from exc
        else:
            row.ciphertext = row.encryption_key_id = row.masked_hint = (
                row.credential_fingerprint
            ) = None
        row.credential_source = body.credential_source
    if changed_credential or not body.enabled or not body.data_policy_approved:
        await _deactivate_routes(db, row.id)
    row.revision += 1
    await record_audit(
        db,
        actor_user_id=actor_user_id,
        resource_type="LLMProviderConfig",
        resource_id=row.id,
        action="UPDATED",
        before=old,
        after={
            "enabled": row.enabled,
            "credential_source": row.credential_source.value,
            "data_policy_approved": row.data_policy_approved,
            "revision": row.revision,
        },
        reason="Admin updated LLM provider",
    )
    await db.flush()
    return provider_response(row)


async def delete_credential(
    db: AsyncSession,
    *,
    row: LLMProviderConfig,
    expected_revision: int,
    actor_user_id: uuid.UUID,
) -> LLMProviderResponse:
    row = await _lock_provider(db, row)
    _check_revision(row, expected_revision)
    row.credential_source = LLMCredentialSource.NONE
    row.environment_key_name = row.ciphertext = row.encryption_key_id = (
        row.masked_hint
    ) = row.credential_fingerprint = None
    row.credential_revision += 1
    row.catalog_status = LLMCatalogStatus.UNTESTED
    row.catalog_checked_at = None
    row.catalog_latency_ms = None
    row.catalog_error_code = None
    row.catalog_verified_credential_revision = None
    row.revision += 1
    await _deactivate_routes(db, row.id)
    await record_audit(
        db,
        actor_user_id=actor_user_id,
        resource_type="LLMProviderConfig",
        resource_id=row.id,
        action="CREDENTIAL_REMOVED",
        after={
            "credential_source": "NONE",
            "credential_revision": row.credential_revision,
            "revision": row.revision,
        },
        reason="Admin removed LLM credential",
    )
    await db.flush()
    return provider_response(row)


def _bedrock_catalog() -> tuple[int, bytes]:
    try:
        import boto3
        from botocore.config import Config

        client = boto3.client(
            "bedrock",
            region_name=get_settings().storage_region,
            config=Config(proxies={}, ignore_configured_endpoint_urls=True),
        )
        endpoint = urlsplit(str(client.meta.endpoint_url))
        if (
            endpoint.scheme != "https"
            or endpoint.hostname is None
            or not endpoint.hostname.endswith((".amazonaws.com", ".amazonaws.com.cn"))
        ):
            return 503, b""
        result = client.list_foundation_models()
        return (
            200,
            json.dumps(
                {
                    "data": [
                        {"id": item.get("modelId")}
                        for item in result.get("modelSummaries", [])
                    ]
                }
            ).encode(),
        )
    except Exception:
        return 503, b""


async def test_catalog(
    db: AsyncSession,
    *,
    row: LLMProviderConfig,
    transport: CatalogTransport = _transport,
    expected_revision: int | None = None,
    actor_user_id: uuid.UUID | None = None,
) -> LLMCatalogTestResponse:
    if expected_revision is not None:
        _check_revision(row, expected_revision)
    row_revision = row.revision
    revision = row.credential_revision
    started = time.perf_counter()
    material_value: str | None = None
    try:
        if row.provider is LLMProvider.BEDROCK:
            code, payload = await asyncio.to_thread(_bedrock_catalog)
        else:
            material = resolve_credential(
                row.provider,
                row.credential_source,
                environment_key_name=_environment_name(row),
                ciphertext=row.ciphertext,
                credential_id=row.id,
                keyring=(
                    _keyring()
                    if row.credential_source is LLMCredentialSource.STORED
                    else None
                ),
                key_id=row.encryption_key_id,
            )
            material_value = material.value
            if not material_value:
                raise CredentialError("credential unavailable")
            code, payload = await asyncio.to_thread(
                transport, row.provider, material_value
            )
        status_value = (
            LLMCatalogStatus.CATALOG_VERIFIED
            if 200 <= code < 300
            else _safe_status(code)
        )
        ids = (
            _model_ids(row.provider, payload)
            if status_value is LLMCatalogStatus.CATALOG_VERIFIED
            else []
        )
        error_code = (
            None
            if status_value is LLMCatalogStatus.CATALOG_VERIFIED
            else status_value.value
        )
    except TimeoutError:
        status_value, ids, error_code = LLMCatalogStatus.TIMEOUT, [], "TIMEOUT"
    except CredentialError:
        status_value, ids, error_code = (
            LLMCatalogStatus.INVALID_CREDENTIAL,
            [],
            "INVALID_CREDENTIAL",
        )
    except urllib.error.URLError as exc:
        if _is_timeout_error(exc):
            status_value, ids, error_code = (
                LLMCatalogStatus.TIMEOUT,
                [],
                "TIMEOUT",
            )
        else:
            status_value, ids, error_code = (
                LLMCatalogStatus.UNAVAILABLE,
                [],
                "UNAVAILABLE",
            )
    except (json.JSONDecodeError, ValueError):
        status_value, ids, error_code = (
            LLMCatalogStatus.INVALID_RESPONSE,
            [],
            "INVALID_RESPONSE",
        )
    except Exception:
        status_value, ids, error_code = LLMCatalogStatus.UNAVAILABLE, [], "UNAVAILABLE"
    checked = datetime.now(UTC)
    latency = min(120_000, max(0, round((time.perf_counter() - started) * 1_000)))
    current = await db.scalar(
        sa.select(LLMProviderConfig)
        .where(LLMProviderConfig.id == row.id)
        .execution_options(populate_existing=True)
        .with_for_update()
    )
    if (
        current is None
        or current.revision != row_revision
        or current.credential_revision != revision
    ):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Credential changed; catalog result discarded",
        )
    verified_fingerprint = (
        credential_fingerprint(material_value)
        if status_value is LLMCatalogStatus.CATALOG_VERIFIED and material_value
        else None
    )
    if (
        verified_fingerprint
        and current.credential_source is LLMCredentialSource.ENVIRONMENT
        and current.credential_fingerprint
        and current.credential_fingerprint != verified_fingerprint
    ):
        current.credential_revision += 1
        revision = current.credential_revision
        await _deactivate_routes(db, current.id)
    current.catalog_status = status_value
    current.catalog_checked_at = checked
    current.catalog_latency_ms = latency
    current.catalog_error_code = error_code
    current.catalog_verified_credential_revision = (
        revision if status_value is LLMCatalogStatus.CATALOG_VERIFIED else None
    )
    if status_value is LLMCatalogStatus.CATALOG_VERIFIED:
        current.credential_fingerprint = verified_fingerprint
    current.revision += 1
    if actor_user_id is not None:
        await record_audit(
            db,
            actor_user_id=actor_user_id,
            resource_type="LLMProviderConfig",
            resource_id=current.id,
            action="CATALOG_TESTED",
            after={
                "status": status_value.value,
                "provider": current.provider.value,
                "credential_revision": revision,
                "latency_ms": latency,
            },
            reason="Admin tested LLM catalog",
        )
    await db.flush()
    return LLMCatalogTestResponse(
        provider=row.provider,
        status=status_value,
        model_ids=ids,
        latency_ms=latency,
        credential_revision=revision,
        catalog_checked_at=checked,
    )


def route_response(route: LLMRoute, provider: LLMProviderConfig) -> LLMRouteResponse:
    blockers: list[str] = []
    if not provider.enabled:
        blockers.append("provider_disabled")
    current_fingerprint = None
    try:
        current_fingerprint = _current_fingerprint(provider)
    except Exception:
        current_fingerprint = None
    if provider.provider is not LLMProvider.BEDROCK and (
        not provider.credential_fingerprint
        or current_fingerprint != provider.credential_fingerprint
    ):
        blockers.append("credential_not_verified")
    if not provider.data_policy_approved:
        blockers.append("data_policy_not_approved")
    if (
        provider.catalog_status is not LLMCatalogStatus.CATALOG_VERIFIED
        or provider.catalog_verified_credential_revision != provider.credential_revision
    ):
        blockers.append("catalog_not_verified")
    if not 1 <= route.max_tokens <= 1024:
        blockers.append("max_tokens_invalid")
    if not route.quality_approved:
        blockers.append("quality_not_approved")
    if not route.model_id:
        blockers.append("model_missing")
    if route.protocol not in llm_provider_protocols(provider.provider):
        blockers.append("protocol_not_supported")
    if provider.provider is LLMProvider.BEDROCK:
        if not route.region:
            blockers.append("region_missing")
        elif route.model_id and not bedrock_semantic_config_approved(
            route.model_id,
            route.region,
            route.geographic_profile or "",
        ):
            blockers.append("geographic_profile_not_approved")
    return LLMRouteResponse(
        id=route.id,
        task=route.task,
        state=route.state,
        active=route.active,
        provider=provider.provider,
        protocol=route.protocol,
        model_id=route.model_id,
        region=route.region,
        geographic_profile=route.geographic_profile,
        max_tokens=route.max_tokens,
        call_budget=route.call_budget,
        quality_approved=route.quality_approved,
        quality_not_approved=not route.quality_approved,
        provider_credential_revision=route.provider_credential_revision,
        revision=route.revision,
        ready=not blockers,
        blockers=blockers,
    )


async def get_route(db: AsyncSession) -> LLMRouteResponse:
    route = await db.scalar(
        sa.select(LLMRoute)
        .where(LLMRoute.task == LLMTask.CITATION_SEMANTIC)
        .options(sa.orm.joinedload(LLMRoute.provider_config))
    )
    if route is None:
        raise HTTPException(status_code=404, detail="LLM route not found")
    return route_response(route, route.provider_config)


async def save_route(
    db: AsyncSession,
    *,
    body: LLMRouteUpdateRequest,
    expected_revision: int,
    actor_user_id: uuid.UUID,
) -> LLMRouteResponse:
    provider = await db.scalar(
        sa.select(LLMProviderConfig)
        .where(LLMProviderConfig.provider == body.provider)
        .with_for_update()
    )
    route = await db.scalar(
        sa.select(LLMRoute)
        .where(LLMRoute.task == LLMTask.CITATION_SEMANTIC)
        .execution_options(populate_existing=True)
        .with_for_update()
    )
    if route is None or provider is None:
        raise HTTPException(status_code=404, detail="LLM route not found")
    _check_revision(route, expected_revision)
    old = {
        "revision": route.revision,
        "protocol": route.protocol.value,
        "model_id": route.model_id,
    }
    route.provider_config_id = provider.id
    route.model_id = body.model_id
    route.protocol = body.protocol
    route.region = body.region
    route.geographic_profile = body.geographic_profile
    route.max_tokens = body.max_tokens
    route.call_budget = body.call_budget
    route.quality_approved = body.quality_approved
    route.quality_approved_by_user_id = actor_user_id if body.quality_approved else None
    route.quality_approved_at = datetime.now(UTC) if body.quality_approved else None
    route.state = LLMRouteState.DRAFT
    route.active = False
    route.activated_by_user_id = None
    route.activated_at = None
    route.provider_credential_revision = provider.credential_revision
    route.revision += 1
    await record_audit(
        db,
        actor_user_id=actor_user_id,
        resource_type="LLMRoute",
        resource_id=route.id,
        action="SAVED",
        before=old,
        after={
            "revision": route.revision,
            "provider": provider.provider.value,
            "protocol": route.protocol.value,
            "model_id": route.model_id,
        },
        reason="Admin saved LLM route",
    )
    await db.flush()
    return route_response(route, provider)


async def set_route_active(
    db: AsyncSession,
    *,
    expected_revision: int,
    actor_user_id: uuid.UUID,
    activate: bool,
    request: LLMRouteActivationRequest | None = None,
) -> LLMRouteResponse:
    route_hint = await db.scalar(
        sa.select(LLMRoute).where(LLMRoute.task == LLMTask.CITATION_SEMANTIC)
    )
    if route_hint is None:
        raise HTTPException(status_code=404, detail="LLM route not found")
    provider = await db.scalar(
        sa.select(LLMProviderConfig)
        .where(LLMProviderConfig.id == route_hint.provider_config_id)
        .with_for_update()
    )
    route = await db.scalar(
        sa.select(LLMRoute)
        .where(LLMRoute.id == route_hint.id)
        .execution_options(populate_existing=True)
        .with_for_update()
    )
    if route is None or provider is None:
        raise HTTPException(status_code=404, detail="LLM route not found")
    if route.provider_config_id != provider.id:
        raise HTTPException(status_code=409, detail="LLM route changed; retry")
    _check_revision(route, expected_revision)
    if activate:
        if request is None or not request.acknowledge_provider_fees:
            raise HTTPException(status_code=422, detail="Fee acknowledgement required")
        result = route_response(route, provider)
        if not result.ready:
            raise HTTPException(status_code=409, detail={"blockers": result.blockers})
        route.state = LLMRouteState.ACTIVE
        route.active = True
        route.provider_credential_revision = provider.credential_revision
        route.activated_by_user_id = actor_user_id
        route.activated_at = datetime.now(UTC)
    else:
        route.state = LLMRouteState.DISABLED
        route.active = False
        route.activated_by_user_id = None
        route.activated_at = None
    route.revision += 1
    await record_audit(
        db,
        actor_user_id=actor_user_id,
        resource_type="LLMRoute",
        resource_id=route.id,
        action="ACTIVATED" if activate else "DEACTIVATED",
        after={"active": route.active, "revision": route.revision},
        reason="Admin changed LLM route state",
    )
    await db.flush()
    return route_response(route, provider)
