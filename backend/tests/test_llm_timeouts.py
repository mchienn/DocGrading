"""OpenAI clients use the timeout/retry budget from config, not SDK defaults.

The SDK default is a 600 s timeout with 2 retries, so one stuck request could
hold a chat request for half an hour. These tests drive the real ``openai``
client through an ``httpx.MockTransport`` that times out, so they check what
the SDK actually sends and how often it retries — no network involved.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable

import httpx
import openai
import pytest

from app.core.config import Settings
from app.services.embeddings import (
    EmbeddingUnavailableError,
    OpenAIEmbeddingProvider,
    get_embedding_provider,
)
from app.services.rag import LLMUnavailableError, OpenAIChatClient, get_llm_client


def _settings(**overrides: object) -> Settings:
    return Settings(
        postgres_db="db", postgres_user="user", postgres_password="pw", **overrides
    )


def _timing_out_transport(
    monkeypatch: pytest.MonkeyPatch,
) -> list[dict[str, float | None]]:
    """Every request the SDK makes times out; returns the timeouts it sent."""
    sent: list[dict[str, float | None]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        sent.append(dict(request.extensions["timeout"]))
        raise httpx.ReadTimeout("simulated provider timeout", request=request)

    real_client: Callable[..., openai.AsyncOpenAI] = openai.AsyncOpenAI

    def client_with_mock_transport(**kwargs: object) -> openai.AsyncOpenAI:
        http_client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        return real_client(**kwargs, http_client=http_client)

    monkeypatch.setattr(openai, "AsyncOpenAI", client_with_mock_transport)
    return sent


def test_timeout_and_retry_defaults() -> None:
    settings = _settings()
    assert settings.llm_timeout_seconds == 30.0
    assert settings.llm_max_retries == 1
    assert settings.embedding_timeout_seconds == 20.0
    assert settings.embedding_max_retries == 2


@pytest.mark.parametrize("field", ["llm_timeout_seconds", "embedding_timeout_seconds"])
def test_timeouts_must_be_positive(field: str) -> None:
    with pytest.raises(ValueError):
        _settings(**{field: 0})


@pytest.mark.parametrize("field", ["llm_max_retries", "embedding_max_retries"])
def test_retries_cannot_be_negative(field: str) -> None:
    with pytest.raises(ValueError):
        _settings(**{field: -1})


def test_chat_completion_times_out_with_configured_budget(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sent = _timing_out_transport(monkeypatch)
    client = get_llm_client(
        _settings(llm_api_key="sk-test", llm_timeout_seconds=7.5, llm_max_retries=1)
    )
    assert isinstance(client, OpenAIChatClient)

    with pytest.raises(LLMUnavailableError) as caught:
        asyncio.run(client.complete(system="s", prompt="p", max_tokens=10))

    assert isinstance(caught.value.__cause__, openai.APITimeoutError)
    assert len(sent) == 2, "1 attempt + llm_max_retries=1 retry"
    assert all(timeout["read"] == 7.5 for timeout in sent)


def test_chat_completion_without_retries_tries_once(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sent = _timing_out_transport(monkeypatch)
    client = get_llm_client(_settings(llm_api_key="sk-test", llm_max_retries=0))

    with pytest.raises(LLMUnavailableError) as caught:
        asyncio.run(client.complete(system="s", prompt="p", max_tokens=10))

    assert isinstance(caught.value.__cause__, openai.APITimeoutError)
    assert len(sent) == 1
    assert sent[0]["read"] == 30.0


def test_embeddings_time_out_with_configured_budget(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sent = _timing_out_transport(monkeypatch)
    waits: list[float] = []

    async def no_sleep(seconds: float) -> None:
        waits.append(seconds)

    provider = get_embedding_provider(
        _settings(
            embedding_api_key="sk-test",
            embedding_timeout_seconds=4.0,
            embedding_max_retries=1,
        )
    )
    assert isinstance(provider, OpenAIEmbeddingProvider)
    provider._sleep = no_sleep  # type: ignore[attr-defined]

    with pytest.raises(EmbeddingUnavailableError) as caught:
        asyncio.run(provider.embed(["xin chào"]))

    assert isinstance(caught.value.__cause__, openai.APITimeoutError)
    assert len(sent) == 2, "1 attempt + embedding_max_retries=1 retry"
    assert all(timeout["read"] == 4.0 for timeout in sent)
    assert waits == [], "a timeout is not a 429: no extra rate-limit waits"
