from __future__ import annotations

import asyncio
import json
import os
import urllib.error
import uuid
from types import SimpleNamespace

import pytest
import sqlalchemy as sa
from fastapi import HTTPException
from pydantic import SecretStr
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.pool import NullPool

from app.api.schemas_llm import (
    LLMProviderUpdateRequest,
    LLMRouteActivationRequest,
    LLMRouteUpdateRequest,
)
from app.core.config import Settings, get_settings
from app.models import LLMProviderConfig, LLMRoute
from app.models.enums import (
    LLMCatalogStatus,
    LLMCredentialSource,
    LLMProtocol,
    LLMProvider,
    LLMRouteState,
    LLMTask,
)
from app.services.llm_credentials import (
    CredentialError,
    credential_fingerprint,
    decrypt_credential,
    encrypt_credential,
    masked_hint,
    resolve_environment_key,
)
from app.services.llm_providers import (
    _is_timeout_error,
    _safe_status,
    provider_response,
    route_response,
    save_route,
    set_route_active,
    update_provider,
)
from app.services.llm_providers import (
    test_catalog as verify_catalog,
)
from app.services.semantic_adapters import (
    HostedSemanticModel,
    _payload,
    _request,
    _response_text,
)
from app.services.semantic_citation import SemanticProviderError, _snapshot_model


def test_catalog_timeout_classification_handles_http_and_socket_timeout() -> None:
    assert _safe_status(408) is LLMCatalogStatus.TIMEOUT
    assert _is_timeout_error(urllib.error.URLError(TimeoutError()))


def test_credential_envelope_binds_row_and_provider() -> None:
    row_id = uuid.uuid4()
    keyring = {"v1": b"k" * 32}
    envelope, key_id, hint, fingerprint = encrypt_credential(
        "sk-secret-value",
        credential_id=row_id,
        provider=LLMProvider.OPENAI,
        keyring=keyring,
        active_key_id="v1",
    )
    assert (
        decrypt_credential(
            envelope,
            credential_id=row_id,
            provider=LLMProvider.OPENAI,
            keyring=keyring,
            key_id=key_id,
        )
        == "sk-secret-value"
    )
    assert b"sk-secret-value" not in envelope
    assert "sk-secret-value" not in repr((envelope, hint, fingerprint))
    with pytest.raises(CredentialError):
        decrypt_credential(
            envelope,
            credential_id=row_id,
            provider=LLMProvider.GEMINI,
            keyring=keyring,
            key_id=key_id,
        )


def test_masked_hint_never_reveals_key_length() -> None:
    assert masked_hint("tiny") == "••••"
    assert masked_hint("short") == "••••hort"
    assert masked_hint("s" * 4096) == "••••ssss"
    assert len(masked_hint("s" * 4096)) <= 32


def test_secret_input_repr_excludes_plaintext() -> None:
    request = LLMProviderUpdateRequest(
        enabled=True,
        credential_source=LLMCredentialSource.STORED,
        credential_key="super-secret-key",
    )
    assert "super-secret-key" not in repr(request)
    assert request.credential_key is not None
    assert request.credential_key.get_secret_value() == "super-secret-key"


def test_keyring_setting_repr_excludes_plaintext() -> None:
    settings = Settings(
        postgres_db="test",
        postgres_user="test",
        postgres_password="test",
        join_rate_limit_hash_secret="x" * 32,
        llm_credential_keyring='{"v1":"c2VjcmV0"}',
    )
    assert '{"v1":"c2VjcmV0"}' not in repr(settings)


def test_environment_selection_is_exact() -> None:
    environ = {"GEMINI_API_KEY": "gemini", "GOOGLE_API_KEY": "google"}
    assert (
        resolve_environment_key(LLMProvider.GEMINI, "GOOGLE_API_KEY", environ)
        == "google"
    )
    assert (
        resolve_environment_key(LLMProvider.GEMINI, "GEMINI_API_KEY", environ)
        == "gemini"
    )
    with pytest.raises(CredentialError):
        resolve_environment_key(LLMProvider.GEMINI, "UNTRUSTED_KEY", environ)


