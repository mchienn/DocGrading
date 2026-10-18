"""Fixed HTTPS adapters for hosted semantic providers."""

from __future__ import annotations

import json
import random
import re
import ssl
import threading
import time
import urllib.request
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from typing import Any, Protocol
from urllib.parse import quote

from app.models.enums import LLMProtocol, LLMProvider
from app.services.semantic_citation import (
    _SEMANTIC_SYSTEM_PROMPT,
    SEMANTIC_PROMPT_VERSION,
    SemanticModelVerdict,
    SemanticProviderError,
    SemanticSource,
    SemanticSourcePassage,
    SemanticVerdict,
    _prompt_fingerprint,
    parse_model_json,
    provider_semantic_payload,
)


class HTTPSJSONTransport(Protocol):
    def __call__(
        self,
        provider: LLMProvider,
        protocol: LLMProtocol,
        model: str,
        credential: str,
        body: bytes,
    ) -> bytes: ...


def _payload(
    claim: str,
    context: str,
    source: SemanticSource,
    passages: Sequence[SemanticSourcePassage],
    sensitive_values: Sequence[str] = (),
    *,
    display_name: str | None = None,
) -> str:
    data = provider_semantic_payload(
        claim=claim,
        context=context,
        source=source,
        passages=passages,
        sensitive_values=sensitive_values,
        display_name=display_name,
    )
    return (
        "<citation-data>"
        + json.dumps(data, ensure_ascii=False, separators=(",", ":"))
        + "</citation-data><allowed-verdicts>"
        + json.dumps([item.value for item in SemanticModelVerdict])
        + "</allowed-verdicts><json-schema>"
        + json.dumps(SemanticVerdict.model_json_schema(), separators=(",", ":"))
        + "</json-schema>"
    )


def _endpoint(provider: LLMProvider, protocol: LLMProtocol, model: str) -> str:
    base = {
        LLMProvider.OPENAI: "https://api.openai.com/v1",
        LLMProvider.DEEPSEEK: "https://api.deepseek.com",
        LLMProvider.ANTHROPIC: "https://api.anthropic.com/v1",
        LLMProvider.GEMINI: "https://generativelanguage.googleapis.com/v1beta",
        # OpenCode Console keys (oc_sk_*) are rejected by the legacy /zen/v1 Messages
        # and Gemini paths; /inference/v1 serves every protocol family.
        LLMProvider.OPENCODE_ZEN: "https://opencode.ai/inference/v1",
    }.get(provider)
    if base is None:
        raise SemanticProviderError("semantic provider unavailable")
    if protocol is LLMProtocol.OPENAI_CHAT:
        return f"{base}/chat/completions"
    if protocol is LLMProtocol.OPENAI_RESPONSES:
        return f"{base}/responses"
    if protocol is LLMProtocol.ANTHROPIC_MESSAGES:
        return f"{base}/messages"
    if protocol is LLMProtocol.GEMINI_GENERATE_CONTENT:
        return f"{base}/models/{quote(model, safe='')}:generateContent"
    raise SemanticProviderError("semantic provider unavailable")


def _request(
    provider: LLMProvider,
    protocol: LLMProtocol,
    model: str,
    credential: str,
    body: bytes,
) -> urllib.request.Request:
    if len(body) > 1_000_000:
        raise SemanticProviderError("semantic request too large")
    headers = {
        "Accept": "application/json",
        "Accept-Encoding": "identity",
        "Content-Type": "application/json",
        # Cloudflare-fronted providers (OpenCode Zen) reject urllib's default
        # "Python-urllib" agent with error 1010 before authentication.
        "User-Agent": "DocGrading/1.0",
    }
    if provider is LLMProvider.OPENCODE_ZEN or protocol in (
        LLMProtocol.OPENAI_CHAT,
        LLMProtocol.OPENAI_RESPONSES,
    ):
        headers["Authorization"] = f"Bearer {credential}"
    elif protocol is LLMProtocol.ANTHROPIC_MESSAGES:
        headers.update({"x-api-key": credential, "anthropic-version": "2023-06-01"})
    else:
        headers["x-goog-api-key"] = credential
    return urllib.request.Request(
        _endpoint(provider, protocol, model), data=body, headers=headers, method="POST"
    )


