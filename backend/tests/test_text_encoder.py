"""Shared text encoder client and the semantic-citation encoder ranker."""

from __future__ import annotations

import http.client
import io
import json
import math
from array import array
from collections.abc import Sequence
from typing import Any

import pytest
from pydantic import ValidationError

from app.core.config import Settings
from app.services import semantic_citation as semantic
from app.services import text_encoder
from app.services.text_encoder import TextEncoder, TextEncoderError
from tests.test_t040_semantic_citation import _passage, _reference, _source


class _Response(io.BytesIO):
    def __enter__(self) -> _Response:
        return self

    def __exit__(self, *_args: object) -> None:
        self.close()


def _fake_opener(monkeypatch: pytest.MonkeyPatch, handler: Any) -> list[dict]:
    sent: list[dict] = []

    class Opener:
        def open(self, request: Any, timeout: float) -> _Response:
            payload = json.loads(request.data)
            sent.append(
                {"url": request.full_url, "headers": dict(request.headers), **payload}
            )
            return _Response(json.dumps(handler(request.full_url, payload)).encode())

    monkeypatch.setattr(
        text_encoder.urllib.request, "build_opener", lambda *_handlers: Opener()
    )
    return sent


def test_embed_batches_restores_index_order_and_normalizes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def handler(_url: str, payload: dict) -> dict:
        rows = [
            {"index": index, "embedding": [float(len(text)), 0.0]}
            for index, text in enumerate(payload["input"])
        ]
        return {"data": list(reversed(rows))}

    sent = _fake_opener(monkeypatch, handler)
    encoder = TextEncoder(
        "https://encoder.test/v1", "m", api_key="k", document_prefix="passage: "
    )
    texts = [f"t{index}" for index in range(40)]

    vectors = encoder.embed(texts, kind="document")

    assert [len(item["input"]) for item in sent] == [32, 8]
    assert sent[0]["input"][0] == "passage: t0"
    assert sent[0]["url"] == "https://encoder.test/v1/embeddings"
    assert sent[0]["headers"]["Authorization"] == "Bearer k"
    assert len(vectors) == 40
    assert all(math.isclose(vector[0], 1.0) for vector in vectors)