def test_provider_response_has_safe_configuration_fields(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    row = SimpleNamespace(
        id=uuid.uuid4(),
        provider=LLMProvider.OPENAI,
        enabled=True,
        data_policy_approved=False,
        credential_source=LLMCredentialSource.STORED,
        environment_key_name=None,
        masked_hint="••••alue",
        ciphertext=b"ciphertext",
        encryption_key_id="key-id",
        credential_fingerprint="f" * 64,
        credential_revision=2,
        revision=3,
        catalog_status=LLMCatalogStatus.UNTESTED,
        catalog_checked_at=None,
        catalog_latency_ms=None,
        catalog_error_code=None,
    )
    monkeypatch.setattr("app.services.llm_providers._keyring", lambda: {})
    response = provider_response(row)
    dumped = response.model_dump_json()
    assert not response.configured
    assert not response.stored_credentials_available
    assert "ciphertext" not in dumped
    assert "fingerprint" not in dumped
    assert "key-id" not in dumped

    monkeypatch.setattr(
        "app.services.llm_providers._keyring", lambda: {"key-id": b"k" * 32}
    )
    response = provider_response(row)
    assert response.configured
    assert response.stored_credentials_available


def _ready_route_and_provider(secret: str) -> tuple[SimpleNamespace, SimpleNamespace]:
    provider = SimpleNamespace(
        id=uuid.uuid4(),
        provider=LLMProvider.OPENAI,
        enabled=True,
        data_policy_approved=True,
        credential_source=LLMCredentialSource.ENVIRONMENT,
        environment_key_name="OPENAI_API_KEY",
        credential_fingerprint=credential_fingerprint(secret),
        credential_revision=4,
        catalog_status=LLMCatalogStatus.CATALOG_VERIFIED,
        catalog_verified_credential_revision=4,
    )
    route = SimpleNamespace(
        id=uuid.uuid4(),
        task=LLMTask.CITATION_SEMANTIC,
        state=LLMRouteState.DRAFT,
        active=False,
        protocol=LLMProtocol.OPENAI_RESPONSES,
        model_id="gpt-5-mini",
        region=None,
        geographic_profile=None,
        max_tokens=512,
        call_budget=8,
        quality_approved=True,
        provider_credential_revision=4,
        revision=2,
    )
    return route, provider


def test_route_readiness_fails_closed_after_environment_key_rotation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "verified-secret")
    route, provider = _ready_route_and_provider("verified-secret")
    assert route_response(route, provider).ready

    monkeypatch.setenv("OPENAI_API_KEY", "rotated-secret")
    response = route_response(route, provider)
    assert not response.ready
    assert "credential_not_verified" in response.blockers


def test_job_snapshot_resolves_only_current_verified_credential(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "verified-secret")
    monkeypatch.setattr("app.services.semantic_citation._server_settings", object)
    route, provider = _ready_route_and_provider("verified-secret")
    snapshot = {
        "provider": provider.provider.value,
        "protocol": route.protocol.value,
        "model_id": route.model_id,
        "max_tokens": route.max_tokens,
        "call_budget": route.call_budget,
        "credential_revision": provider.credential_revision,
        "enabled": True,
        "data_policy_approved": True,
        "quality_approved": True,
        "credential_source": provider.credential_source.value,
        "environment_key_name": provider.environment_key_name,
    }

    class Result:
        def one_or_none(self) -> tuple[uuid.UUID, str, str]:
            return (
                uuid.UUID("20000000-0000-4000-8000-000000000001"),
                "alice@example.test",
                "Alice Example",
            )

    class Database:
        async def scalar(self, _query: object) -> SimpleNamespace:
            return provider

        async def execute(self, _query: object) -> Result:
            return Result()

    job = SimpleNamespace(
        document_version_id=uuid.uuid4(),
        snapshot={"llm_route": snapshot},
    )
    model = asyncio.run(_snapshot_model(Database(), job))
    assert isinstance(model, HostedSemanticModel)
    assert model.audit_metadata()["model_id"] == "gpt-5-mini"

    monkeypatch.setenv("OPENAI_API_KEY", "rotated-secret")
    assert asyncio.run(_snapshot_model(Database(), job)) is None