def _default_transport(
    provider: LLMProvider,
    protocol: LLMProtocol,
    model: str,
    credential: str,
    body: bytes,
) -> bytes:
    import urllib.error
    import urllib.request

    request = _request(provider, protocol, model, credential, body)

    class _NoRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, *_args: Any, **_kwargs: Any) -> None:
            return None

    context = ssl.create_default_context()
    context.minimum_version = ssl.TLSVersion.TLSv1_2
    opener = urllib.request.build_opener(
        urllib.request.ProxyHandler({}),
        _NoRedirect(),
        urllib.request.HTTPSHandler(context=context),
    )
    # Free tiers answer bursts (parallel claims) with 429; wait as the provider asks
    # (Retry-After header or Gemini's retryDelay) up to a bound, then give up. Up to
    # a second of jitter keeps parallel claims from retrying in lockstep.
    for attempt in range(3):
        try:
            with opener.open(request, timeout=30) as response:
                raw = response.read(1_000_001)
                if len(raw) > 1_000_000:
                    raise SemanticProviderError("semantic provider response too large")
                return raw
        except SemanticProviderError:
            raise
        except urllib.error.HTTPError as exc:
            if exc.code not in (429, 503) or attempt == 2:
                raise SemanticProviderError("semantic provider unavailable") from exc
            time.sleep(_retry_delay(exc, attempt) + random.uniform(0.0, 1.0))
        except (urllib.error.URLError, TimeoutError) as exc:
            raise SemanticProviderError("semantic provider unavailable") from exc
    raise SemanticProviderError("semantic provider unavailable")


_MAX_RETRY_DELAY_SECONDS = 30.0


def _retry_delay(error: Any, attempt: int) -> float:
    """Seconds to wait before retrying a rate-limited request."""
    delay: float | None = None
    header = (error.headers.get("Retry-After") or "").strip() if error.headers else ""
    if header.isdigit():
        delay = float(header)
    elif header:
        try:  # Retry-After may also be an HTTP-date; past or invalid means no wait
            when = parsedate_to_datetime(header)
        except (TypeError, ValueError, IndexError):
            when = None
        if when is not None:
            if when.tzinfo is None:
                when = when.replace(tzinfo=UTC)
            seconds = (when - datetime.now(UTC)).total_seconds()
            delay = seconds if seconds > 0 else None
    if delay is None:
        try:
            body = error.read(64_000).decode("utf-8", "replace")
        except Exception:
            body = ""
        match = re.search(r'"retryDelay"\s*:\s*"(\d+(?:\.\d+)?)s"', body)
        if match:
            delay = float(match.group(1))
    if delay is None:
        delay = 2.0 * 2**attempt
    return min(_MAX_RETRY_DELAY_SECONDS, max(0.0, delay))


class HostedSemanticModel:
    def __init__(
        self, config: Mapping[str, Any], *, transport: HTTPSJSONTransport | None = None
    ) -> None:
        self.provider = LLMProvider(str(config["provider"]))
        self.protocol = LLMProtocol(str(config["protocol"]))
        self.model_id = str(config.get("model_id") or "")
        self.region = str(config.get("region") or "") or None
        requested_tokens = int(config.get("max_tokens", 512))
        if not 1 <= requested_tokens <= 1024:
            raise ValueError("semantic max_tokens is invalid")
        self.max_tokens = requested_tokens
        self._credential = str(config.get("credential") or "")
        self._sensitive_values = tuple(
            str(value)
            for value in config.get("_redact_values", ())
            if isinstance(value, str)
        )
        self._display_name = (
            str(config.get("_redact_display_name")).strip()
            if config.get("_redact_display_name")
            else None
        )
        self._transport = transport or _default_transport
        self._lock = threading.Lock()
        self._calls = self._input_tokens = self._output_tokens = self._total_tokens = 0
        self._latency_ms = 0.0
        if not self.model_id or not self._credential:
            raise ValueError("semantic provider configuration is incomplete")

    def _request(self, user: str) -> bytes:
        if self.protocol is LLMProtocol.OPENAI_CHAT:
            body = {
                "model": self.model_id,
                "messages": [
                    {"role": "system", "content": _SEMANTIC_SYSTEM_PROMPT},
                    {"role": "user", "content": user},
                ],
                "temperature": 0,
                # OpenAI reasoning models reject max_tokens; DeepSeek and OpenCode
                # Zen chat-compatible endpoints still expect it.
                (
                    "max_completion_tokens"
                    if self.provider is LLMProvider.OPENAI
                    else "max_tokens"
                ): self.max_tokens,
                "tools": [],
            }
        elif self.protocol is LLMProtocol.OPENAI_RESPONSES:
            body = {
                "model": self.model_id,
                "instructions": _SEMANTIC_SYSTEM_PROMPT,
                "input": user,
                "temperature": 0,
                "max_output_tokens": self.max_tokens,
                "tools": [],
            }
        elif self.protocol is LLMProtocol.ANTHROPIC_MESSAGES:
            body = {
                "model": self.model_id,
                "system": _SEMANTIC_SYSTEM_PROMPT,
                "messages": [{"role": "user", "content": user}],
                "temperature": 0,
                "max_tokens": self.max_tokens,
                "tools": [],
            }
        else:
            body = {
                "systemInstruction": {"parts": [{"text": _SEMANTIC_SYSTEM_PROMPT}]},
                "contents": [
                    {
                        "role": "user",
                        "parts": [{"text": user}],
                    }
                ],
                "generationConfig": {
                    "temperature": 0,
                    "maxOutputTokens": self.max_tokens,
                },
            }
        return self._transport(
            self.provider,
            self.protocol,
            self.model_id,
            self._credential,
            json.dumps(body, ensure_ascii=False, separators=(",", ":")).encode(),
        )

    def evaluate(
        self,
        *,
        claim: str,
        context: str,
        source: SemanticSource,
        passages: Sequence[SemanticSourcePassage],
    ) -> Any:
        started = time.perf_counter()
        try:
            raw = self._request(
                _payload(
                    claim,
                    context,
                    source,
                    passages,
                    self._sensitive_values,
                    display_name=self._display_name,
                )
            )
            if len(raw) > 1_000_000:
                raise ValueError("provider response too large")
            response = json.loads(raw)
            text, usage = _response_text(self.protocol, response)
            if not text or len(text) > 64_000:
                raise ValueError("provider response invalid")
            with self._lock:
                self._calls += 1
                self._input_tokens += usage[0]
                self._output_tokens += usage[1]
                self._total_tokens += usage[2]
            return parse_model_json(text)
        except SemanticProviderError:
            raise
        except (ValueError, TypeError, json.JSONDecodeError):
            raise
        except Exception as exc:
            raise SemanticProviderError("semantic provider unavailable") from exc
        finally:
            with self._lock:
                self._latency_ms += (time.perf_counter() - started) * 1_000

    def audit_metadata(self) -> dict[str, Any]:
        with self._lock:
            return {
                "provider": self.provider.value,
                "protocol": self.protocol.value,
                "model_id": self.model_id,
                "region": self.region,
                "max_tokens": self.max_tokens,
                "prompt_version": SEMANTIC_PROMPT_VERSION,
                "prompt_fingerprint": _prompt_fingerprint(),
                "calls": self._calls,
                "input_tokens": self._input_tokens,
                "output_tokens": self._output_tokens,
                "total_tokens": self._total_tokens,
                "latency_ms": round(self._latency_ms, 3),
                "estimated_cost_usd": None,
            }