def test_embed_accepts_rows_without_index_in_input_order(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Gemini's OpenAI-compatible endpoint returns rows without `index`.
    _fake_opener(
        monkeypatch,
        lambda _url, payload: {
            "data": [
                {"embedding": [1.0, 0.0] if text == "x" else [0.0, 1.0]}
                for text in payload["input"]
            ]
        },
    )

    vectors = TextEncoder("http://encoder", "m").embed(["x", "y"], kind="query")

    assert [list(vector) for vector in vectors] == [[1.0, 0.0], [0.0, 1.0]]


def test_rerank_maps_scores_back_to_input_order(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _fake_opener(
        monkeypatch,
        lambda _url, _payload: [{"index": 1, "score": 0.9}, {"index": 0, "score": 0.1}],
    )
    encoder = TextEncoder("http://encoder", "m", rerank_url="http://reranker")

    assert encoder.rerank("q", ["a", "b"]) == [0.1, 0.9]
    assert TextEncoder("http://encoder", "m").rerank("q", ["a"]) is None


def test_invalid_response_raises_sanitized_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _fake_opener(monkeypatch, lambda _url, _payload: {"data": []})
    with pytest.raises(TextEncoderError) as error:
        TextEncoder("http://encoder", "m").embed(["secret claim"], kind="query")
    assert "secret claim" not in str(error.value)


def test_truncated_response_becomes_encoder_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # A connection cut mid-body raises IncompleteRead, which is not an OSError;
    # it must still become TextEncoderError so the ranker falls back to BM25.
    def cut(_url: str, _payload: dict) -> dict:
        raise http.client.IncompleteRead(b"{")

    _fake_opener(monkeypatch, cut)
    with pytest.raises(TextEncoderError):
        TextEncoder("http://encoder", "m").embed(["claim"], kind="query")


def test_settings_reject_api_key_over_plain_http() -> None:
    with pytest.raises(ValidationError, match="HTTPS"):
        Settings(
            semantic_encoder_url="http://encoder.test/v1",
            semantic_encoder_model="m",
            semantic_encoder_api_key="k",
        )
    with pytest.raises(ValidationError, match="semantic_encoder_model"):
        Settings(semantic_encoder_url="http://encoder:80/v1")


class _FakeEncoder:
    model = "fake"
    fingerprint = "fp"

    def __init__(self, *, rerank_url: str = "", fail: bool = False) -> None:
        self.rerank_url = rerank_url
        self.fail = fail
        self.queries: list[str] = []
        self.document_batches = 0

    def embed(self, texts: Sequence[str], *, kind: str) -> list[array]:
        if self.fail:
            raise TextEncoderError("encoder unavailable")
        if kind == "query":
            self.queries.extend(texts)
            return [array("f", [1.0, 0.0])]
        self.document_batches += 1
        # Passage i points further from the query as i grows.
        return [
            array("f", [math.cos(index / 10), math.sin(index / 10)])
            for index in range(len(texts))
        ]

    def rerank(self, _query: str, texts: Sequence[str]) -> list[float] | None:
        if not self.rerank_url:
            return None
        return [1.0 if "reranked" in text else 0.0 for text in texts]


class _MemoryStorage:
    def __init__(self) -> None:
        self.objects: dict[str, bytes] = {}

    def get_bounded(self, key: str, _limit: int) -> bytes:
        return self.objects[key]

    def put_private_object(
        self, key: str, data: bytes, *, content_type: str, metadata: dict
    ) -> None:
        self.objects[key] = data


def _passages() -> list[semantic.SemanticSourcePassage]:
    return [
        _passage(passage_id=f"p-{index}", text=f"Passage {index} text.")
        for index in range(4)
    ] + [_passage(passage_id="p-4", text="Passage reranked to the top.")]


def test_encoder_ranker_redacts_claim_reranks_and_caches_source_vectors() -> None:
    storage = _MemoryStorage()
    passages = _passages()
    encoder = _FakeEncoder(rerank_url="http://reranker")
    ranker = semantic.EncoderRanker(
        encoder,
        sensitive_values=("student@example.test",),
        storage=storage,
        cache_prefix="semantic",
    )

    order = ranker("Claim by student@example.test", passages)

    assert order == ["p-4", "p-0", "p-1", "p-2", "p-3"]
    assert encoder.queries == ["Claim by [REDACTED]"]
    assert encoder.document_batches == 1
    assert len(storage.objects) == 1

    # A later job reads the cached vectors instead of re-encoding the source.
    plain = _FakeEncoder()
    later = semantic.EncoderRanker(plain, storage=storage, cache_prefix="semantic")
    assert later("Claim", passages) == ["p-0", "p-1", "p-2", "p-3", "p-4"]
    assert plain.document_batches == 0


def test_encoder_failure_falls_back_to_bm25_passages() -> None:
    passages = [
        _passage(passage_id="p-1", text="Transformer achieves 28.4 BLEU."),
        _passage(passage_id="p-2", text="Hardware settings are unrelated."),
    ]
    ranker = semantic.EncoderRanker(_FakeEncoder(fail=True))
    claim = "Transformer achieves 28.4 BLEU on translation [1]."
    pair = semantic.ClaimCitationPair(
        pair_id="pair-1",
        claim_id="claim-1",
        mention_id="m-1",
        reference_id="ref-1",
        claim=claim,
        context="",
        claim_anchor=semantic.SemanticClaimAnchor(
            page_number=1, element_id="p-1", start=0, end=len(claim)
        ),
        extraction_method=semantic.ExtractionMethod.SENTENCE,
    )

    result = semantic.evaluate_claim(
        pair, _reference(), _source(passages=passages), None, dense_ranker=ranker
    )

    assert ranker.failures == 1
    assert result.source_passages[0].passage_id == "p-1"