@pytest.mark.parametrize(
    ("keyring", "key", "status_code"),
    [
        pytest.param(
            CredentialError("credential keyring is empty"),
            "sk-valid",
            503,
            id="server-keyring-unavailable",
        ),
        pytest.param({"key-id": b"k" * 32}, "x" * 4097, 422, id="entered-key-too-long"),
    ],
)
def test_stored_credential_separates_keyring_and_entered_key_errors(
    monkeypatch: pytest.MonkeyPatch,
    keyring: object,
    key: str,
    status_code: int,
) -> None:
    provider = SimpleNamespace(
        id=uuid.uuid4(),
        provider=LLMProvider.OPENAI,
        credential_source=LLMCredentialSource.NONE,
        environment_key_name=None,
        enabled=True,
        data_policy_approved=False,
        credential_revision=1,
        revision=1,
    )

    async def lock(_db: object, row: object) -> object:
        return row

    def resolve() -> dict[str, bytes]:
        if isinstance(keyring, Exception):
            raise keyring
        return keyring  # type: ignore[return-value]

    monkeypatch.setattr("app.services.llm_providers._lock_provider", lock)
    monkeypatch.setattr("app.services.llm_providers._keyring", resolve)
    body = LLMProviderUpdateRequest.model_construct(
        enabled=True,
        credential_source=LLMCredentialSource.STORED,
        environment_key_name=None,
        credential_key=SecretStr(key),
        data_policy_approved=False,
    )
    with pytest.raises(HTTPException) as caught:
        asyncio.run(
            update_provider(
                None,  # type: ignore[arg-type]
                row=provider,  # type: ignore[arg-type]
                body=body,
                expected_revision=1,
                actor_user_id=uuid.uuid4(),
            )
        )
    assert caught.value.status_code == status_code


def test_job_route_snapshot_takes_a_shared_row_lock() -> None:
    from sqlalchemy.dialects import postgresql

    from app.services.analysis_job import _llm_route_snapshot

    captured: list[object] = []

    class Database:
        async def scalar(self, query: object) -> None:
            captured.append(query)

    assert asyncio.run(_llm_route_snapshot(Database())) is None  # type: ignore[arg-type]
    sql = str(captured[0].compile(dialect=postgresql.dialect()))  # type: ignore[attr-defined]
    # FOR SHARE blocks route mutation but lets concurrent job creation proceed.
    assert sql.rstrip().endswith("FOR SHARE")


def test_provider_payload_removes_known_identity_and_extra_metadata() -> None:
    source = SimpleNamespace(
        source_id="doi:10.1000/source",
        title="Unused source title",
        access_type=SimpleNamespace(value="FULL_TEXT"),
    )
    passage = SimpleNamespace(
        passage_id="passage-1",
        text=(
            "Evidence by Alice Example for alice@example.test, "
            "20000000-0000-4000-8000-000000000001."
        ),
        page_number=7,
        section="Student records",
    )
    payload = _payload(
        "Student name: Alice Example\nClaim text.",
        "Contact alice@example.test",
        source,
        [passage],
        (
            "Alice Example",
            "alice@example.test",
            "20000000-0000-4000-8000-000000000001",
        ),
    )
    assert "Alice Example" not in payload
    assert "alice@example.test" not in payload
    assert "20000000-0000-4000-8000-000000000001" not in payload
    assert "Unused source title" not in payload
    assert "Student records" not in payload


