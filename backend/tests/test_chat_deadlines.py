"""Per-turn deadlines cut slow provider calls (no DB).

The provider either asks for ``Retry-After: 120`` or never answers. Every
call runs under a 10 s guard: without a deadline in the product code the
guard expires and the test fails instead of hanging for minutes.
"""

from __future__ import annotations

import asyncio
import logging
import re
import time
import uuid
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
    handle_chat,
)
from app.services.embeddings import OpenAIEmbeddingProvider
from app.services.rag import FakeLLMClient, OpenAIChatClient, _vector_ranked
from tests.openai_mock import OpenAIMock, chat_completion, hang, retry_after
from tests.test_llm_failures import UNKNOWN_MESSAGE, _install_fake_retrieval, _scope
from tests.test_summary_cache_failures import _FakeSession

GUARD_SECONDS = 10.0

# The SDK imports its resource modules lazily on first use, which can take
# longer than these sub-second test deadlines: load them once up front.
_warm = openai.AsyncOpenAI(api_key="sk-warm-up")
_ = (_warm.chat.completions, _warm.embeddings)


def _settings(**overrides: object) -> Settings:
    return Settings(
        postgres_db="db", postgres_user="user", postgres_password="pw", **overrides
    )


def _use_settings(monkeypatch: pytest.MonkeyPatch, **overrides: object) -> Settings:
    settings = _settings(**overrides)
    monkeypatch.setattr(chat_service, "get_settings", lambda: settings)
    return settings


def _product_client() -> OpenAIChatClient:
    # Production defaults: 30 s timeout, 1 retry. Only the deadline can cut it.
    return OpenAIChatClient("sk-test", "gpt-test", timeout_seconds=30, max_retries=1)


def _guarded(coro):
    """Run *coro*; fail (not hang) if nothing cuts it within GUARD_SECONDS.

    Returns (result, elapsed seconds, tasks still alive besides this one).
    """

    async def runner():
        started = time.perf_counter()
        result = await asyncio.wait_for(coro, GUARD_SECONDS)
        elapsed = time.perf_counter() - started
        leftover = {t for t in asyncio.all_tasks() if t is not asyncio.current_task()}
        return result, elapsed, leftover

    try:
        return asyncio.run(runner())
    except TimeoutError:
        pytest.fail(f"no deadline: still waiting after the {GUARD_SECONDS}s guard")


def test_deadline_defaults() -> None:
    settings = _settings()
    assert settings.chat_turn_deadline_seconds == 25.0
    assert settings.llm_router_timeout_seconds == 8.0
    assert settings.summary_deadline_seconds == 90.0


@pytest.mark.parametrize(
    "field",
    [
        "chat_turn_deadline_seconds",
        "llm_router_timeout_seconds",
        "summary_deadline_seconds",
    ],
)
def test_deadlines_must_be_positive(field: str) -> None:
    with pytest.raises(ValueError):
        _settings(**{field: 0})


