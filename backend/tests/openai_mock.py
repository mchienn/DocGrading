"""Route the real ``openai`` SDK through an ``httpx.MockTransport`` in tests.

The handler may be sync or async (an async handler can hang to simulate a
provider that never answers). ``OpenAIMock`` records every request, every
cancelled request and every closed HTTP client, so tests can check that a
deadline really cut the call and left nothing open.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from typing import Any

import httpx
import openai
import pytest

Handler = Callable[[httpx.Request], httpx.Response | Awaitable[httpx.Response]]


def error_body(message: str) -> dict:
    return {"error": {"message": message, "type": "error", "code": None}}


def retry_after(seconds: int, status: int = 429) -> Handler:
    """The server asks the SDK to wait *seconds* before retrying."""

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            status,
            headers={"retry-after": str(seconds)},
            json=error_body("slow down"),
        )

    return handler


def chat_completion(content: str, prompt_tokens: int = 11, completion_tokens: int = 7):
    return {
        "id": "chatcmpl-test",
        "object": "chat.completion",
        "created": 0,
        "model": "gpt-test",
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", "content": content},
                "finish_reason": "stop",
            }
        ],
        "usage": {
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "total_tokens": prompt_tokens + completion_tokens,
        },
    }


def embedding_list(n: int, dimensions: int, tokens: int = 3) -> dict:
    return {
        "object": "list",
        "model": "emb-test",
        "data": [
            {"object": "embedding", "index": i, "embedding": [0.0] * dimensions}
            for i in range(n)
        ],
        "usage": {"prompt_tokens": tokens, "total_tokens": tokens},
    }


class OpenAIMock:
    def __init__(self, handler: Handler) -> None:
        self.handler = handler
        self.requests: list[httpx.Request] = []
        self.cancelled: list[str] = []
        self.clients_opened = 0
        self.clients_closed = 0

    async def _handle(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        try:
            result = self.handler(request)
            if asyncio.iscoroutine(result):
                result = await result
            return result  # type: ignore[return-value]
        except asyncio.CancelledError:
            self.cancelled.append(request.url.path)
            raise

    def install(self, monkeypatch: pytest.MonkeyPatch) -> OpenAIMock:
        real_client = openai.AsyncOpenAI
        mock = self

        class _TrackedClient(httpx.AsyncClient):
            async def aclose(self) -> None:
                mock.clients_closed += 1
                await super().aclose()

        def client_with_mock_transport(**kwargs: Any) -> openai.AsyncOpenAI:
            mock.clients_opened += 1
            http_client = _TrackedClient(transport=httpx.MockTransport(mock._handle))
            return real_client(**kwargs, http_client=http_client)

        monkeypatch.setattr(openai, "AsyncOpenAI", client_with_mock_transport)
        return self

    def paths(self) -> list[str]:
        return [r.url.path for r in self.requests]


async def hang(_request: httpx.Request) -> httpx.Response:
    """A provider that accepts the request and never answers."""
    await asyncio.sleep(3600)
    raise AssertionError("unreachable")