def _response_text(
    protocol: LLMProtocol, value: Any
) -> tuple[str, tuple[int, int, int]]:
    usage = (
        value.get("usage", value.get("usageMetadata", {}))
        if isinstance(value, Mapping)
        else {}
    )
    input_tokens = int(
        usage.get(
            "prompt_tokens", usage.get("input_tokens", usage.get("promptTokenCount", 0))
        )
        or 0
    )
    output_tokens = int(
        usage.get(
            "completion_tokens",
            usage.get("output_tokens", usage.get("candidatesTokenCount", 0)),
        )
        or 0
    )
    total = int(
        usage.get(
            "total_tokens", usage.get("totalTokenCount", input_tokens + output_tokens)
        )
        or 0
    )
    if protocol is LLMProtocol.OPENAI_CHAT:
        text = ((value.get("choices") or [{}])[0].get("message") or {}).get(
            "content", ""
        )
    elif protocol is LLMProtocol.OPENAI_RESPONSES:
        text = value.get("output_text", "")
        if not text:
            for row in value.get("output", []):
                for part in row.get("content", []) if isinstance(row, Mapping) else []:
                    if isinstance(part, Mapping) and isinstance(part.get("text"), str):
                        text += part["text"]
    elif protocol is LLMProtocol.ANTHROPIC_MESSAGES:
        text = "".join(
            part.get("text", "")
            for part in value.get("content", [])
            if isinstance(part, Mapping)
        )
    else:
        text = "".join(
            part.get("text", "")
            for candidate in value.get("candidates", [])
            if isinstance(candidate, Mapping)
            for part in (
                (candidate.get("content") or {}).get("parts", [])
                if isinstance(candidate.get("content"), Mapping)
                else []
            )
            if isinstance(part, Mapping)
        )
    return text if isinstance(text, str) else "", (
        max(0, input_tokens),
        max(0, output_tokens),
        max(0, total),
    )


def adapter_for_snapshot(
    snapshot: Mapping[str, Any],
    credential: str,
    *,
    transport: HTTPSJSONTransport | None = None,
) -> HostedSemanticModel:
    return HostedSemanticModel(
        {**snapshot, "credential": credential}, transport=transport
    )


OpenAISemanticModel = HostedSemanticModel
AnthropicSemanticModel = HostedSemanticModel
GeminiSemanticModel = HostedSemanticModel
OpenCodeZenSemanticModel = HostedSemanticModel
DeepSeekSemanticModel = HostedSemanticModel