def test_answer_is_cut_by_the_turn_deadline_on_retry_after_120(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    mock = OpenAIMock(retry_after(120)).install(monkeypatch)
    _use_settings(monkeypatch, chat_turn_deadline_seconds=0.5)
    monkeypatch.setattr(chat_service, "_rag_llm_client", _product_client)
    _install_fake_retrieval(monkeypatch)

    response, elapsed, leftover = _guarded(
        chat_service._handle_ask_about_requirement(
            None, _scope(), "Bài này có kiểm thử không?"  # type: ignore[arg-type]
        )
    )

    assert elapsed < 2.0
    assert len(mock.requests) == 1, "cut while the SDK waited for Retry-After"
    assert response.reply.splitlines()[0] == ANSWER_FALLBACK_TEXT
    assert response.citations and response.citations[0].page == 2
    assert response.llm_unavailable is True
    assert mock.clients_closed == mock.clients_opened == 1
    assert leftover == set()


def test_answer_is_cut_when_the_provider_never_answers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    mock = OpenAIMock(hang).install(monkeypatch)
    _use_settings(monkeypatch, chat_turn_deadline_seconds=0.5)
    monkeypatch.setattr(chat_service, "_rag_llm_client", _product_client)
    _install_fake_retrieval(monkeypatch)

    response, elapsed, leftover = _guarded(
        chat_service._handle_ask_about_requirement(
            None, _scope(), "Bài này có kiểm thử không?"  # type: ignore[arg-type]
        )
    )

    assert elapsed < 2.0
    assert response.llm_unavailable is True
    assert mock.cancelled == ["/v1/chat/completions"], "in-flight request cancelled"
    assert mock.clients_closed == mock.clients_opened == 1
    assert leftover == set()


def test_router_has_its_own_short_timeout(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    mock = OpenAIMock(hang).install(monkeypatch)
    _use_settings(
        monkeypatch, llm_router_timeout_seconds=0.3, chat_turn_deadline_seconds=5
    )
    monkeypatch.setattr(chat_service, "_rag_llm_client", _product_client)
    user = SimpleNamespace(id=uuid.uuid4(), roles=["TEACHER"])

    with caplog.at_level(logging.WARNING, logger="app.services.chat"):
        response, elapsed, leftover = _guarded(
            handle_chat(
                None,  # type: ignore[arg-type]
                user=user,  # type: ignore[arg-type]
                message=UNKNOWN_MESSAGE,
                course_id=None,
                assignment_id=None,
            )
        )

    assert elapsed < 1.5, "router timeout (0.3 s), not the turn deadline (5 s)"
    assert response.intent == Intent.UNKNOWN
    assert response.reply.startswith("Mình chưa hiểu câu hỏi này.")
    assert len(mock.requests) == 1
    assert mock.cancelled == ["/v1/chat/completions"]
    assert mock.clients_closed == mock.clients_opened == 1
    assert leftover == set()
    assert any(r.levelno == logging.WARNING for r in caplog.records)


def test_router_does_not_retry(monkeypatch: pytest.MonkeyPatch) -> None:
    mock = OpenAIMock(
        lambda _r: httpx.Response(503, headers={"retry-after-ms": "1"})
    ).install(monkeypatch)
    _use_settings(monkeypatch)
    monkeypatch.setattr(chat_service, "_rag_llm_client", _product_client)
    user = SimpleNamespace(id=uuid.uuid4(), roles=["TEACHER"])

    response, _elapsed, _leftover = _guarded(
        handle_chat(
            None,  # type: ignore[arg-type]
            user=user,  # type: ignore[arg-type]
            message=UNKNOWN_MESSAGE,
            course_id=None,
            assignment_id=None,
        )
    )
    assert response.intent == Intent.UNKNOWN
    assert len(mock.requests) == 1, "router: no retry even if the client has 1"


def test_summary_is_cut_by_the_summary_deadline(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    mock = OpenAIMock(retry_after(120)).install(monkeypatch)
    _use_settings(
        monkeypatch, summary_deadline_seconds=0.5, chat_turn_deadline_seconds=5
    )
    monkeypatch.setattr(chat_service, "_rag_llm_client", _product_client)
    session = _FakeSession(existing=None)

    response, elapsed, leftover = _guarded(
        chat_service._handle_summarize_submission(session, _scope())  # type: ignore[arg-type]
    )

    assert elapsed < 2.0, "summary deadline (0.5 s), not the turn deadline (5 s)"
    assert response.reply == SUMMARY_UNAVAILABLE_TEXT
    assert response.llm_unavailable is True
    assert session.added == [] and session.commits == 0, "nothing cached"
    assert mock.clients_closed == mock.clients_opened
    assert leftover == set()


def test_summary_may_outlive_the_turn_deadline(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def slow_success(_request: httpx.Request) -> httpx.Response:
        await asyncio.sleep(0.6)
        return httpx.Response(200, json=chat_completion("Tóm tắt thật"))

    OpenAIMock(slow_success).install(monkeypatch)
    _use_settings(
        monkeypatch, chat_turn_deadline_seconds=0.2, summary_deadline_seconds=5
    )
    monkeypatch.setattr(chat_service, "_rag_llm_client", _product_client)
    session = _FakeSession(existing=None)

    response, _elapsed, _leftover = _guarded(
        chat_service._handle_summarize_submission(session, _scope())  # type: ignore[arg-type]
    )
    assert response.reply == "Tóm tắt thật"
    assert response.llm_unavailable is False
    assert session.commits == 1


def test_query_embedding_is_cut_by_its_time_budget(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    mock = OpenAIMock(retry_after(120)).install(monkeypatch)
    provider = OpenAIEmbeddingProvider(
        "sk-test", "emb", timeout_seconds=20, max_retries=2, rate_limit_retries=0
    )

    with caplog.at_level(logging.WARNING, logger="app.services.rag"):
        ids, elapsed, leftover = _guarded(
            _vector_ranked(
                None, [uuid.uuid4()], "kiểm thử", provider, timeout_seconds=0.4  # type: ignore[arg-type]
            )
        )

    assert ids == []
    assert elapsed < 2.0
    assert len(mock.requests) == 1
    assert mock.clients_closed == mock.clients_opened == 1
    assert leftover == set()
    assert any(r.levelno == logging.WARNING for r in caplog.records)


def test_no_budget_left_skips_the_llm_call(monkeypatch: pytest.MonkeyPatch) -> None:
    client = FakeLLMClient("không được gọi")
    _use_settings(monkeypatch, chat_turn_deadline_seconds=0.001)
    monkeypatch.setattr(chat_service, "_rag_llm_client", lambda: client)
    _install_fake_retrieval(monkeypatch)

    async def ask_after_budget_is_spent():
        deadline = chat_service.TurnDeadline.start()
        await asyncio.sleep(0.01)
        return await chat_service._handle_ask_about_requirement(
            None, _scope(), "Bài này có kiểm thử không?", deadline=deadline  # type: ignore[arg-type]
        )

    response, _elapsed, _leftover = _guarded(ask_after_budget_is_spent())
    assert response.llm_unavailable is True
    assert client.calls == []


# --- query-embedding cap ------------------------------------------------------


def test_query_embedding_cap_default() -> None:
    assert _settings().query_embedding_timeout_seconds == 6.0
    with pytest.raises(ValueError):
        _settings(query_embedding_timeout_seconds=0)


def test_hanging_embedding_still_leaves_time_for_the_llm_answer(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Embedding hangs, the LLM answers at once: the answer must be the LLM's.

    Retrieval runs the real ``_vector_ranked`` with the budget the chat
    passes, then returns one fixed chunk (as full-text retrieval would).
    """
    from app.services import rag as rag_service
    from tests.test_llm_failures import _retrieved

    chunks = _retrieved()

    async def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/embeddings"):
            return await hang(request)
        cited = re.search(rb"\[chunk:([0-9a-f-]{36})\]", request.content)
        reply = f"Có, nhóm dùng pytest [chunk:{cited.group(1).decode()}]."
        return httpx.Response(200, json=chat_completion(reply))

    mock = OpenAIMock(handler).install(monkeypatch)
    _use_settings(
        monkeypatch,
        chat_turn_deadline_seconds=2.0,
        query_embedding_timeout_seconds=0.3,
    )
    monkeypatch.setattr(chat_service, "_rag_llm_client", _product_client)
    _install_fake_retrieval(monkeypatch)
    provider = OpenAIEmbeddingProvider(
        "sk-test", "emb", timeout_seconds=20, max_retries=2, rate_limit_retries=0
    )
    monkeypatch.setattr(chat_service, "_rag_embedding_provider", lambda: provider)

    async def retrieve(
        db, version_ids, query, *, provider=None, embed_timeout=None, **_
    ):
        await rag_service._vector_ranked(
            db, version_ids, query, provider, timeout_seconds=embed_timeout
        )
        return chunks

    monkeypatch.setattr(chat_service, "retrieve_chunks", retrieve)

    response, elapsed, leftover = _guarded(
        chat_service._handle_ask_about_requirement(
            None, _scope(), "Bài này có kiểm thử không?"  # type: ignore[arg-type]
        )
    )

    assert response.llm_unavailable is False, "the LLM still had time to answer"
    assert response.reply.startswith("Có, nhóm dùng pytest")
    assert 0.25 <= elapsed < 1.5, "cut at the 0.3 s cap, not the 2 s turn budget"
    assert mock.cancelled == ["/v1/embeddings"]
    assert mock.clients_closed == mock.clients_opened == 2
    assert leftover == set()
