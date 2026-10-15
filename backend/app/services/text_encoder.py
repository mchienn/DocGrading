"""Shared multilingual text encoder client.

Speaks two de-facto standard HTTP protocols so the model behind them can be swapped
by configuration: OpenAI-compatible ``POST {url}/embeddings`` (served by Hugging
Face Text Embeddings Inference, OpenAI, Gemini, vLLM, Ollama...) and Text
Embeddings Inference ``POST {url}/rerank`` for cross-encoder rerankers.
"""

from __future__ import annotations

import hashlib
import http.client
import json
import math
import urllib.error
import urllib.request
from array import array
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any, Literal

_BATCH_SIZE = 32
_TIMEOUT_SECONDS = 60
_MAX_RESPONSE_BYTES = 64_000_000
_MAX_TEXT_CHARS = 8_000

TextKind = Literal["query", "document"]


class TextEncoderError(RuntimeError):
    """Sanitized encoder failure; request texts are never included."""


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args: Any, **kwargs: Any) -> None:
        return None


def _normalized(values: Sequence[float]) -> array:
    vector = array("f", (float(value) for value in values))
    norm = math.sqrt(sum(value * value for value in vector))
    if not vector or not math.isfinite(norm) or norm == 0:
        raise TextEncoderError("encoder returned an invalid vector")
    return array("f", (value / norm for value in vector))


def similarity_order(query: array, documents: Sequence[array]) -> list[int]:
    """Document indexes by descending cosine similarity (vectors are normalized)."""
    scores = [sum(a * b for a, b in zip(query, doc, strict=True)) for doc in documents]
    return sorted(range(len(documents)), key=lambda index: (-scores[index], index))


@dataclass(frozen=True)
class TextEncoder:
    embeddings_url: str
    model: str
    api_key: str = ""
    query_prefix: str = ""
    document_prefix: str = ""
    rerank_url: str = ""

    @property
    def fingerprint(self) -> str:
        """Stable ID of everything that changes document vectors."""
        material = f"{self.model}\x00{self.document_prefix}".encode()
        return hashlib.sha256(material).hexdigest()[:16]

    def embed(self, texts: Sequence[str], *, kind: TextKind) -> list[array]:
        prefix = self.query_prefix if kind == "query" else self.document_prefix
        vectors: list[array] = []
        for start in range(0, len(texts), _BATCH_SIZE):
            batch = [
                prefix + text[:_MAX_TEXT_CHARS]
                for text in texts[start : start + _BATCH_SIZE]
            ]
            body = self._post(
                f"{self.embeddings_url.rstrip('/')}/embeddings",
                {"model": self.model, "input": batch},
            )
            rows = body.get("data") if isinstance(body, dict) else None
            if not isinstance(rows, list) or len(rows) != len(batch):
                raise TextEncoderError("encoder returned an invalid response")
            try:
                # Gemini's OpenAI-compatible endpoint omits `index`; rows then
                # arrive in input order.
                rows = sorted(
                    enumerate(rows), key=lambda item: int(item[1].get("index", item[0]))
                )
                vectors.extend(_normalized(row["embedding"]) for _, row in rows)
            except (KeyError, TypeError, ValueError) as exc:
                raise TextEncoderError("encoder returned an invalid response") from exc
        if len({len(vector) for vector in vectors}) > 1:
            raise TextEncoderError("encoder returned mixed vector sizes")
        return vectors

    def rerank(self, query: str, texts: Sequence[str]) -> list[float] | None:
        """Cross-encoder relevance per text, or None when no reranker is set."""
        if not self.rerank_url or not texts:
            return None
        body = self._post(
            f"{self.rerank_url.rstrip('/')}/rerank",
            {
                "query": query[:_MAX_TEXT_CHARS],
                "texts": [text[:_MAX_TEXT_CHARS] for text in texts],
                "truncate": True,
            },
        )
        scores = [float("-inf")] * len(texts)
        try:
            for row in body:
                scores[int(row["index"])] = float(row["score"])
        except (KeyError, TypeError, ValueError, IndexError) as exc:
            raise TextEncoderError("reranker returned an invalid response") from exc
        if any(not math.isfinite(score) for score in scores):
            raise TextEncoderError("reranker returned an invalid response")
        return scores

    def _post(self, url: str, payload: dict[str, Any]) -> Any:
        headers = {
            "Accept": "application/json",
            "Content-Type": "application/json",
            "User-Agent": "DocGrading/1.0",
        }
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        request = urllib.request.Request(
            url,
            data=json.dumps(payload, ensure_ascii=False).encode(),
            headers=headers,
            method="POST",
        )
        opener = urllib.request.build_opener(
            urllib.request.ProxyHandler({}), _NoRedirect()
        )
        try:
            with opener.open(request, timeout=_TIMEOUT_SECONDS) as response:
                raw = response.read(_MAX_RESPONSE_BYTES + 1)
        except (
            urllib.error.URLError,
            http.client.HTTPException,
            OSError,
            ValueError,
        ) as exc:
            raise TextEncoderError("encoder unavailable") from exc
        if len(raw) > _MAX_RESPONSE_BYTES:
            raise TextEncoderError("encoder response too large")
        try:
            return json.loads(raw)
        except ValueError as exc:
            raise TextEncoderError("encoder returned an invalid response") from exc


def encoder_from_settings(settings: Any | None) -> TextEncoder | None:
    if settings is None:
        return None
    url = str(getattr(settings, "semantic_encoder_url", "") or "").strip()
    model = str(getattr(settings, "semantic_encoder_model", "") or "").strip()
    if not url or not model:
        return None
    key = getattr(settings, "semantic_encoder_api_key", "")
    return TextEncoder(
        embeddings_url=url,
        model=model,
        api_key=key.get_secret_value() if hasattr(key, "get_secret_value") else key,
        query_prefix=getattr(settings, "semantic_encoder_query_prefix", ""),
        document_prefix=getattr(settings, "semantic_encoder_document_prefix", ""),
        rerank_url=str(getattr(settings, "semantic_reranker_url", "") or "").strip(),
    )
