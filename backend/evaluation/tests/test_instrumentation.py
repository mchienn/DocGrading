"""The benchmark's counting clients behave like the product's clients.

They must reuse the product request path (error wrapping, timeout/retry from
config), still count tokens, count failed calls, and keep one shared call
counter across the copies the chat makes for the summary/router paths.
"""

from __future__ import annotations

import asyncio
import uuid
from types import SimpleNamespace

import httpx
import pytest

from app.core.config import Settings
from app.models.chunk import EMBEDDING_DIMENSIONS
from app.services import chat as chat_service
from app.services import rag as rag_service
from app.services.chat import Intent, handle_chat
from app.services.embeddings import EmbeddingUnavailableError, OpenAIEmbeddingProvider
from app.services.rag import LLMUnavailableError, OpenAIChatClient
from evaluation import instrumentation
from evaluation.instrumentation import (
    CountingChatClient,
    CountingEmbeddingProvider,
    RetrievalRecorder,
    TokenLedger,
    ablation_config,
    make_embedding_provider,
    make_llm_client,
)
from tests.openai_mock import OpenAIMock, chat_completion, embedding_list


def _settings(**overrides: object) -> Settings:
    return Settings(
        postgres_db="db",
        postgres_user="user",
        postgres_password="pw",
        llm_api_key="sk-test",
        embedding_api_key="sk-test",
        **overrides,
    )


@pytest.fixture
def settings(monkeypatch: pytest.MonkeyPatch) -> Settings:
    config = _settings(
        llm_timeout_seconds=12.5,
        llm_max_retries=1,
        embedding_timeout_seconds=6.5,
        embedding_max_retries=1,
    )
    monkeypatch.setattr(instrumentation, "get_settings", lambda: config)
    return config


def _server_error(_request: httpx.Request) -> httpx.Response:
    return httpx.Response(503, headers={"retry-after-ms": "1"})


def test_counting_clients_do_not_reimplement_the_request() -> None:
    assert CountingChatClient.complete is OpenAIChatClient.complete
    assert CountingEmbeddingProvider._request is OpenAIEmbeddingProvider._request
    assert CountingEmbeddingProvider.embed is OpenAIEmbeddingProvider.embed


def test_llm_success_counts_tokens_with_the_product_timeout(
    monkeypatch: pytest.MonkeyPatch, settings: Settings
) -> None:
    mock = OpenAIMock(
        lambda _r: httpx.Response(200, json=chat_completion("ok", 11, 7))
    ).install(monkeypatch)
    ledger = TokenLedger()
    client = make_llm_client(ledger)

    text = asyncio.run(
        client.complete(
            system=rag_service.ANSWER_SYSTEM_PROMPT, prompt="p", max_tokens=5
        )
    )

    assert text == "ok"
    assert ledger.llm["answer"] == {"calls": 1, "prompt": 11, "completion": 7}
    assert client.calls == 1
    assert mock.requests[0].extensions["timeout"]["read"] == 12.5


def test_llm_failure_is_the_product_error_and_is_counted(
    monkeypatch: pytest.MonkeyPatch, settings: Settings
) -> None:
    mock = OpenAIMock(_server_error).install(monkeypatch)
    ledger = TokenLedger()
    client = make_llm_client(ledger)

    with pytest.raises(LLMUnavailableError):
        asyncio.run(
            client.complete(
                system=rag_service.ANSWER_SYSTEM_PROMPT, prompt="p", max_tokens=5
            )
        )

    assert len(mock.requests) == 2, "1 attempt + llm_max_retries=1"
    assert ledger.errors == {"answer": 1}
    assert ledger.snapshot()["errors"] == {"answer": 1}
    assert ledger.llm_total == 0
    assert client.calls == 1


def test_copies_made_by_the_chat_share_the_call_counter(
    monkeypatch: pytest.MonkeyPatch, settings: Settings
) -> None:
    OpenAIMock(lambda _r: httpx.Response(200, json=chat_completion("ok"))).install(
        monkeypatch
    )
    ledger = TokenLedger()
    client = make_llm_client(ledger)
    monkeypatch.setattr(chat_service, "_rag_llm_client", lambda: client)

    summary_client = chat_service._rag_summary_llm_client()
    asyncio.run(
        summary_client.complete(
            system=rag_service.SUMMARY_SYSTEM_PROMPT, prompt="p", max_tokens=5
        )
    )

    assert summary_client is not client
    assert client.calls == 1, "cache_suite reads the original client's counter"
    assert ledger.llm["summary"]["calls"] == 1


def test_embedding_success_counts_tokens_with_the_product_timeout(
    monkeypatch: pytest.MonkeyPatch, settings: Settings
) -> None:
    mock = OpenAIMock(
        lambda _r: httpx.Response(
            200, json=embedding_list(1, EMBEDDING_DIMENSIONS, tokens=4)
        )
    ).install(monkeypatch)
    ledger = TokenLedger()
    provider = make_embedding_provider(ledger)

    vectors = asyncio.run(provider.embed(["xin chào"]))

    assert len(vectors) == 1 and len(vectors[0]) == EMBEDDING_DIMENSIONS
    assert ledger.embedding["calls"] == 1 and ledger.embedding["tokens"] == 4
    assert mock.requests[0].extensions["timeout"]["read"] == 6.5


def test_embedding_failure_is_the_product_error_and_is_counted(
    monkeypatch: pytest.MonkeyPatch, settings: Settings
) -> None:
    mock = OpenAIMock(_server_error).install(monkeypatch)
    ledger = TokenLedger()
    provider = make_embedding_provider(ledger)

    with pytest.raises(EmbeddingUnavailableError):
        asyncio.run(provider.embed(["xin chào"]))

    assert len(mock.requests) == 2, "1 attempt + embedding_max_retries=1"
    assert ledger.errors == {"embedding": 1}


def test_rule_only_configuration_still_answers_unknown_questions() -> None:
    user = SimpleNamespace(id=uuid.uuid4(), roles=["TEACHER"])
    with ablation_config("rule_only", TokenLedger(), RetrievalRecorder()):
        response = asyncio.run(
            handle_chat(
                None,  # type: ignore[arg-type]
                user=user,  # type: ignore[arg-type]
                message="zxqv plorb wint",
                course_id=None,
                assignment_id=None,
            )
        )
    assert response.intent == Intent.UNKNOWN
