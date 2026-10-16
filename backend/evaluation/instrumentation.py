"""Benchmark-only instrumentation around ``app.services.chat``.

Nothing here changes product code: each ablation configuration is applied by
swapping module attributes for the duration of a ``with`` block and restoring
them afterwards.

- ``TokenLedger`` + ``CountingChatClient`` / ``CountingEmbeddingProvider``
  record the token usage the OpenAI API itself reports (``response.usage``),
  per purpose (answer, router, summary, judge, embedding), and abort the run
  once LLM usage crosses a hard budget.
- ``RetrievalRecorder`` keeps every chunk list ``retrieve_chunks`` returns,
  with full text, so retrieval is scored on what the retriever actually
  produced rather than on what the answer happened to cite.
- ``ablation_config`` applies one of the three configurations.
"""

from __future__ import annotations

import contextlib
from collections import defaultdict
from collections.abc import Iterator
from dataclasses import dataclass, field
from typing import Any

from pydantic_settings import BaseSettings, SettingsConfigDict

from app.core.config import ROOT_ENV_FILE, Settings, get_settings
from app.services import chat as chat_service
from app.services import rag as rag_service
from app.services.chat import Intent
from app.services.embeddings import OpenAIEmbeddingProvider
from app.services.rag import LLMNotConfiguredError, OpenAIChatClient

LLM_TOKEN_BUDGET = 2_000_000


def _purpose_of(system: str) -> str:
    """Which pipeline step a chat-completion call belongs to."""
    if system == chat_service.ROUTER_SYSTEM_PROMPT:
        return "router"
    if system == rag_service.ANSWER_SYSTEM_PROMPT:
        return "answer"
    if system in (
        rag_service.SUMMARY_SYSTEM_PROMPT,
        rag_service.SUMMARY_MAP_SYSTEM_PROMPT,
    ):
        return "summary"
    return "judge"


class TokenBudgetExceeded(RuntimeError):
    pass


@dataclass
class TokenLedger:
    llm_budget: int = LLM_TOKEN_BUDGET
    llm: dict[str, dict[str, int]] = field(
        default_factory=lambda: defaultdict(
            lambda: {"calls": 0, "prompt": 0, "completion": 0}
        )
    )
    embedding: dict[str, int] = field(default_factory=lambda: {"calls": 0, "tokens": 0})
    # Provider calls that failed (after the SDK's retries), per purpose.
    errors: dict[str, int] = field(default_factory=lambda: defaultdict(int))

    exceeded: bool = False

    @property
    def llm_total(self) -> int:
        return sum(v["prompt"] + v["completion"] for v in self.llm.values())

    def add_llm(self, purpose: str, prompt: int, completion: int) -> None:
        bucket = self.llm[purpose]
        bucket["calls"] += 1
        bucket["prompt"] += prompt
        bucket["completion"] += completion
        if self.llm_total > self.llm_budget:
            # Flag as well as raise: chat._route_unknown swallows exceptions,
            # so the runner also checks this flag after every case.
            self.exceeded = True
            raise TokenBudgetExceeded(
                f"LLM token budget exceeded: {self.llm_total} > {self.llm_budget}"
            )

    def add_error(self, purpose: str) -> None:
        self.errors[purpose] += 1

    def add_embedding(self, tokens: int) -> None:
        self.embedding["calls"] += 1
        self.embedding["tokens"] += tokens

    def snapshot(self) -> dict[str, Any]:
        return {
            "llm_total_tokens": self.llm_total,
            "llm_by_purpose": {k: dict(v) for k, v in self.llm.items()},
            "embedding": dict(self.embedding),
            "errors": dict(self.errors),
            "llm_budget": self.llm_budget,
            "budget_exceeded": self.exceeded,
        }


class CountingChatClient(OpenAIChatClient):
    """The product's ``OpenAIChatClient`` (same request, error wrapping and
    timeout/retry settings) plus usage accounting through its hooks.

    ``calls`` counts every completed or failed call made through this client
    *and the copies the chat makes of it* (``with_options`` for the summary
    and router paths share ``_stats``); the cache cases rely on it.
    """

    def __init__(
        self,
        ledger: TokenLedger,
        *,
        api_key: str,
        model: str,
        settings: Settings | None = None,
    ) -> None:
        settings = settings or get_settings()
        super().__init__(
            api_key,
            model,
            timeout_seconds=settings.llm_timeout_seconds,
            max_retries=settings.llm_max_retries,
        )
        self._ledger = ledger
        self._stats = {"calls": 0}

    @property
    def calls(self) -> int:
        return self._stats["calls"]

    def _record_success(self, system: str, response: Any) -> None:
        self._stats["calls"] += 1
        usage = response.usage
        self._ledger.add_llm(
            _purpose_of(system),
            usage.prompt_tokens if usage else 0,
            usage.completion_tokens if usage else 0,
        )

    def _record_failure(self, system: str) -> None:
        self._stats["calls"] += 1
        self._ledger.add_error(_purpose_of(system))


