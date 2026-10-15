"""Public-HTTPS fetcher used for provider-supplied source URLs."""

from __future__ import annotations

from typing import Any

import pytest

from app.services import safe_fetch
from app.services.safe_fetch import fetch_public_https

_PDF = {"application/pdf"}


def _addresses(mapping: dict[str, str]) -> Any:
    def getaddrinfo(host: str, *_args: object, **_kwargs: object) -> list:
        return [(2, 1, 6, "", (mapping[host], 443))]

    return getaddrinfo


class _Response:
    def __init__(self, status: int, headers: dict[str, str], body: bytes = b"") -> None:
        self.status = status
        self._headers = headers
        self._body = body

    def getheader(self, name: str) -> str | None:
        return self._headers.get(name)

    def read(self, limit: int) -> bytes:
        return self._body[:limit]


def _fake_connections(
    monkeypatch: pytest.MonkeyPatch, responses: dict[str, _Response]
) -> list[tuple[str, str, str]]:
    connected: list[tuple[str, str, str]] = []

    class Connection:
        def __init__(self, host: str, address: str, _timeout: float) -> None:
            self.host = host
            self.address = address

        def request(self, _method: str, path: str, headers: dict) -> None:
            connected.append((self.host, self.address, path))
            self.path = path

        def getresponse(self) -> _Response:
            return responses[f"{self.host}{self.path}"]

        def close(self) -> None:
            return None

    monkeypatch.setattr(safe_fetch, "_PinnedHTTPSConnection", Connection)
    return connected


@pytest.mark.parametrize(
    "url",
    [
        "http://example.test/a.pdf",
        "https://example.test:8443/a.pdf",
        "https://user:pass@example.test/a.pdf",
        "file:///etc/passwd",
        "https://example.test:99999/a.pdf",
        "https://[::1/a.pdf",
    ],
)
def test_rejects_non_https_non_default_port_and_credentials(url: str) -> None:
    assert (
        fetch_public_https(url, accept="*/*", content_types=_PDF, max_bytes=10) is None
    )


@pytest.mark.parametrize(
    "address", ["127.0.0.1", "10.0.0.5", "169.254.169.254", "::1", "172.30.255.3"]
)
def test_rejects_hosts_resolving_to_non_public_addresses(
    monkeypatch: pytest.MonkeyPatch, address: str
) -> None:
    monkeypatch.setattr(
        safe_fetch.socket, "getaddrinfo", _addresses({"internal.test": address})
    )
    connected = _fake_connections(monkeypatch, {})

    result = fetch_public_https(
        "https://internal.test/a.pdf", accept="*/*", content_types=_PDF, max_bytes=10
    )

    assert result is None
    assert connected == []


def test_redirect_to_internal_host_is_refused_after_public_hop(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        safe_fetch.socket,
        "getaddrinfo",
        _addresses({"repo.test": "93.184.216.34", "metadata.test": "169.254.169.254"}),
    )
    connected = _fake_connections(
        monkeypatch,
        {
            "repo.test/a.pdf": _Response(
                302, {"Location": "https://metadata.test/latest"}
            ),
        },
    )

    result = fetch_public_https(
        "https://repo.test/a.pdf", accept="*/*", content_types=_PDF, max_bytes=10
    )

    assert result is None
    assert connected == [("repo.test", "93.184.216.34", "/a.pdf")]


def test_follows_public_redirect_and_enforces_type_and_size(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        safe_fetch.socket,
        "getaddrinfo",
        _addresses({"repo.test": "93.184.216.34", "cdn.test": "93.184.216.35"}),
    )
    _fake_connections(
        monkeypatch,
        {
            "repo.test/a.pdf": _Response(301, {"Location": "https://cdn.test/a.pdf"}),
            "cdn.test/a.pdf": _Response(
                200, {"Content-Type": "application/pdf"}, b"%PDF-1.7"
            ),
            "cdn.test/page": _Response(200, {"Content-Type": "text/html"}, b"<html>"),
            "cdn.test/big.pdf": _Response(
                200, {"Content-Type": "application/pdf"}, b"%PDF-" + b"x" * 20
            ),
        },
    )

    def fetch(url: str) -> bytes | None:
        return fetch_public_https(url, accept="*/*", content_types=_PDF, max_bytes=10)

    assert fetch("https://repo.test/a.pdf") == b"%PDF-1.7"
    assert fetch("https://cdn.test/page") is None
    assert fetch("https://cdn.test/big.pdf") is None