def test_successful_environment_rotation_advances_revision_and_disables_route(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "rotated-secret")
    provider = SimpleNamespace(
        id=uuid.uuid4(),
        provider=LLMProvider.OPENAI,
        credential_source=LLMCredentialSource.ENVIRONMENT,
        environment_key_name="OPENAI_API_KEY",
        ciphertext=None,
        encryption_key_id=None,
        credential_fingerprint=credential_fingerprint("verified-secret"),
        credential_revision=4,
        revision=3,
        catalog_status=LLMCatalogStatus.CATALOG_VERIFIED,
        catalog_checked_at=None,
        catalog_latency_ms=None,
        catalog_error_code=None,
        catalog_verified_credential_revision=4,
    )
    active_route = SimpleNamespace(
        active=True,
        state=LLMRouteState.ACTIVE,
        activated_by_user_id=uuid.uuid4(),
        activated_at=object(),
        revision=2,
    )

    class Rows:
        def all(self) -> list[SimpleNamespace]:
            return [active_route]

    class Database:
        async def scalar(self, _query: object) -> SimpleNamespace:
            return provider

        async def scalars(self, _query: object) -> Rows:
            return Rows()

        async def flush(self) -> None:
            return None

    result = asyncio.run(
        verify_catalog(
            Database(),
            row=provider,
            transport=lambda _provider, _credential: (
                200,
                b'{"data":[{"id":"gpt-5-mini"}]}',
            ),
        )
    )
    assert result.credential_revision == 5
    assert provider.catalog_verified_credential_revision == 5
    assert not active_route.active
    assert active_route.state is LLMRouteState.DISABLED


def test_bedrock_rejects_unapproved_model_profile_before_activation() -> None:
    route, provider = _ready_route_and_provider("unused")
    provider.provider = LLMProvider.BEDROCK
    provider.credential_source = LLMCredentialSource.NONE
    provider.credential_fingerprint = None
    route.protocol = LLMProtocol.BEDROCK_CONVERSE
    route.model_id = "global.vendor-model"
    route.region = "us-east-1"
    response = route_response(route, provider)
    assert not response.ready
    assert "geographic_profile_not_approved" in response.blockers


@pytest.mark.skipif(
    os.environ.get("RUN_DATABASE_TESTS") != "1",
    reason="Database integration tests require RUN_DATABASE_TESTS=1",
)
def test_postgresql_llm_route_activation_and_environment_rotation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def scenario() -> None:
        engine = create_async_engine(get_settings().database_url, poolclass=NullPool)
        connection = await engine.connect()
        transaction = await connection.begin()
        session = AsyncSession(bind=connection, expire_on_commit=False)
        admin_id = uuid.uuid4()
        try:
            await connection.execute(
                sa.text(
                    "INSERT INTO public.users "
                    "(id, email, display_name, password_hash, roles, status, revision) "
                    "VALUES (:id, :email, 'LLM Admin', 'hash', "
                    "ARRAY['ADMIN']::public.user_role[], "
                    "'ACTIVE'::public.user_status, 1)"
                ),
                {"id": admin_id, "email": f"llm-{admin_id}@test.local"},
            )
            provider = await session.scalar(
                sa.select(LLMProviderConfig).where(
                    LLMProviderConfig.provider == LLMProvider.OPENAI
                )
            )
            route = await session.scalar(
                sa.select(LLMRoute).where(LLMRoute.task == LLMTask.CITATION_SEMANTIC)
            )
            assert provider is not None
            assert route is not None

            monkeypatch.setenv("OPENAI_API_KEY", "verified-secret")
            provider_response_value = await update_provider(
                session,
                row=provider,
                body=LLMProviderUpdateRequest(
                    enabled=True,
                    credential_source=LLMCredentialSource.ENVIRONMENT,
                    environment_key_name="OPENAI_API_KEY",
                    data_policy_approved=True,
                ),
                expected_revision=provider.revision,
                actor_user_id=admin_id,
            )
            catalog = await verify_catalog(
                session,
                row=provider,
                expected_revision=provider_response_value.revision,
                actor_user_id=admin_id,
                transport=lambda _provider, _credential: (
                    200,
                    b'{"data":[{"id":"gpt-5-mini"}]}',
                ),
            )
            assert catalog.status is LLMCatalogStatus.CATALOG_VERIFIED

            draft = await save_route(
                session,
                body=LLMRouteUpdateRequest(
                    provider=LLMProvider.OPENAI,
                    model_id="gpt-5-mini",
                    protocol=LLMProtocol.OPENAI_RESPONSES,
                    max_tokens=512,
                    call_budget=8,
                    quality_approved=True,
                ),
                expected_revision=route.revision,
                actor_user_id=admin_id,
            )
            active = await set_route_active(
                session,
                expected_revision=draft.revision,
                actor_user_id=admin_id,
                activate=True,
                request=LLMRouteActivationRequest(acknowledge_provider_fees=True),
            )
            assert active.active
            assert active.state is LLMRouteState.ACTIVE

            previous_credential_revision = provider.credential_revision
            monkeypatch.setenv("OPENAI_API_KEY", "rotated-secret")
            rotated = await verify_catalog(
                session,
                row=provider,
                expected_revision=provider.revision,
                actor_user_id=admin_id,
                transport=lambda _provider, _credential: (
                    200,
                    b'{"data":[{"id":"gpt-5-mini"}]}',
                ),
            )
            assert rotated.credential_revision == previous_credential_revision + 1
            await session.refresh(route)
            assert not route.active
            assert route.state is LLMRouteState.DISABLED

            with pytest.raises(HTTPException) as stale:
                await update_provider(
                    session,
                    row=provider,
                    body=LLMProviderUpdateRequest(
                        enabled=True,
                        credential_source=LLMCredentialSource.ENVIRONMENT,
                        environment_key_name="OPENAI_API_KEY",
                        data_policy_approved=True,
                    ),
                    expected_revision=provider_response_value.revision,
                    actor_user_id=admin_id,
                )
            assert stale.value.status_code == 412
        finally:
            await session.close()
            await transaction.rollback()
            await connection.close()
            await engine.dispose()

    asyncio.run(scenario())


