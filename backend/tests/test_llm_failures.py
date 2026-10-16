"""OpenAI failures never escape the chat as exceptions (so never as HTTP 500).

Every test drives the real ``openai`` SDK through an ``httpx.MockTransport``
that fails in one specific way, and checks the reply hides provider details.
DB-backed ``handle_chat`` coverage lives in ``test_chat_llm_failures_db.py``.
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from collections.abc import Callable
from types import SimpleNamespace

import httpx
import openai
import pytest

from app.core.config import Settings
from app.services import chat as chat_service
from app.services.chat import (
    ANSWER_FALLBACK_TEXT,
    SUMMARY_UNAVAILABLE_TEXT,
    Intent,
    RagScope,
    classify_intent,
    handle_chat,
)
from app.services.embeddings import (
    EmbeddingUnavailableError,
    OpenAIEmbeddingProvider,
    get_embedding_provider,
)
from app.services.rag import (
    LLMUnavailableError,
    OpenAIChatClient,
    RetrievedChunk,
    _vector_ranked,
    get_llm_client,
)
from tests.test_summary_cache_failures import _FakeSession

SECRET = "sk-leak-0123456789abcdef0123"
LEAK_HOST = "internal-gateway.example"
LEAK_URL = f"https://{LEAK_HOST}/v1/chat?api_key={SECRET}"
FAST_RETRY = {"retry-after-ms": "1"}  # keep retried statuses fast in tests
# conftest.py swaps this for ``lambda: None`` in every test; keep the real one.
REAL_RAG_EMBEDDING_PROVIDER = chat_service._rag_embedding_provider


def _error_body(message: str) -> dict:
    return {"error": {"message": message, "type": "error", "code": None}}


def _timeout(request: httpx.Request) -> httpx.Response:
    raise httpx.ReadTimeout(f"timed out calling {LEAK_URL}", request=request)


def _connection(request: httpx.Request) -> httpx.Response:
    raise httpx.ConnectError(f"cannot reach {LEAK_URL}", request=request)


def _rate_limit(_request: httpx.Request) -> httpx.Response:
    return httpx.Response(
        429, headers=FAST_RETRY, json=_error_body(f"Rate limit for key {SECRET}")
    )


def _server_error(_request: httpx.Request) -> httpx.Response:
    return httpx.Response(
        503, headers=FAST_RETRY, json=_error_body(f"upstream {LEAK_URL} is down")
    )


def _auth(_request: httpx.Request) -> httpx.Response:
    return httpx.Response(
        401, json=_error_body(f"Incorrect API key provided: {SECRET}")
    )


def _permission(_request: httpx.Request) -> httpx.Response:
    return httpx.Response(403, json=_error_body(f"Project {LEAK_URL} not allowed"))


FAILURES: dict[str, Callable[[httpx.Request], httpx.Response]] = {
    "timeout": _timeout,
    "connection": _connection,
    "rate_limit_429": _rate_limit,
    "server_error_503": _server_error,
    "auth_401": _auth,
    "permission_403": _permission,
}
RETRIED = {"timeout", "connection", "rate_limit_429", "server_error_503"}


def install_failing_openai(
    monkeypatch: pytest.MonkeyPatch, kind: str
) -> list[httpx.Request]:
    """Every OpenAI SDK request fails as *kind*; returns the requests made."""
    seen: list[httpx.Request] = []
    fail = FAILURES[kind]

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return fail(request)

    real_client = openai.AsyncOpenAI

    def client_with_mock_transport(**kwargs: object) -> openai.AsyncOpenAI:
        http_client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        return real_client(**kwargs, http_client=http_client)

    monkeypatch.setattr(openai, "AsyncOpenAI", client_with_mock_transport)
    return seen


def assert_no_leak(text: str) -> None:
    for fragment in (SECRET, LEAK_HOST, "api.openai.com", "Traceback"):
        assert fragment not in text, f"response leaks {fragment!r}"


def _settings(**overrides: object) -> Settings:
    return Settings(
        postgres_db="db", postgres_user="user", postgres_password="pw", **overrides
    )


def _chat_client() -> OpenAIChatClient:
    return OpenAIChatClient("sk-test", "gpt-test", timeout_seconds=5, max_retries=1)


# --- defaults ---------------------------------------------------------------


def test_chat_path_retries_once_and_summaries_twice_by_default() -> None:
    settings = _settings()
    assert settings.llm_max_retries == 1
    assert settings.llm_summary_max_retries == 2


@pytest.mark.parametrize("field", ["llm_summary_max_retries"])
def test_summary_retries_cannot_be_negative(field: str) -> None:
    with pytest.raises(ValueError):
        _settings(**{field: -1})


def test_summary_client_uses_summary_retry_budget(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen = install_failing_openai(monkeypatch, "server_error_503")
    settings = _settings(llm_api_key="sk-test")
    monkeypatch.setattr(chat_service, "get_settings", lambda: settings)
    monkeypatch.setattr(
        chat_service, "_rag_llm_client", lambda: get_llm_client(settings)
    )

    with pytest.raises(LLMUnavailableError):
        asyncio.run(
            chat_service._rag_summary_llm_client().complete(
                system="s", prompt="p", max_tokens=5
            )
        )
    assert len(seen) == 3, "1 attempt + llm_summary_max_retries=2"

    seen.clear()
    with pytest.raises(LLMUnavailableError):
        asyncio.run(
            chat_service._rag_llm_client().complete(
                system="s", prompt="p", max_tokens=5
            )
        )
    assert len(seen) == 2, "1 attempt + llm_max_retries=1"


# --- client level -------------------------------------------------------------


@pytest.mark.parametrize("kind", FAILURES)
def test_chat_client_raises_one_safe_error_type(
    monkeypatch: pytest.MonkeyPatch, kind: str
) -> None:
    seen = install_failing_openai(monkeypatch, kind)
    with pytest.raises(LLMUnavailableError) as caught:
        asyncio.run(_chat_client().complete(system="s", prompt="p", max_tokens=5))
    assert_no_leak(str(caught.value))
    assert len(seen) == (2 if kind in RETRIED else 1)


@pytest.mark.parametrize("kind", FAILURES)
def test_embedding_provider_raises_one_safe_error_type(
    monkeypatch: pytest.MonkeyPatch, kind: str
) -> None:
    install_failing_openai(monkeypatch, kind)
    provider = OpenAIEmbeddingProvider(
        "sk-test", "m", timeout_seconds=5, max_retries=0, rate_limit_retries=0
    )

    async def no_wait(_seconds: float) -> None:
        return None

    provider._sleep = no_wait  # type: ignore[attr-defined]
    with pytest.raises(EmbeddingUnavailableError) as caught:
        asyncio.run(provider.embed(["xin chào"]))
    assert_no_leak(str(caught.value))


def test_interactive_embeddings_skip_the_backfill_rate_limit_loop(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen = install_failing_openai(monkeypatch, "rate_limit_429")
    waits: list[float] = []

    async def record_wait(seconds: float) -> None:
        waits.append(seconds)

    provider = get_embedding_provider(
        _settings(embedding_api_key="sk-test", embedding_max_retries=1),
        interactive=True,
    )
    assert isinstance(provider, OpenAIEmbeddingProvider)
    provider._sleep = record_wait  # type: ignore[attr-defined]
    with pytest.raises(EmbeddingUnavailableError):
        asyncio.run(provider.embed(["q"]))
    assert len(seen) == 2, "only the SDK's own retry"
    assert waits == [], "no extra 20/40/... s waits on a chat request"


def test_chat_embeddings_are_interactive(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[dict] = []

    def fake_get(*args: object, **kwargs: object) -> object:
        calls.append(kwargs)
        return object()

    monkeypatch.setattr(chat_service, "get_embedding_provider", fake_get)
    REAL_RAG_EMBEDDING_PROVIDER()
    assert calls == [{"interactive": True}]


# --- embedding during retrieval --------------------------------------------------


@pytest.mark.parametrize("kind", FAILURES)
def test_vector_retrieval_degrades_to_nothing_when_embedding_fails(
    monkeypatch: pytest.MonkeyPatch, kind: str, caplog: pytest.LogCaptureFixture
) -> None:
    install_failing_openai(monkeypatch, kind)
    provider = OpenAIEmbeddingProvider(
        "sk-test", "m", timeout_seconds=5, max_retries=0, rate_limit_retries=0
    )
    with caplog.at_level(logging.WARNING, logger="app.services.rag"):
        ids = asyncio.run(_vector_ranked(None, [uuid.uuid4()], "kiểm thử", provider))  # type: ignore[arg-type]
    assert ids == []
    assert any(r.levelno == logging.WARNING for r in caplog.records)


# --- LLM router -----------------------------------------------------------------

UNKNOWN_MESSAGE = "zxqv plorb wint"


@pytest.mark.parametrize("kind", FAILURES)
def test_router_failure_is_answered_as_unknown(
    monkeypatch: pytest.MonkeyPatch, kind: str, caplog: pytest.LogCaptureFixture
) -> None:
    assert classify_intent(UNKNOWN_MESSAGE) is Intent.UNKNOWN
    seen = install_failing_openai(monkeypatch, kind)
    monkeypatch.setattr(chat_service, "_rag_llm_client", _chat_client)
    user = SimpleNamespace(id=uuid.uuid4(), roles=["TEACHER"])

    with caplog.at_level(logging.WARNING, logger="app.services.chat"):
        response = asyncio.run(
            handle_chat(
                None,  # type: ignore[arg-type]  # UNKNOWN never touches the DB
                user=user,  # type: ignore[arg-type]
                message=UNKNOWN_MESSAGE,
                course_id=None,
                assignment_id=None,
            )
        )

    assert seen, "the router really called the provider"
    assert response.intent == Intent.UNKNOWN
    assert response.reply == "Mình chưa hiểu câu hỏi này.\n" + chat_service._HELP_TEXT
    assert_no_leak(response.model_dump_json())
    warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
    assert warnings, "router failures are logged as warnings"


# --- answer with citations -----------------------------------------------------


def _scope() -> RagScope:
    return RagScope(SimpleNamespace(name="CS101"), [uuid.uuid4()], None)  # type: ignore[arg-type]


def _retrieved() -> list[RetrievedChunk]:
    return [
        RetrievedChunk(
            id=uuid.uuid4(),
            document_version_id=uuid.uuid4(),
            chunk_index=0,
            page_start=2,
            page_end=2,
            section_path="3. Kiểm thử",
            text="[3. Kiểm thử]\nNhóm viết kiểm thử đơn vị bằng pytest.",
            score=0.1,
        )
    ]


def _install_fake_retrieval(monkeypatch: pytest.MonkeyPatch) -> None:
    chunks = _retrieved()

    async def fake_retrieve(*_args: object, **_kwargs: object) -> list:
        return chunks

    async def fake_citations(_db: object, found: list, _query: str) -> list:
        return [
            chat_service.Citation(
                chunk_id=c.id,
                page=c.page_start,
                page_end=c.page_end,
                section_path=c.section_path,
                excerpt="Nhóm viết kiểm thử đơn vị bằng pytest.",
            )
            for c in found
        ]

    monkeypatch.setattr(chat_service, "retrieve_chunks", fake_retrieve)
    monkeypatch.setattr(chat_service, "_citations_for", fake_citations)
    monkeypatch.setattr(chat_service, "_rag_embedding_provider", lambda: None)


@pytest.mark.parametrize("kind", FAILURES)
def test_answer_failure_returns_the_retrieved_passages(
    monkeypatch: pytest.MonkeyPatch, kind: str, caplog: pytest.LogCaptureFixture
) -> None:
    seen = install_failing_openai(monkeypatch, kind)
    monkeypatch.setattr(chat_service, "_rag_llm_client", _chat_client)
    _install_fake_retrieval(monkeypatch)

    with caplog.at_level(logging.WARNING, logger="app.services.chat"):
        response = asyncio.run(
            chat_service._handle_ask_about_requirement(
                None, _scope(), "Bài này có kiểm thử không?"  # type: ignore[arg-type]
            )
        )

    assert seen
    assert response.intent == Intent.ASK_ABOUT_REQUIREMENT
    assert response.reply.splitlines()[0] == ANSWER_FALLBACK_TEXT
    assert "Trang 2" in response.reply
    assert response.citations and response.citations[0].page == 2
    assert response.llm_unavailable is True
    assert_no_leak(response.model_dump_json())
    assert any(r.levelno == logging.WARNING for r in caplog.records)


def test_answer_without_key_uses_the_same_safe_fallback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        chat_service, "_rag_llm_client", lambda: OpenAIChatClient("", "gpt-test")
    )
    _install_fake_retrieval(monkeypatch)
    response = asyncio.run(
        chat_service._handle_ask_about_requirement(
            None, _scope(), "Bài này có kiểm thử không?"  # type: ignore[arg-type]
        )
    )
    assert response.reply.splitlines()[0] == ANSWER_FALLBACK_TEXT
    assert "LLM_API_KEY" not in response.reply
    assert response.llm_unavailable is True


# --- summaries -------------------------------------------------------------------


@pytest.mark.parametrize("kind", FAILURES)
def test_summary_failure_is_reported_flagged_and_not_cached(
    monkeypatch: pytest.MonkeyPatch, kind: str, caplog: pytest.LogCaptureFixture
) -> None:
    seen = install_failing_openai(monkeypatch, kind)
    monkeypatch.setattr(chat_service, "_rag_llm_client", _chat_client)
    session = _FakeSession(existing=None)

    with caplog.at_level(logging.WARNING, logger="app.services.chat"):
        response = asyncio.run(
            chat_service._handle_summarize_submission(session, _scope())  # type: ignore[arg-type]
        )

    assert seen
    assert response.intent == Intent.SUMMARIZE_SUBMISSION
    assert response.reply == SUMMARY_UNAVAILABLE_TEXT
    assert response.llm_unavailable is True
    assert session.added == [] and session.commits == 0
    assert_no_leak(response.model_dump_json())
    assert any(r.levelno == logging.WARNING for r in caplog.records)


def test_empty_summary_is_flagged_too(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.services.rag import SUMMARY_FAILED_TEXT, FakeLLMClient

    monkeypatch.setattr(chat_service, "_rag_llm_client", lambda: FakeLLMClient(""))
    response = asyncio.run(
        chat_service._handle_summarize_submission(_FakeSession(existing=None), _scope())  # type: ignore[arg-type]
    )
    assert response.reply == SUMMARY_FAILED_TEXT
    assert response.llm_unavailable is True


def test_successful_summary_is_not_flagged(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.services.rag import FakeLLMClient

    monkeypatch.setattr(
        chat_service, "_rag_llm_client", lambda: FakeLLMClient("Tóm tắt thật")
    )
    response = asyncio.run(
        chat_service._handle_summarize_submission(_FakeSession(existing=None), _scope())  # type: ignore[arg-type]
    )
    assert response.reply == "Tóm tắt thật"
    assert response.llm_unavailable is False