class CountingEmbeddingProvider(OpenAIEmbeddingProvider):
    """The product's embedding provider, configured like the chat's query
    embedding (``get_embedding_provider(interactive=True)``), plus usage
    accounting through its hooks."""

    def __init__(
        self,
        ledger: TokenLedger,
        *,
        api_key: str,
        model: str,
        settings: Settings | None = None,
    ) -> None:
        settings = settings or get_settings()
        super().__init__(
            api_key,
            model,
            timeout_seconds=settings.embedding_timeout_seconds,
            max_retries=settings.embedding_max_retries,
            rate_limit_retries=0,
        )
        self._ledger = ledger

    def _record_response(self, response: Any) -> None:
        self._ledger.add_embedding(response.usage.total_tokens if response.usage else 0)

    def _record_failure(self) -> None:
        self._ledger.add_error("embedding")


def make_llm_client(ledger: TokenLedger) -> CountingChatClient:
    settings = get_settings()
    return CountingChatClient(
        ledger,
        api_key=settings.llm_api_key.strip(),
        model=settings.llm_model,
        settings=settings,
    )


class _JudgeSettings(BaseSettings):
    """``JUDGE_LLM_MODEL`` from the environment or the root ``.env``."""

    model_config = SettingsConfigDict(
        env_file=ROOT_ENV_FILE, env_file_encoding="utf-8", extra="ignore"
    )
    judge_llm_model: str = ""


def judge_model_name() -> str:
    """The judge's model: ``JUDGE_LLM_MODEL`` if set, else the system's
    ``LLM_MODEL`` (then the judge grades its own model's answers)."""
    return _JudgeSettings().judge_llm_model.strip() or get_settings().llm_model


def make_judge_client(ledger: TokenLedger) -> CountingChatClient:
    """Same OpenAI key as the system; only the model can differ."""
    settings = get_settings()
    return CountingChatClient(
        ledger,
        api_key=settings.llm_api_key.strip(),
        model=judge_model_name(),
        settings=settings,
    )


def make_embedding_provider(ledger: TokenLedger) -> CountingEmbeddingProvider:
    settings = get_settings()
    return CountingEmbeddingProvider(
        ledger,
        api_key=settings.embedding_api_key.strip(),
        model=settings.embedding_model,
        settings=settings,
    )


class RetrievalRecorder:
    """Wraps ``chat.retrieve_chunks`` and keeps each call's result."""

    def __init__(self) -> None:
        self.calls: list[list[Any]] = []

    def reset(self) -> None:
        self.calls = []

    def wrap(self, original: Any) -> Any:
        async def recording(*args: Any, **kwargs: Any) -> Any:
            chunks = await original(*args, **kwargs)
            self.calls.append(list(chunks))
            return chunks

        return recording


class _NoLLM:
    """Stands in for the LLM in the rule-only configuration."""

    model_name = "disabled"

    async def complete(self, *, system: str, prompt: str, max_tokens: int) -> str:
        raise LLMNotConfiguredError("LLM disabled in the rule_only configuration")


async def _no_route(message: str, history: Any, deadline: Any = None) -> None:
    return None


async def _no_keyword(db: Any, version_ids: Any, query: str) -> list[Any]:
    return []


CONFIGS = ("rule_only", "rag_only", "hybrid")

CONFIG_DESCRIPTIONS = {
    "rule_only": (
        "Bộ phân loại intent theo từ khóa + truy vấn SQL; không LLM router, "
        "không LLM soạn câu trả lời/tóm tắt; truy hồi chỉ full-text "
        "(keyword) - không vector."
    ),
    "rag_only": (
        "Không bộ phân loại intent: mọi câu đi thẳng vào nhánh "
        "ASK_ABOUT_REQUIREMENT (truy hồi + LLM soạn câu trả lời có trích "
        "dẫn); truy hồi chỉ vector (pgvector) - không full-text."
    ),
    "hybrid": (
        "Hệ thống hiện tại: từ khóa -> (UNKNOWN) LLM router; SQL cho số "
        "liệu; truy hồi lai vector + full-text (RRF); LLM soạn câu trả lời "
        "và tóm tắt (có cache)."
    ),
}


@contextlib.contextmanager
def ablation_config(
    name: str,
    ledger: TokenLedger,
    recorder: RetrievalRecorder,
) -> Iterator[CountingChatClient | None]:
    """Apply configuration *name* to ``app.services.chat`` while active.

    Yields the counting LLM client in use (None for rule_only).
    """
    if name not in CONFIGS:
        raise ValueError(f"unknown configuration {name!r}")
    saved = {
        "classify_intent": chat_service.classify_intent,
        "_route_unknown": chat_service._route_unknown,
        "_rag_llm_client": chat_service._rag_llm_client,
        "_rag_embedding_provider": chat_service._rag_embedding_provider,
        "retrieve_chunks": chat_service.retrieve_chunks,
    }
    saved_keyword = rag_service._keyword_ranked
    llm: CountingChatClient | None = None
    try:
        chat_service.retrieve_chunks = recorder.wrap(saved["retrieve_chunks"])
        if name == "rule_only":
            chat_service._route_unknown = _no_route
            chat_service._rag_llm_client = lambda: _NoLLM()
            chat_service._rag_embedding_provider = lambda: None
        else:
            llm = make_llm_client(ledger)
            embedder = make_embedding_provider(ledger)
            chat_service._rag_llm_client = lambda: llm
            chat_service._rag_embedding_provider = lambda: embedder
            if name == "rag_only":
                chat_service.classify_intent = (
                    lambda message: Intent.ASK_ABOUT_REQUIREMENT
                )
                rag_service._keyword_ranked = _no_keyword
        yield llm
    finally:
        for attr, value in saved.items():
            setattr(chat_service, attr, value)
        rag_service._keyword_ranked = saved_keyword