@pytest.mark.parametrize(
    ("provider", "protocol", "suffix", "header"),
    [
        (
            LLMProvider.OPENAI,
            LLMProtocol.OPENAI_CHAT,
            "/v1/chat/completions",
            "Authorization",
        ),
        (
            LLMProvider.OPENAI,
            LLMProtocol.OPENAI_RESPONSES,
            "/v1/responses",
            "Authorization",
        ),
        (
            LLMProvider.ANTHROPIC,
            LLMProtocol.ANTHROPIC_MESSAGES,
            "/v1/messages",
            "x-api-key",
        ),
        (
            LLMProvider.GEMINI,
            LLMProtocol.GEMINI_GENERATE_CONTENT,
            "/v1beta/models/model%2Fid:generateContent",
            "x-goog-api-key",
        ),
        (
            LLMProvider.OPENCODE_ZEN,
            LLMProtocol.ANTHROPIC_MESSAGES,
            "opencode.ai/inference/v1/messages",
            "Authorization",
        ),
        (
            LLMProvider.OPENCODE_ZEN,
            LLMProtocol.GEMINI_GENERATE_CONTENT,
            "opencode.ai/inference/v1/models/model%2Fid:generateContent",
            "Authorization",
        ),
    ],
)
def test_hosted_request_builder_has_fixed_endpoint_and_auth(
    provider: LLMProvider, protocol: LLMProtocol, suffix: str, header: str
) -> None:
    request = _request(provider, protocol, "model/id", "secret", b"{}")
    assert request.full_url.endswith(suffix)
    assert header.lower() in {key.lower() for key in request.headers}
    assert "secret" not in request.full_url
    assert request.get_header("User-agent") == "DocGrading/1.0"


@pytest.mark.parametrize(
    ("provider", "field", "other"),
    [
        (LLMProvider.OPENAI, "max_completion_tokens", "max_tokens"),
        (LLMProvider.DEEPSEEK, "max_tokens", "max_completion_tokens"),
        (LLMProvider.OPENCODE_ZEN, "max_tokens", "max_completion_tokens"),
    ],
)
def test_openai_chat_token_limit_field_matches_provider(
    provider: LLMProvider, field: str, other: str
) -> None:
    sent: list[dict[str, object]] = []

    def transport(*args: object) -> tuple[int, dict[str, object]]:
        sent.append(json.loads(args[-1]))  # type: ignore[arg-type]
        return 200, {}

    model = HostedSemanticModel(
        {
            "provider": provider.value,
            "protocol": LLMProtocol.OPENAI_CHAT.value,
            "model_id": "model-id",
            "max_tokens": 321,
            "credential": "secret",
        },
        transport=transport,  # type: ignore[arg-type]
    )
    model._request("user text")

    assert sent[0][field] == 321
    assert other not in sent[0]


