"""Embedding providers for RAG retrieval.

Callers depend only on ``EmbeddingProvider``; which implementation runs is
decided by ``EMBEDDING_PROVIDER`` in config. A missing API key never fails at
import/boot time — ``EmbeddingNotConfiguredError`` is raised only when a
provider is actually asked to embed, so chunking and keyword-only retrieval
keep working without any key.
"""

from __future__ import annotations

import asyncio
import hashlib
import math
import re
from collections.abc import Awaitable, Callable
from typing import Protocol

from app.core.config import Settings, get_settings
from app.models.chunk import EMBEDDING_DIMENSIONS


class EmbeddingNotConfiguredError(RuntimeError):
    """The configured embedding provider cannot be called (e.g. no API key)."""


class EmbeddingProvider(Protocol):
    model_name: str

    async def embed(self, texts: list[str]) -> list[list[float]]: ...


def _is_rate_limited(exc: BaseException) -> bool:
    return getattr(exc, "status_code", None) == 429


class OpenAIEmbeddingProvider:
    # Low-tier accounts get ~40k tokens/minute while one 100-chunk batch is
    # ~16k tokens, so 429s are expected during backfills: wait for the
    # per-minute window to reset instead of failing the whole run.
    RATE_LIMIT_RETRIES = 6
    RATE_LIMIT_WAIT_SECONDS = 20.0

    def __init__(
        self,
        api_key: str,
        model: str,
        *,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        self._api_key = api_key
        self.model_name = model
        self._sleep = sleep

    async def embed(self, texts: list[str]) -> list[list[float]]:
        if not self._api_key:
            raise EmbeddingNotConfiguredError(
                "EMBEDDING_API_KEY is not set; cannot call the OpenAI embeddings API"
            )
        if not texts:
            return []
        for attempt in range(self.RATE_LIMIT_RETRIES + 1):
            try:
                return await self._request(texts)
            except Exception as exc:
                if not _is_rate_limited(exc) or attempt == self.RATE_LIMIT_RETRIES:
                    raise
                await self._sleep(self.RATE_LIMIT_WAIT_SECONDS * (attempt + 1))
        raise AssertionError("unreachable")

    async def _request(self, texts: list[str]) -> list[list[float]]:
        # Imported lazily so the SDK is only loaded when embeddings are used.
        from openai import AsyncOpenAI

        client = AsyncOpenAI(api_key=self._api_key)
        try:
            response = await client.embeddings.create(
                model=self.model_name,
                input=texts,
                dimensions=EMBEDDING_DIMENSIONS,
            )
        finally:
            await client.close()
        ordered = sorted(response.data, key=lambda item: item.index)
        return [list(item.embedding) for item in ordered]


_TOKEN_RE = re.compile(r"\w+", re.UNICODE)


class FakeEmbeddingProvider:
    """Deterministic, offline embeddings for tests and local development.

    Each word is hashed into a bucket (feature hashing) and the vector is
    L2-normalised, so texts sharing words have a higher cosine similarity —
    enough to exercise ranking logic without any network call.
    """

    model_name = "fake-hash-embedding"

    def __init__(self, dimensions: int = EMBEDDING_DIMENSIONS) -> None:
        self._dimensions = dimensions

    async def embed(self, texts: list[str]) -> list[list[float]]:
        return [self._embed_one(text) for text in texts]

    def _embed_one(self, text: str) -> list[float]:
        vector = [0.0] * self._dimensions
        for token in _TOKEN_RE.findall(text.lower()):
            digest = hashlib.sha256(token.encode("utf-8")).digest()
            bucket = int.from_bytes(digest[:4], "big") % self._dimensions
            vector[bucket] += 1.0 if digest[4] % 2 == 0 else -1.0
        norm = math.sqrt(sum(value * value for value in vector))
        if norm == 0:
            # Non-empty, deterministic fallback for texts with no word tokens.
            vector[0] = 1.0
            return vector
        return [value / norm for value in vector]


def get_embedding_provider(settings: Settings | None = None) -> EmbeddingProvider:
    settings = settings or get_settings()
    provider = settings.embedding_provider.strip().lower()
    if provider == "openai":
        return OpenAIEmbeddingProvider(
            api_key=settings.embedding_api_key.strip(),
            model=settings.embedding_model,
        )
    if provider == "fake":
        return FakeEmbeddingProvider()
    raise EmbeddingNotConfiguredError(
        f"Unknown EMBEDDING_PROVIDER {settings.embedding_provider!r} "
        "(expected 'openai' or 'fake')"
    )
