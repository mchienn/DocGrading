from __future__ import annotations

import asyncio
import math

import pytest

from app.core.config import Settings
from app.services.embeddings import (
    EmbeddingNotConfiguredError,
    FakeEmbeddingProvider,
    OpenAIEmbeddingProvider,
    get_embedding_provider,
)
from app.services.rag import (
    RRF_K,
    make_excerpt,
    query_terms,
    rrf_merge,
    strip_section_prefix,
)


def test_rrf_merge_rewards_items_present_in_both_lists() -> None:
    vector = ["a", "b", "c"]
    keyword = ["c", "d", "a"]
    merged = rrf_merge([vector, keyword], limit=10)
    # a: 1/61 + 1/63, c: 1/63 + 1/61 -> tie, a seen first; then b (1/62), d (1/62).
    assert [item for item, _ in merged] == ["a", "c", "b", "d"]
    assert merged[0][1] == pytest.approx(1 / (RRF_K + 1) + 1 / (RRF_K + 3))


def test_rrf_merge_orders_by_summed_reciprocal_rank() -> None:
    merged = rrf_merge([["x", "y", "z"], ["z", "y"]], limit=10)
    # z (1/61 + 1/63) edges out y (1/62 + 1/62); both beat x (1/61 alone).
    scores = dict(merged)
    assert scores["y"] == pytest.approx(2 / 62)
    assert scores["z"] == pytest.approx(1 / 63 + 1 / 61)
    assert [item for item, _ in merged] == ["z", "y", "x"]


def test_rrf_merge_respects_limit_and_handles_empty_lists() -> None:
    assert rrf_merge([[], []]) == []
    merged = rrf_merge([list("abcdefghij")], limit=5)
    assert [item for item, _ in merged] == list("abcde")


def test_rrf_merge_single_list_keeps_order() -> None:
    merged = rrf_merge([[], ["k1", "k2"]], limit=8)
    assert [item for item, _ in merged] == ["k1", "k2"]


def test_query_terms_drop_stopwords_and_keep_diacritics() -> None:
    assert query_terms("Kiểm thử của hệ thống và API") == [
        "kiểm",
        "thử",
        "hệ",
        "thống",
        "api",
    ]


def test_strip_section_prefix() -> None:
    assert strip_section_prefix("[2. Yêu cầu > 2.1]\nNội dung") == "Nội dung"
    assert strip_section_prefix("Không có prefix") == "Không có prefix"


def test_make_excerpt_centres_on_first_query_hit() -> None:
    text = "[Mục]\n" + "mở đầu " * 80 + "đoạn này bàn về kiểm thử đơn vị " + "kết " * 80
    excerpt = make_excerpt(text, "kiểm thử", width=120)
    assert "kiểm thử" in excerpt
    assert excerpt.startswith("…") and excerpt.endswith("…")
    assert len(excerpt) <= 122


def test_make_excerpt_matches_without_diacritics() -> None:
    text = "phần đầu " * 60 + "Kiểm Thử tự động" + " phần cuối" * 60
    assert "Kiểm Thử" in make_excerpt(text, "kiem thu", width=100)


def test_make_excerpt_short_text_is_returned_whole() -> None:
    assert make_excerpt("[A]\nNgắn gọn.", "gì đó") == "Ngắn gọn."


def test_fake_embeddings_are_deterministic_and_normalised() -> None:
    provider = FakeEmbeddingProvider(dimensions=64)
    first, second = asyncio.run(provider.embed(["kiểm thử đơn vị", "kiểm thử đơn vị"]))
    assert first == second
    assert math.sqrt(sum(v * v for v in first)) == pytest.approx(1.0)


def test_fake_embeddings_rank_overlapping_text_closer() -> None:
    provider = FakeEmbeddingProvider(dimensions=256)
    query, related, unrelated = asyncio.run(
        provider.embed(
            [
                "kiểm thử đơn vị",
                "chương này mô tả kiểm thử đơn vị cho module",
                "lịch sử thị trường chứng khoán",
            ]
        )
    )

    def cosine(a: list[float], b: list[float]) -> float:
        return sum(x * y for x, y in zip(a, b, strict=True))

    assert cosine(query, related) > cosine(query, unrelated)


def _settings(**overrides: str) -> Settings:
    return Settings(
        postgres_db="db", postgres_user="user", postgres_password="pw", **overrides
    )


def test_openai_provider_without_key_fails_only_when_called() -> None:
    provider = get_embedding_provider(_settings(embedding_api_key=""))
    assert isinstance(provider, OpenAIEmbeddingProvider)
    with pytest.raises(EmbeddingNotConfiguredError, match="EMBEDDING_API_KEY"):
        asyncio.run(provider.embed(["xin chào"]))


def test_fake_provider_selected_by_config() -> None:
    provider = get_embedding_provider(_settings(embedding_provider="fake"))
    assert isinstance(provider, FakeEmbeddingProvider)


def test_unknown_provider_raises_clear_error() -> None:
    with pytest.raises(EmbeddingNotConfiguredError, match="EMBEDDING_PROVIDER"):
        get_embedding_provider(_settings(embedding_provider="nope"))