def test_catalog_request_sends_explicit_user_agent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.services import llm_providers

    sent: list[urllib.request.Request] = []

    class FakeResponse:
        status = 200

        def __enter__(self) -> FakeResponse:
            return self

        def __exit__(self, *_args: object) -> None:
            return None

        def read(self, _limit: int) -> bytes:
            return b'{"data": []}'

    class FakeOpener:
        def open(self, request: urllib.request.Request, timeout: float) -> FakeResponse:
            sent.append(request)
            return FakeResponse()

    monkeypatch.setattr(
        llm_providers.urllib.request, "build_opener", lambda *_handlers: FakeOpener()
    )
    assert llm_providers._transport(LLMProvider.OPENCODE_ZEN, "secret")[0] == 200
    assert sent[0].get_header("User-agent") == "DocGrading/1.0"


def test_hosted_transport_waits_out_rate_limit_then_gives_up(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Parallel claims on a free tier get 429; the transport waits as Gemini asks
    # (retryDelay in the error body) and retries, but not forever.
    import io
    import urllib.error

    from app.services import semantic_adapters

    calls: list[str] = []
    waits: list[float] = []
    outcomes = [429, "ok", 429, 429, 429]

    class FakeResponse(io.BytesIO):
        def __enter__(self) -> FakeResponse:
            return self

        def __exit__(self, *_args: object) -> None:
            return None

    class FakeOpener:
        def open(self, request: urllib.request.Request, timeout: float) -> object:
            calls.append(request.full_url)
            outcome = outcomes.pop(0)
            if outcome == "ok":
                return FakeResponse(b'{"ok": true}')
            raise urllib.error.HTTPError(
                request.full_url,
                429,
                "quota",
                {},
                io.BytesIO(b'{"error": {"details": [{"retryDelay": "7s"}]}}'),
            )

    monkeypatch.setattr(
        semantic_adapters.urllib.request, "build_opener", lambda *_h: FakeOpener()
    )
    monkeypatch.setattr(semantic_adapters.time, "sleep", waits.append)

    def send() -> bytes:
        return semantic_adapters._default_transport(
            LLMProvider.GEMINI,
            LLMProtocol.GEMINI_GENERATE_CONTENT,
            "gemini-test",
            "key",
            b"{}",
        )

    assert send() == b'{"ok": true}'
    with pytest.raises(SemanticProviderError):
        send()
    assert len(calls) == 5
    assert waits == [7.0, 7.0, 7.0]


def test_hosted_request_builder_rejects_oversized_body() -> None:
    with pytest.raises(SemanticProviderError, match="semantic request too large"):
        _request(
            LLMProvider.OPENAI,
            LLMProtocol.OPENAI_CHAT,
            "model",
            "secret",
            b"x" * 1_000_001,
        )


@pytest.mark.parametrize(
    ("protocol", "body"),
    [
        (
            LLMProtocol.OPENAI_CHAT,
            {
                "choices": [{"message": {"content": "{}"}}],
                "usage": {"prompt_tokens": 2, "completion_tokens": 3},
            },
        ),
        (
            LLMProtocol.OPENAI_RESPONSES,
            {"output_text": "{}", "usage": {"input_tokens": 2, "output_tokens": 3}},
        ),
        (
            LLMProtocol.ANTHROPIC_MESSAGES,
            {
                "content": [{"text": "{}"}],
                "usage": {"input_tokens": 2, "output_tokens": 3},
            },
        ),
        (
            LLMProtocol.GEMINI_GENERATE_CONTENT,
            {
                "candidates": [{"content": {"parts": [{"text": "{}"}]}}],
                "usageMetadata": {"promptTokenCount": 2, "candidatesTokenCount": 3},
            },
        ),
    ],
)
def test_protocol_response_text_and_usage(
    protocol: LLMProtocol, body: dict[str, object]
) -> None:
    text, usage = _response_text(protocol, body)
    assert json.loads(text) == {}
    assert usage[:2] == (2, 3)
