"""Bounded HTTPS GET restricted to public internet hosts.

Used for URLs that come from metadata providers rather than from code constants
(for example open-access PDF locations). Every hop, including redirects, must be
HTTPS on port 443 to a host whose every resolved address is globally routable; the
connection goes to the address that was checked, so DNS cannot be re-bound between
the check and the request. Addresses embedding an IPv4 address (NAT64,
IPv4-compatible) are judged by that IPv4 address. A whole fetch, redirects and
body included, stops after `_MAX_FETCH_SECONDS`, so a host trickling bytes cannot
hold a worker. Proxies from the environment are never used.
"""

from __future__ import annotations

import http.client
import ipaddress
import socket
import ssl
import time
from collections.abc import Collection
from urllib.parse import urljoin, urlsplit

_REDIRECTS = {301, 302, 303, 307, 308}
_MAX_FETCH_SECONDS = 60.0
_READ_CHUNK = 65_536
# A NAT64 gateway or IPv4-compatible address reaches the embedded IPv4 address.
_EMBEDDED_IPV4 = (
    ipaddress.ip_network("64:ff9b::/96"),
    ipaddress.ip_network("::/96"),
)


class _PinnedHTTPSConnection(http.client.HTTPSConnection):
    def __init__(self, host: str, address: str, timeout: float) -> None:
        context = ssl.create_default_context()
        context.minimum_version = ssl.TLSVersion.TLSv1_2
        super().__init__(host, 443, timeout=timeout, context=context)
        self._address = address

    def connect(self) -> None:
        sock = socket.create_connection((self._address, 443), self.timeout)
        self.sock = self._context.wrap_socket(sock, server_hostname=self.host)

    def set_timeout(self, seconds: float) -> None:
        """Bound every following socket operation, including a connect to come."""
        self.timeout = seconds
        if self.sock is not None:
            self.sock.settimeout(seconds)


def _is_public(address: str) -> bool:
    ip = ipaddress.ip_address(address.split("%", 1)[0])
    if ip.version == 6 and any(ip in network for network in _EMBEDDED_IPV4):
        ip = ipaddress.IPv4Address(int(ip) & 0xFFFFFFFF)
    return ip.is_global


def _public_address(host: str) -> str | None:
    try:
        infos = socket.getaddrinfo(host, 443, type=socket.SOCK_STREAM)
    except (OSError, UnicodeError):
        return None
    addresses = {info[4][0] for info in infos}
    if not addresses or not all(_is_public(address) for address in addresses):
        return None
    # IPv4 first: containers often lack an IPv6 route.
    return sorted(addresses, key=lambda address: (":" in address, address))[0]


def fetch_public_https(
    url: str,
    *,
    accept: str,
    content_types: Collection[str],
    max_bytes: int,
    timeout: float = 15.0,
    max_redirects: int = 3,
) -> bytes | None:
    """Body of a 200 response, or None for any refusal or failure."""
    deadline = time.monotonic() + _MAX_FETCH_SECONDS
    for _hop in range(max_redirects + 1):
        try:
            parts = urlsplit(url)
            port = parts.port
        except ValueError:
            return None
        if (
            parts.scheme != "https"
            or not parts.hostname
            or parts.username
            or parts.password
            or port not in (None, 443)
        ):
            return None
        address = _public_address(parts.hostname)
        if address is None:
            return None
        left = deadline - time.monotonic()
        if left <= 0:
            return None
        connection = _PinnedHTTPSConnection(parts.hostname, address, min(timeout, left))
        try:
            path = parts.path or "/"
            if parts.query:
                path = f"{path}?{parts.query}"
            connection.request(
                "GET",
                path,
                headers={"Accept": accept, "User-Agent": "DocGrading/1.0"},
            )
            connection.set_timeout(
                min(timeout, max(deadline - time.monotonic(), 0.001))
            )
            response = connection.getresponse()
            if response.status in _REDIRECTS:
                location = response.getheader("Location")
                if not location:
                    return None
                url = urljoin(url, location)
                continue
            if response.status != 200:
                return None
            content_type = (response.getheader("Content-Type") or "").split(";", 1)[0]
            if content_type.strip().lower() not in content_types:
                return None
            declared = response.getheader("Content-Length")
            if declared and declared.isdigit() and int(declared) > max_bytes:
                return None
            body = bytearray()
            while len(body) <= max_bytes:
                left = deadline - time.monotonic()
                if left <= 0:
                    return None
                # Each recv waits at most the time left; read1 returns after one
                # recv, where read(n) would loop until n bytes arrive.
                connection.set_timeout(min(timeout, left))
                chunk = response.read1(min(_READ_CHUNK, max_bytes + 1 - len(body)))
                if not chunk:
                    return bytes(body)
                body += chunk
            return None
        except (OSError, http.client.HTTPException, ValueError):
            return None
        finally:
            connection.close()
    return None
