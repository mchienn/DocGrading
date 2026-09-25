from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def _no_chunk_indexing_publish(monkeypatch: pytest.MonkeyPatch) -> None:
    """Keep worker tests from publishing RAG indexing tasks to a real broker."""
    try:
        from app.workers import tasks
    except Exception:
        # Settings may be unavailable for tests that never touch the worker.
        return
    monkeypatch.setattr(tasks, "enqueue_chunk_indexing", lambda _version_id: True)


@pytest.fixture(autouse=True)
def _no_real_rag_providers(monkeypatch: pytest.MonkeyPatch) -> None:
    """Never call paid OpenAI APIs from tests, even when .env holds real keys.

    Tests that need a model patch these again with Fake* implementations.
    """
    try:
        from app.services import chat
        from app.services.rag import OpenAIChatClient
    except Exception:
        return
    monkeypatch.setattr(chat, "_rag_embedding_provider", lambda: None)
    monkeypatch.setattr(
        chat, "_rag_llm_client", lambda: OpenAIChatClient(api_key="", model="unset")
    )
