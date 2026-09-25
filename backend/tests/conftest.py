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
